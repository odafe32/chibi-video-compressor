"""
Chibi - GUI front-end for ffmpeg-based batch video compression.

Ports the logic of compress_videos.ps1 into a desktop GUI:
 - hardware encoder detection (NVENC / QSV / AMF), verified with a real test encode
 - folder or multi-file selection
 - target-size-based bitrate calculation
 - fast (hw or software veryfast) / medium (software) / slow (software two-pass) modes
 - optional downscale to 720p
 - live per-file progress with ETA, using ffmpeg's -progress pipe

ffmpeg.exe and ffprobe.exe are embedded in the built exe (via PyInstaller
--add-binary) and extracted at runtime. A copy placed next to the exe
overrides the embedded one, if you ever want to swap ffmpeg builds.
"""

import os
import re
import sys
import queue
import shutil
import threading
import subprocess
import tempfile
import uuid
import webbrowser
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

# Forced dark theme - deliberate, not left to the OS setting, so the app
# looks the same and looks intentional on every machine it runs on.
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "1.0.0"
AUTHOR_NAME = "Godfrey Joseph Sule"
AUTHOR_GITHUB = "https://github.com/odafe32/"
AUTHOR_LINKEDIN = "https://www.linkedin.com/in/godfrey-joseph-a06370248/"

# ---------------------------------------------------------------------------
# Design tokens - single source of truth for the whole UI's look
# ---------------------------------------------------------------------------
COLORS = {
    "bg":           "#0A0E1A",   # deep dark background
    "bg_secondary": "#0F1419",   # slightly lighter bg
    "card":         "#161B26",   # elevated card background
    "card_hover":   "#1C2230",   # card hover state
    "card_border":  "#1F2937",   # subtle border
    "accent":       "#6366F1",   # vibrant indigo
    "accent_hover": "#4F46E5",   # deeper indigo
    "accent_glow":  "#818CF8",   # lighter glow
    "text":         "#F9FAFB",   # crisp white
    "text_secondary": "#9CA3AF", # medium gray
    "text_dim":     "#6B7280",   # dim gray
    "success":      "#10B981",   # emerald green
    "success_bg":   "#064E3B",   # dark green bg
    "warning":      "#F59E0B",   # amber
    "danger":       "#EF4444",   # red
    "danger_hover": "#DC2626",   # darker red
    "track":        "#1F2937",   # input/track background
    "divider":      "#374151",   # divider line
}
FONT_FAMILY = "Segoe UI" if os.name == "nt" else ("SF Pro Text" if sys.platform == "darwin" else "Ubuntu")

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def app_dir() -> Path:
    """Directory the exe/script lives in (works for PyInstaller onefile too)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Where PyInstaller onefile extracts embedded data/binaries at runtime
    (sys._MEIPASS). Falls back to the script's own folder when not frozen."""
    return Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))


def locate_binary(name: str) -> Path:
    """Prefer a copy sitting next to the exe (lets an advanced user swap in
    their own ffmpeg build); otherwise use the one embedded in the exe."""
    beside_exe = app_dir() / name
    if beside_exe.exists():
        return beside_exe
    return bundle_dir() / name


FFMPEG = locate_binary("ffmpeg.exe")
FFPROBE = locate_binary("ffprobe.exe")


def asset_path(name: str) -> Path:
    """Locate a bundled asset (e.g. icon file), checking next to the exe/
    script first, then the PyInstaller-extracted bundle, then ./assets/."""
    for base in (app_dir(), bundle_dir(), app_dir() / "assets", bundle_dir() / "assets"):
        candidate = base / name
        if candidate.exists():
            return candidate
    return app_dir() / name


# ---------------------------------------------------------------------------
# Backend logic (mirrors compress_videos.ps1)
# ---------------------------------------------------------------------------

def run_hidden(args, **kwargs):
    return subprocess.run(
        args, creationflags=CREATE_NO_WINDOW,
        capture_output=True, text=True, **kwargs
    )


def test_hw_encoder(name: str) -> bool:
    test_args = [
        str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=128x128:rate=1",
        "-frames:v", "1", "-c:v", name, "-f", "null", "-",
    ]
    try:
        p = run_hidden(test_args, timeout=15)
        return p.returncode == 0
    except Exception:
        return False


def detect_hw_encoder() -> str | None:
    try:
        p = run_hidden([str(FFMPEG), "-hide_banner", "-encoders"])
        listing = p.stdout + p.stderr
    except Exception:
        return None
    candidates = []
    if "h264_nvenc" in listing:
        candidates.append("h264_nvenc")
    if "h264_qsv" in listing:
        candidates.append("h264_qsv")
    if "h264_amf" in listing:
        candidates.append("h264_amf")
    for cand in candidates:
        if test_hw_encoder(cand):
            return cand
    return None


def ffprobe_duration(path: str) -> float | None:
    p = run_hidden([
        str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    try:
        return float(p.stdout.strip())
    except Exception:
        return None


def ffprobe_resolution(path: str) -> str:
    p = run_hidden([
        str(FFPROBE), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path,
    ])
    return p.stdout.strip() or "unknown"


def compress_image(input_path: str, output_path: str, target_pct: float) -> bool:
    """Compress an image to target percentage of original size using PIL."""
    try:
        from PIL import Image
        import io
        
        img = Image.open(input_path)
        
        # Convert RGBA to RGB if saving as JPEG
        if img.mode in ('RGBA', 'LA', 'P') and output_path.lower().endswith(('.jpg', '.jpeg')):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        original_size = Path(input_path).stat().st_size
        target_size = original_size * (target_pct / 100.0)
        
        # Binary search for the right quality
        quality_low, quality_high = 10, 95
        best_quality = 85
        
        for _ in range(8):  # 8 iterations should be enough
            quality = (quality_low + quality_high) // 2
            buffer = io.BytesIO()
            
            save_kwargs = {'quality': quality, 'optimize': True}
            if output_path.lower().endswith('.png'):
                save_kwargs = {'optimize': True, 'compress_level': 9}
            elif output_path.lower().endswith('.webp'):
                save_kwargs = {'quality': quality, 'method': 6}
            
            img.save(buffer, format=img.format or 'JPEG', **save_kwargs)
            current_size = buffer.tell()
            
            if abs(current_size - target_size) < target_size * 0.05:  # within 5%
                best_quality = quality
                break
            elif current_size > target_size:
                quality_high = quality - 1
            else:
                quality_low = quality + 1
                best_quality = quality
        
        # Save with best quality found
        save_kwargs = {'quality': best_quality, 'optimize': True}
        if output_path.lower().endswith('.png'):
            save_kwargs = {'optimize': True, 'compress_level': 9}
        elif output_path.lower().endswith('.webp'):
            save_kwargs = {'quality': best_quality, 'method': 6}
        
        img.save(output_path, **save_kwargs)
        return Path(output_path).exists()
    except Exception as e:
        return False


def get_encoder_args(encoder, preset, bitrate, maxrate, bufsize, pass_num=None, passlog=None):
    a = ["-c:v", encoder]
    if "nvenc" in encoder:
        a += ["-preset", preset, "-rc", "vbr", "-b:v", bitrate, "-maxrate", maxrate, "-bufsize", bufsize]
    elif "qsv" in encoder:
        a += ["-preset", preset, "-b:v", bitrate, "-maxrate", maxrate, "-bufsize", bufsize]
    elif "amf" in encoder:
        a += ["-quality", preset, "-rc", "vbr_peak", "-b:v", bitrate, "-maxrate", maxrate, "-bufsize", bufsize]
    else:
        a += ["-preset", preset, "-b:v", bitrate, "-maxrate", maxrate, "-bufsize", bufsize]
        if pass_num:
            a += ["-pass", pass_num, "-passlogfile", passlog]
    return a


FATAL_RE = re.compile(
    r"(Error opening|Cannot load|Invalid argument|No such file|"
    r"Error while opening encoder|Conversion failed|Error initializing|could not open)",
    re.IGNORECASE,
)
OUT_TIME_RE = re.compile(rb"out_time_ms=(\d+)")
SPEED_RE = re.compile(rb"speed=\s*([\d.]+)x")


def run_ffmpeg_pass(input_file, extra_args, out_target, duration, progress_cb, cancel_evt):
    """Runs one ffmpeg pass, streaming -progress data to progress_cb(pct, speed, eta_txt).
    Returns (ok: bool, stderr_text: str)."""
    args = [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-i", input_file] \
        + extra_args + ["-progress", "pipe:1", "-nostats", out_target]

    stderr_path = Path(tempfile.gettempdir()) / f"vc_err_{uuid.uuid4().hex}.log"
    with open(stderr_path, "wb") as errf:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=errf,
            creationflags=CREATE_NO_WINDOW,
        )
        buf = b""
        cur_sec = 0.0
        speed_val = 0.0
        while True:
            if cancel_evt.is_set():
                proc.terminate()
                break
            chunk = proc.stdout.readline()
            if not chunk:
                if proc.poll() is not None:
                    break
                continue
            buf += chunk
            m = OUT_TIME_RE.search(chunk)
            if m:
                cur_sec = int(m.group(1)) / 1_000_000.0
            m2 = SPEED_RE.search(chunk)
            if m2:
                speed_val = float(m2.group(1))
            pct = min(99.9, (cur_sec / max(duration, 0.01)) * 100.0)
            eta_txt = "calculating..."
            if speed_val > 0.01:
                remaining = max(duration - cur_sec, 0)
                secs = int(remaining / speed_val)
                eta_txt = f"{secs // 3600:02d}h {(secs % 3600) // 60:02d}m {secs % 60:02d}s"
            progress_cb(pct, speed_val, eta_txt)
        proc.wait()

    stderr_text = ""
    try:
        stderr_text = stderr_path.read_text(errors="ignore")
    except Exception:
        pass
    finally:
        stderr_path.unlink(missing_ok=True)

    has_fatal = bool(FATAL_RE.search(stderr_text))
    if out_target == "NUL" or out_target == os.devnull:
        ok = not has_fatal
    else:
        ok = Path(out_target).exists() and Path(out_target).stat().st_size > 0 and not has_fatal
    return ok, stderr_text


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ChibiApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Chibi — by {AUTHOR_NAME}")
        self.geometry("920x880")
        self.minsize(840, 720)
        self.configure(fg_color=COLORS["bg"])
        self._set_window_icon()

        self.files: list[str] = []
        self.out_dir: str | None = None
        self.hw_encoder: str | None = None
        self.cancel_evt = threading.Event()
        self.worker: threading.Thread | None = None
        self.msg_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._check_binaries()
        self.after(100, self._poll_queue)
        threading.Thread(target=self._detect_hw_bg, daemon=True).start()

    def _set_window_icon(self):
        """Cross-platform window/taskbar icon."""
        try:
            if os.name == "nt":
                ico = asset_path("Chibi.ico")
                if ico.exists():
                    try:
                        self.iconbitmap(default=str(ico.resolve()))
                        return
                    except Exception:
                        pass  # fall through to PNG path
            # Fallback: use PIL to load PNG as the window icon
            png = asset_path("Chibi_256.png")
            if png.exists():
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(str(png)).resize((64, 64), Image.LANCZOS)
                    self._icon_img = ImageTk.PhotoImage(img)
                    self.iconphoto(True, self._icon_img)
                    return
                except Exception:
                    pass
                try:
                    self._icon_img = tk.PhotoImage(file=str(png))
                    self.iconphoto(True, self._icon_img)
                except Exception:
                    pass
        except Exception:
            pass  # missing icon should never crash the app

    # -- UI construction -----------------------------------------------
    def _card(self, parent, title=None, has_glow=False):
        """A consistently-styled section container with optional glow effect."""
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=16,
                             border_width=1, border_color=COLORS["card_border"])
        if title:
            title_frame = ctk.CTkFrame(card, fg_color="transparent")
            title_frame.grid(row=0, column=0, columnspan=6, sticky="ew", padx=20, pady=(18, 12))
            
            ctk.CTkLabel(title_frame, text=title.upper(), 
                         font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold", slant="roman"),
                         text_color=COLORS["text_secondary"]).pack(side="left")
            
            if has_glow:
                glow_indicator = ctk.CTkLabel(title_frame, text="●", 
                                              font=ctk.CTkFont(size=10),
                                              text_color=COLORS["accent_glow"])
                glow_indicator.pack(side="left", padx=(8, 0))
        return card

    def _build_ui(self):
        outer_pad = {"padx": 24, "pady": (0, 16)}

        # ---- Header -----------------------------------------------------
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_secondary"], corner_radius=0)
        header.pack(fill="x", padx=0, pady=(0, 24))
        
        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="x", padx=28, pady=24)

        icon_png = asset_path("Chibi_256.png")
        if icon_png.exists():
            try:
                from PIL import Image
                pil_icon = Image.open(icon_png)
                ctk_icon = ctk.CTkImage(light_image=pil_icon, dark_image=pil_icon, size=(52, 52))
                ctk.CTkLabel(header_inner, image=ctk_icon, text="").pack(side="left", padx=(0, 16))
            except Exception:
                ctk.CTkLabel(header_inner, text="C",
                             font=ctk.CTkFont(family=FONT_FAMILY, size=28, weight="bold"),
                             text_color=COLORS["accent"],
                             fg_color=COLORS["card"], corner_radius=12,
                             width=52, height=52).pack(side="left", padx=(0, 16))
        else:
            ctk.CTkLabel(header_inner, text="C",
                         font=ctk.CTkFont(family=FONT_FAMILY, size=28, weight="bold"),
                         text_color=COLORS["accent"],
                         fg_color=COLORS["card"], corner_radius=12,
                         width=52, height=52).pack(side="left", padx=(0, 16))

        title_block = ctk.CTkFrame(header_inner, fg_color="transparent")
        title_block.pack(side="left", fill="x", expand=True)
        
        title_container = ctk.CTkFrame(title_block, fg_color="transparent")
        title_container.pack(anchor="w")
        
        ctk.CTkLabel(title_container, text="Chibi",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=32, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left")
        
        version_badge = ctk.CTkFrame(title_container, fg_color=COLORS["card"], corner_radius=6)
        version_badge.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(version_badge, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).pack(padx=8, pady=4)
        
        ctk.CTkLabel(title_block, text="Compress heavy videos & images — reduce file sizes dramatically",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=14),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(6, 0))

        status_block = ctk.CTkFrame(header_inner, fg_color=COLORS["card"], corner_radius=10)
        status_block.pack(side="right", anchor="e", padx=0, pady=0)
        
        status_inner = ctk.CTkFrame(status_block, fg_color="transparent")
        status_inner.pack(padx=14, pady=10)
        
        self.hw_dot = ctk.CTkLabel(status_inner, text="●", font=ctk.CTkFont(size=14),
                                    text_color=COLORS["text_dim"], width=16)
        self.hw_dot.pack(side="left")
        self.hw_label = ctk.CTkLabel(status_inner, text="Checking hardware…",
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                                      text_color=COLORS["text_secondary"])
        self.hw_label.pack(side="left", padx=(6, 0))

        # ---- Scrollable body container -----------------------------------
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg"], corner_radius=0,
                                              scrollbar_button_color=COLORS["card"],
                                              scrollbar_button_hover_color=COLORS["accent"])
        self.scroll.pack(fill="both", expand=True, padx=0, pady=0)

        def _card_in_scroll(title=None, has_glow=False):
            return self._card(self.scroll, title, has_glow)

        # ---- Source selection --------------------------------------------
        src_frame = _card_in_scroll("Source Selection")
        src_frame.pack(fill="x", **outer_pad)
        src_frame.grid_columnconfigure(2, weight=1)

        mode_container = ctk.CTkFrame(src_frame, fg_color="transparent")
        mode_container.grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 14))
        
        self.mode_var = ctk.StringVar(value="folder")
        
        folder_btn = ctk.CTkRadioButton(mode_container, text="📁  Whole Folder", 
                                        variable=self.mode_var, value="folder",
                                        command=self._on_mode_change, fg_color=COLORS["accent"],
                                        hover_color=COLORS["accent_hover"],
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=14))
        folder_btn.pack(side="left", padx=(0, 16))
        
        files_btn = ctk.CTkRadioButton(mode_container, text="�️  Specific Files", 
                                       variable=self.mode_var, value="files",
                                       command=self._on_mode_change, fg_color=COLORS["accent"],
                                       hover_color=COLORS["accent_hover"],
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=14))
        files_btn.pack(side="left")

        self.browse_btn = ctk.CTkButton(src_frame, text="Browse Files", width=140, height=38,
                                         corner_radius=10, fg_color=COLORS["accent"],
                                         hover_color=COLORS["accent_hover"], text_color="white",
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                                         command=self._browse)
        self.browse_btn.grid(row=1, column=3, sticky="e", padx=20, pady=(0, 14))

        path_container = ctk.CTkFrame(src_frame, fg_color=COLORS["track"], corner_radius=10)
        path_container.grid(row=2, column=0, columnspan=4, sticky="ew", padx=20, pady=(0, 20))
        
        self.path_label = ctk.CTkLabel(path_container, text="No files selected",
                                        anchor="w", justify="left",
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                                        text_color=COLORS["text_secondary"])
        self.path_label.pack(fill="x", padx=16, pady=14)

        # ---- Settings ------------------------------------------------------
        set_frame = _card_in_scroll("Compression Settings")
        set_frame.pack(fill="x", **outer_pad)
        set_frame.grid_columnconfigure(0, weight=1)
        set_frame.grid_columnconfigure(1, weight=1)

        # Left column - Target Size
        left_col = ctk.CTkFrame(set_frame, fg_color="transparent")
        left_col.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(left_col, text="Target Size", 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 8))
        
        pct_container = ctk.CTkFrame(left_col, fg_color=COLORS["track"], corner_radius=10)
        pct_container.pack(fill="x")
        
        pct_inner = ctk.CTkFrame(pct_container, fg_color="transparent")
        pct_inner.pack(fill="x", padx=14, pady=12)
        
        self.pct_entry = ctk.CTkEntry(pct_inner, width=70, height=36, corner_radius=8,
                                       fg_color=COLORS["card"], border_width=1,
                                       border_color=COLORS["divider"],
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
                                       justify="center")
        self.pct_entry.insert(0, "10")
        self.pct_entry.pack(side="left")
        
        ctk.CTkLabel(pct_inner, text="% of original size", 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                     text_color=COLORS["text_secondary"]).pack(side="left", padx=(12, 0))
        
        self.downscale_var = ctk.BooleanVar(value=False)
        downscale_check = ctk.CTkCheckBox(left_col, text="⬇️  Downscale videos to 720p", 
                                          variable=self.downscale_var,
                                          fg_color=COLORS["accent"], 
                                          hover_color=COLORS["accent_hover"],
                                          font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                                          checkbox_width=20, checkbox_height=20)
        downscale_check.pack(anchor="w", pady=(12, 0))

        # Right column - Speed
        right_col = ctk.CTkFrame(set_frame, fg_color="transparent")
        right_col.grid(row=1, column=1, sticky="nsew", padx=20, pady=(0, 20))
        
        ctk.CTkLabel(right_col, text="Encoding Speed", 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 8))
        
        self.speed_var = ctk.StringVar(value="fast")
        
        speed_options = [
            ("fast", "⚡ Fast", "Hardware accelerated"),
            ("medium", "⚙️  Medium", "Balanced quality"),
            ("slow", "🎯 Best", "2-pass, highest quality")
        ]
        
        for val, label, desc in speed_options:
            speed_card = ctk.CTkFrame(right_col, fg_color=COLORS["track"], corner_radius=10)
            speed_card.pack(fill="x", pady=(0, 8))
            
            radio = ctk.CTkRadioButton(speed_card, text="", variable=self.speed_var, value=val,
                                       fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"])
            radio.pack(side="left", padx=(12, 8), pady=10)
            
            text_frame = ctk.CTkFrame(speed_card, fg_color="transparent")
            text_frame.pack(side="left", fill="x", expand=True, pady=10)
            
            ctk.CTkLabel(text_frame, text=label, anchor="w",
                         font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                         text_color=COLORS["text"]).pack(anchor="w")
            ctk.CTkLabel(text_frame, text=desc, anchor="w",
                         font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                         text_color=COLORS["text_dim"]).pack(anchor="w")

        # ---- Controls --------------------------------------------------
        ctrl_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=24, pady=(0, 16))
        
        self.start_btn = ctk.CTkButton(ctrl_frame, text="🚀  Start Compression", command=self._start,
                                        height=50, corner_radius=12, fg_color=COLORS["accent"],
                                        hover_color=COLORS["accent_hover"], text_color="white",
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=15, weight="bold"))
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 12))
        
        self.cancel_btn = ctk.CTkButton(ctrl_frame, text="✕  Cancel", command=self._cancel,
                                         width=120, height=50, corner_radius=12, 
                                         fg_color="transparent",
                                         border_width=2, border_color=COLORS["danger"],
                                         hover_color=COLORS["danger"], text_color=COLORS["danger"],
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                                         state="disabled")
        self.cancel_btn.pack(side="left")

        # ---- Progress -----------------------------------------------------
        prog_frame = _card_in_scroll("Progress", has_glow=False)
        prog_frame.pack(fill="x", padx=24, pady=(0, 16))
        self.prog_frame_ref = prog_frame
        prog_frame.grid_columnconfigure(0, weight=1)

        self.file_label = ctk.CTkLabel(prog_frame, text="Ready to compress", anchor="w",
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
                                        text_color=COLORS["text"])
        self.file_label.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        
        self.progress_bar = ctk.CTkProgressBar(prog_frame, height=16, corner_radius=8,
                                                fg_color=COLORS["track"], 
                                                progress_color=COLORS["accent"])
        self.progress_bar.set(0)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 12))
        
        # Stats row - prominent display of %, speed, and ETA
        stats_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        stats_row.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        
        # Percentage stat
        pct_card = ctk.CTkFrame(stats_row, fg_color=COLORS["track"], corner_radius=10)
        pct_card.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkLabel(pct_card, text="PROGRESS", anchor="w",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color=COLORS["text_dim"]).pack(anchor="w", padx=14, pady=(10, 2))
        self.pct_stat = ctk.CTkLabel(pct_card, text="0.0%", anchor="w",
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
                                      text_color=COLORS["accent"])
        self.pct_stat.pack(anchor="w", padx=14, pady=(0, 12))
        
        # Speed stat
        speed_card = ctk.CTkFrame(stats_row, fg_color=COLORS["track"], corner_radius=10)
        speed_card.pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(speed_card, text="SPEED", anchor="w",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color=COLORS["text_dim"]).pack(anchor="w", padx=14, pady=(10, 2))
        self.speed_stat = ctk.CTkLabel(speed_card, text="—", anchor="w",
                                        font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
                                        text_color=COLORS["text"])
        self.speed_stat.pack(anchor="w", padx=14, pady=(0, 12))
        
        # ETA stat
        eta_card = ctk.CTkFrame(stats_row, fg_color=COLORS["track"], corner_radius=10)
        eta_card.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkLabel(eta_card, text="TIME LEFT", anchor="w",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
                     text_color=COLORS["text_dim"]).pack(anchor="w", padx=14, pady=(10, 2))
        self.eta_stat = ctk.CTkLabel(eta_card, text="—", anchor="w",
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
                                      text_color=COLORS["success"])
        self.eta_stat.pack(anchor="w", padx=14, pady=(0, 12))
        
        # Keep detail_label for extra info but hidden
        self.detail_label = ctk.CTkLabel(prog_frame, text="", anchor="w",
                                          font=ctk.CTkFont(family="Consolas", size=11),
                                          text_color=COLORS["text_dim"])

        # ---- Log -----------------------------------------------------------
        log_frame = _card_in_scroll("Activity Log")
        log_frame.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        self.log_box = ctk.CTkTextbox(log_frame, wrap="word", fg_color=COLORS["bg"],
                                       text_color=COLORS["text_secondary"], corner_radius=10,
                                       border_width=1, border_color=COLORS["divider"],
                                       font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.log_box.configure(state="disabled")

        # ---- Footer / credits --------------------------------------------
        footer = ctk.CTkFrame(self, fg_color=COLORS["bg_secondary"], corner_radius=0)
        footer.pack(side="bottom", fill="x", padx=0, pady=0)
        
        footer_inner = ctk.CTkFrame(footer, fg_color="transparent")
        footer_inner.pack(fill="x", padx=28, pady=16)

        info_frame = ctk.CTkFrame(footer_inner, fg_color="transparent")
        info_frame.pack(side="left")
        
        ctk.CTkLabel(info_frame, text=f"Chibi v{APP_VERSION}",
                     text_color=COLORS["text_secondary"], 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")).pack(side="left")
        
        ctk.CTkLabel(info_frame, text="  •  ",
                     text_color=COLORS["text_dim"], 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11)).pack(side="left")
        
        ctk.CTkLabel(info_frame, text=f"by {AUTHOR_NAME}",
                     text_color=COLORS["text_dim"], 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=11)).pack(side="left")

        links = ctk.CTkFrame(footer_inner, fg_color="transparent")
        links.pack(side="right")
        
        for label, url in [("GitHub", AUTHOR_GITHUB), ("LinkedIn", AUTHOR_LINKEDIN)]:
            link_btn = ctk.CTkButton(links, text=label, width=70, height=28, 
                                     fg_color=COLORS["card"],
                                     hover_color=COLORS["card_hover"],
                                     text_color=COLORS["accent"], corner_radius=8,
                                     font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                                     cursor="hand2",
                                     command=lambda u=url: webbrowser.open(u))
            link_btn.pack(side="right", padx=(8, 0))

    def _check_binaries(self):
        if not FFMPEG.exists() or not FFPROBE.exists():
            messagebox.showerror(
                "Missing files",
                "ffmpeg.exe / ffprobe.exe could not be found (checked next to the exe "
                f"and the embedded bundle: {bundle_dir()}).\nIf you're running gui_app.py "
                "directly (not the built exe), put ffmpeg.exe and ffprobe.exe next to it."
            )

    # -- helpers ----------------------------------------------------------
    def _log(self, text: str, replace_last=False):
        self.log_box.configure(state="normal")
        if replace_last:
            self.log_box.delete("end-2l", "end-1l")
            self.log_box.insert("end", text + "\n")
        else:
            self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_mode_change(self):
        self.files = []
        self.path_label.configure(text="No files selected")

    def _browse(self):
        if self.mode_var.get() == "folder":
            folder = filedialog.askdirectory(title="Select folder to compress")
            if not folder:
                return
            found = [str(p) for p in Path(folder).iterdir()
                     if p.is_file() and p.suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)]
            self.files = found
            self.out_dir = str(Path(folder) / "Compressed")
            
            video_count = sum(1 for f in found if Path(f).suffix.lower() in VIDEO_EXTS)
            image_count = sum(1 for f in found if Path(f).suffix.lower() in IMAGE_EXTS)
            
            summary = []
            if video_count:
                summary.append(f"{video_count} video(s)")
            if image_count:
                summary.append(f"{image_count} image(s)")
            
            self.path_label.configure(text=f"📁  {folder}  •  {', '.join(summary)} found")
        else:
            paths = filedialog.askopenfilenames(
                title="Select video/image file(s)",
                filetypes=[
                    ("Videos & Images", "*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.jpg *.jpeg *.png *.webp *.bmp *.tiff *.tif"),
                    ("Video files", "*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v"),
                    ("Image files", "*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.tif"),
                    ("All files", "*.*")
                ],
            )
            if not paths:
                return
            self.files = list(paths)
            self.out_dir = str(Path(paths[0]).parent / "Compressed")
            self.path_label.configure(text=f"✅  {len(paths)} file(s) selected")

    def _detect_hw_bg(self):
        enc = detect_hw_encoder()
        self.msg_queue.put(("hw", enc))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "hw":
                    self.hw_encoder = payload
                    if payload:
                        self.hw_dot.configure(text_color=COLORS["success"])
                        self.hw_label.configure(
                            text=f"⚡ {payload.upper()}",
                            text_color=COLORS["success"])
                    else:
                        self.hw_dot.configure(text_color=COLORS["warning"])
                        self.hw_label.configure(
                            text="Software encoding",
                            text_color=COLORS["text_secondary"])
                elif kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    file_txt, pct, speed, eta = payload
                    self.file_label.configure(text=file_txt)
                    self.progress_bar.set(max(0.0, min(1.0, pct / 100.0)))
                    self.pct_stat.configure(text=f"{pct:.1f}%")
                    self.speed_stat.configure(text=f"{speed:.2f}x" if speed > 0 else "—")
                    self.eta_stat.configure(text=eta if eta != "calculating..." else "...")
                    self.detail_label.configure(text=f"{pct:.1f}%  •  {speed:.2f}x speed  •  ETA: {eta}")
                elif kind == "done":
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.file_label.configure(text="✅  Compression complete!")
                    self.progress_bar.set(1.0)
                    self.pct_stat.configure(text="100.0%")
                    self.speed_stat.configure(text="—")
                    self.eta_stat.configure(text="Done")
                    messagebox.showinfo("Finished", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # -- run ----------------------------------------------------------
    def _start(self):
        if not FFMPEG.exists() or not FFPROBE.exists():
            self._check_binaries()
            return
        if not self.files:
            messagebox.showwarning("No files", "Please select a folder or file(s) first.")
            return
        try:
            target_pct = float(self.pct_entry.get())
            if target_pct <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid value", "Target size % must be a positive number.")
            return

        os.makedirs(self.out_dir, exist_ok=True)
        self.cancel_evt.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._run_batch,
            args=(list(self.files), target_pct, self.speed_var.get(), self.downscale_var.get()),
            daemon=True,
        )
        self.worker.start()
        self.after(200, lambda: self.scroll._parent_canvas.yview_moveto(0.5))

    def _cancel(self):
        self.cancel_evt.set()
        self.msg_queue.put(("log", "Cancelling after current step..."))

    def _run_batch(self, files, target_pct, speed, downscale):
        encoder, preset, mode = "libx264", "medium", "single"
        if speed == "fast":
            preset = "veryfast"
            if self.hw_encoder:
                encoder = self.hw_encoder
                preset = {"h264_nvenc": "p1", "h264_qsv": "veryfast", "h264_amf": "speed"}[self.hw_encoder]
        elif speed == "slow":
            mode = "twopass"

        self.msg_queue.put(("log", f"Starting batch compression | Target: {target_pct}% of original size"))
        scale = "-2:720" if downscale else None
        total = len(files)

        for idx, f in enumerate(files, start=1):
            if self.cancel_evt.is_set():
                self.msg_queue.put(("log", "Cancelled."))
                break
            
            fname = Path(f).stem
            file_ext = Path(f).suffix.lower()
            is_image = file_ext in IMAGE_EXTS
            
            self.msg_queue.put(("log", f"\n=== [{idx}/{total}] {fname}{file_ext} ==="))
            orig_size = Path(f).stat().st_size
            
            # Handle images separately
            if is_image:
                self.msg_queue.put(("log", f"  Type: Image | Original: {orig_size/1_000_000:.2f} MB"))
                out_file = str(Path(self.out_dir) / f"{fname}{file_ext}")
                
                self.msg_queue.put(("progress", (f"[{idx}/{total}] Compressing image: {fname}{file_ext}", 50, 0, "a few seconds")))
                
                ok = compress_image(f, out_file, target_pct)
                if ok:
                    new_size = Path(out_file).stat().st_size
                    reduction = ((orig_size - new_size) / orig_size) * 100
                    self.msg_queue.put(("progress", (f"[{idx}/{total}] ✅ {fname}{file_ext} done", 100, 0, "Done")))
                    self.msg_queue.put(("log", f"  ✅ Done -> {new_size/1_000_000:.2f} MB ({reduction:.1f}% reduction)"))
                else:
                    self.msg_queue.put(("log", f"  ❌ [ERROR] Image compression failed"))
                continue
            
            # Handle videos
            self.msg_queue.put(("log", f"  Type: Video | Encoder: {encoder} | Mode: {mode}"))
            duration = ffprobe_duration(f)
            if not duration:
                self.msg_queue.put(("log", "  ❌ Could not read duration - skipping."))
                continue
            resolution = ffprobe_resolution(f)

            total_kbps = (orig_size * 8 * (target_pct / 100.0)) / duration / 1000.0
            audio_kbps = 128
            vid_kbps = max(total_kbps - audio_kbps, 100)
            max_kbps = vid_kbps * 1.5
            buf_kbps = vid_kbps * 2.0

            self.msg_queue.put(("log",
                f"  Duration: {duration:.1f}s | Resolution: {resolution} | "
                f"Original: {orig_size/1_000_000:.1f} MB | Target video bitrate: {vid_kbps:.0f}k"))

            out_file = str(Path(self.out_dir) / f"{fname}.mp4")
            passlog = str(Path(tempfile.gettempdir()) / f"vc_pass_{uuid.uuid4().hex}")
            vf = ["-vf", f"scale={scale}"] if scale else []

            def progress_cb(pct, spd, eta, label="Encoding"):
                self.msg_queue.put(("progress", (f"File {idx}/{total}: {fname} - {label}", pct, spd, eta)))

            ok = True
            if mode == "twopass":
                p1 = get_encoder_args(encoder, preset, f"{vid_kbps:.0f}k", f"{max_kbps:.0f}k",
                                       f"{buf_kbps:.0f}k", pass_num="1", passlog=passlog) + vf + ["-an", "-f", "null"]
                ok, err = run_ffmpeg_pass(f, p1, os.devnull, duration,
                                           lambda p, s, e: progress_cb(p, s, e, "Pass 1/2 (analysis)"),
                                           self.cancel_evt)
                if not ok:
                    self.msg_queue.put(("log", f"  [ERROR] Pass 1 failed: {err.strip()[:400]}"))
                    continue
                p2 = get_encoder_args(encoder, preset, f"{vid_kbps:.0f}k", f"{max_kbps:.0f}k",
                                       f"{buf_kbps:.0f}k", pass_num="2", passlog=passlog) + vf + ["-c:a", "aac", "-b:a", "128k"]
                ok, err = run_ffmpeg_pass(f, p2, out_file, duration,
                                           lambda p, s, e: progress_cb(p, s, e, "Pass 2/2 (final)"),
                                           self.cancel_evt)
                if not ok:
                    self.msg_queue.put(("log", f"  [ERROR] Pass 2 failed: {err.strip()[:400]}"))
                    continue
            else:
                single = get_encoder_args(encoder, preset, f"{vid_kbps:.0f}k", f"{max_kbps:.0f}k",
                                           f"{buf_kbps:.0f}k") + vf + ["-c:a", "aac", "-b:a", "128k"]
                ok, err = run_ffmpeg_pass(f, single, out_file, duration, progress_cb, self.cancel_evt)
                if not ok:
                    self.msg_queue.put(("log", f"  [ERROR] Encoding failed: {err.strip()[:400]}"))
                    continue

            for p in Path(tempfile.gettempdir()).glob(Path(passlog).name + "*"):
                p.unlink(missing_ok=True)
            self.msg_queue.put(("log", f"  Done -> {out_file}"))

        self.msg_queue.put(("done", f"Finished. Output folder:\n{self.out_dir}"))


if __name__ == "__main__":
    app = ChibiApp()
    app.mainloop()
