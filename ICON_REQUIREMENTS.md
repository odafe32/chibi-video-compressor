# Icon Requirements for Chibi

## Current Status
The app currently uses placeholder icons named:
- `Chibi.ico` (Windows icon, 256x256 or multi-size)
- `Chibi_256.png` (PNG for display in app header)
- `Chibi_512.png` (High-res PNG)
- `Chibi.icns` (macOS icon, if needed)

## What the Icon Should Represent
Since **Chibi** now compresses both **heavy videos AND images**, the icon should visually communicate:

1. **Compression/Size Reduction** - arrows pointing inward, shrinking effect, or compact symbol
2. **Media Files** - video/image representation (film strip, photo, or generic media)
3. **Modern & Clean** - matches the app's modern indigo/purple color scheme

## Design Suggestions

### Option 1: Compression Symbol
- A downward arrow or compress symbol (⬇️ or ⚡) with media elements
- Color: Indigo/purple gradient (#6366F1 to #818CF8)
- Style: Modern, flat design with subtle shadows

### Option 2: Media + Compression
- A film strip or image frame being compressed/shrunk
- Visual: Two arrows pointing toward center with media icon in middle
- Color scheme: Match app accent colors

### Option 3: Abstract "Chibi" Symbol
- Stylized "C" with compression lines or arrows
- Minimalist geometric design
- Gradient from #6366F1 (indigo) to #10B981 (success green)

## Technical Requirements

### For Windows (.ico)
- Multi-resolution icon containing:
  - 16x16 pixels
  - 32x32 pixels
  - 48x48 pixels
  - 256x256 pixels
- Format: ICO file
- Transparency: Yes (alpha channel)

### For App Display (.png)
- **Chibi_256.png**: 256x256 pixels, PNG with transparency
- **Chibi_512.png**: 512x512 pixels, PNG with transparency (for high-DPI displays)

## Color Palette (from app)
- **Primary Accent**: `#6366F1` (vibrant indigo)
- **Accent Glow**: `#818CF8` (lighter indigo)
- **Success**: `#10B981` (emerald green)
- **Background**: `#0A0E1A` (deep dark)
- **Card**: `#161B26` (elevated surface)

## Where Icons Are Used
1. **Window title bar** (Windows taskbar)
2. **App header** (top-left, 52x52px display)
3. **Start Menu** (after installation)
4. **Desktop shortcut** (if user selects it)
5. **Installer wizard** (Inno Setup)

## Next Steps
1. Create or commission icon designs matching the specifications above
2. Export in required formats (.ico, .png)
3. Replace current placeholder icons in `assets/` folder
4. Rebuild the app with new icons

---

**Note**: The current icons are named "Chibi" but may still have old "VideoCompressor" designs. New icons should reflect the app's dual purpose: **video AND image compression**.
