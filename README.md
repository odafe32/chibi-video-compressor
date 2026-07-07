# Chibi — GUI + Installer

**Built by Godfrey Joseph Sule**
[GitHub](https://github.com/odafe32/) · [LinkedIn](https://www.linkedin.com/in/godfrey-joseph-a06370248/)

A modern Windows app for compressing **heavy videos and images** to reduce file sizes dramatically.
Built with a GUI (`gui_app.py`) and a double-click installer, using:

- **CustomTkinter** for the GUI (Python)
- **PyInstaller** to bundle it into `Chibi.exe`
- **Inno Setup** to build a normal Windows installer (Start Menu + optional desktop icon)

Everything here needs to be built **on a Windows machine** (Inno Setup and the
.exe both need Windows). Total time: about 15 minutes the first time.

## What's in this folder

| File | Purpose |
|---|---|
| `gui_app.py` | The full GUI app — compresses videos (with hardware encoder detection, bitrate calc, two-pass mode) and images (with quality optimization) |
| `requirements.txt` | Python packages needed |
| `build_exe.bat` | Builds `dist\Chibi.exe` |
| `installer.iss` | Inno Setup script that builds `ChibiSetup.exe` |
| `bin/` | Drop `ffmpeg.exe` and `ffprobe.exe` here before building the installer |

## Step 1 — Install prerequisites (one-time)

1. [Python 3.10+](https://www.python.org/downloads/) — during install, check **"Add python.exe to PATH"**.
2. [Inno Setup](https://jrsoftware.org/isdl.php) (free) — just run the installer, defaults are fine.

## Step 2 — Get ffmpeg/ffprobe and embed them in the exe

Grab a Windows static build:

- https://www.gyan.dev/ffmpeg/builds/ → download the **"release essentials"** zip
- Open the zip, go into its `bin\` folder, copy `ffmpeg.exe` and `ffprobe.exe`
- Paste both into this project's `bin\` folder (replacing the placeholder text file)

## Step 3 — Build the exe

1. Copy this whole folder to your Windows machine.
2. Double-click **`build_exe.bat`**.
   - It checks `bin\` has both exes, creates a virtual environment, installs
     `customtkinter` + `pyinstaller`, and builds the app with ffmpeg/ffprobe
     **embedded inside it** (via `--add-binary`).
   - Result: `dist\Chibi.exe` — a single file, nothing else needed next to it.
3. Test it: just double-click `dist\Chibi.exe` directly. No copying ffmpeg
   alongside it required — it's baked in and gets extracted to a temp folder
   automatically each time the app starts (adds a second or two to startup).

> Note: if you ever want to swap in a different ffmpeg build without
> rebuilding, you *can* still drop `ffmpeg.exe`/`ffprobe.exe` next to
> `Chibi.exe` — the app checks there first and only falls back to
> the embedded copy if nothing's found beside it.

## Step 4 — Build the installer

1. Double-click **`installer.iss`** — it opens in Inno Setup.
2. Click **Build → Compile** (or press Ctrl+F9).
3. Output: `installer_output\ChibiSetup.exe`

That single file is what you hand to other people. Running it installs the
app to Program Files and adds a Start Menu entry (optional desktop icon) —
since ffmpeg/ffprobe are already embedded in the exe, end users don't need to
install or configure anything else.

## Notes / things you may want to tweak

- **App icon**: add an `.ico` file and reference it with `SetupIconFile=` in
  `installer.iss`, and pass `--icon=yourfile.ico` to the `pyinstaller` command
  in `build_exe.bat` for the exe's own icon.
- **Publisher name / version**: edit the `#define` lines at the top of `installer.iss`.
- **Code signing**: unsigned installers trigger a Windows SmartScreen warning
  ("Windows protected your PC"). Users can click "More info → Run anyway".
  To remove that warning you'd need a code-signing certificate (~$100+/yr) —
  not required to make the installer work, just cosmetic/trust related.
- **Antivirus false positives**: PyInstaller-built exes occasionally get
  flagged by some AV engines (false positive, common with PyInstaller). If
  it's an issue for your users, submitting the exe to the AV vendor as a
  false positive usually resolves it within a few days.
- The GUI keeps the same behavior as the script: bitrate is computed from
  target-%-of-original-size, Fast mode uses a hardware encoder if one tests
  successfully, Slow mode does a real two-pass encode.

## If you'd rather skip building yourself

If at any point this feels like more than you want to manage, I can also just
walk through building it live with you interactively, or simplify to a
one-file portable exe (no installer, just a folder you zip and share) —
that skips Inno Setup entirely if you don't need a real installer wizard.
