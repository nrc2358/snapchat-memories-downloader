# Snapchat Memories Downloader

Download all your Snapchat memories with proper metadata (dates, GPS coordinates).

## Quick Start

### 1. Get your data from Snapchat

1. Go to https://accounts.snapchat.com
2. Click **My Data**
3. Select **Export your Memories** → **Request Only Memories**
4. Wait for the email, download the data
5. Place `memories_history.html` in this folder

### 2. Test first (recommended)

```bash
python3 run_all.py --test
```

This downloads just 5 files and runs them through the full pipeline. Check the `snapchat_memories/` folder to verify everything looks good.

### 3. Run the full download

```bash
python3 run_all.py --full
```

**That's it.** Dependencies install automatically. No venv needed.

## Command Line Options

```bash
python3 run_all.py              # Interactive menu
python3 run_all.py --test       # Test mode: download 5 files only
python3 run_all.py --test 10    # Test mode: download 10 files
python3 run_all.py --full       # Skip menu, run all steps
```

## What it does

1. **Downloads** all memories from the HTML file
2. **Adds GPS metadata** to files that have location data
3. **Combines overlays** - merges text/sticker overlays with base images/videos
4. **Removes duplicates** in extracted folders

## Optional Tools (for best results)

```bash
brew install exiftool ffmpeg
```

- **exiftool** - Writes date/GPS metadata to files (so they sort correctly in Photos)
- **ffmpeg** - Combines video overlays (text/stickers on videos)

## Files Created

- `snapchat_memories/` - Your downloaded memories
- `downloaded_files.json` - Progress tracker (resume-friendly)
- `download_errors.json` - Failed downloads (if any)

## Troubleshooting

**Downloads failing?**
- Delete `download_errors.json` and run again
- Some files may be missing on Snapchat's servers

**Metadata not being written?**
- Install exiftool: `brew install exiftool`

**Video overlays not combining?**
- Install ffmpeg: `brew install ffmpeg`
