#!/usr/bin/env python3
"""
Snapchat Memories Downloader - All-in-One Script
Combines downloading, metadata, overlay combining, and deduplication into one easy workflow.

Usage:
    python3 run_all.py              # Interactive menu
    python3 run_all.py --test       # Test mode: download 5 files to verify everything works
    python3 run_all.py --test 10    # Test mode: download 10 files
    python3 run_all.py --full       # Skip menu, run full download immediately
"""

import os
import re
import sys
import json
import shutil
import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ============================================================================
# AUTO-INSTALL DEPENDENCIES (handles macOS Homebrew Python restrictions)
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(SCRIPT_DIR, '.venv')

def ensure_venv():
    """Create venv and re-run script inside it if needed"""
    # Check if we're already in the venv
    if sys.prefix != sys.base_prefix:
        return  # Already in a venv, good to go
    
    # Check if venv exists
    venv_python = os.path.join(VENV_DIR, 'bin', 'python')
    
    if not os.path.exists(venv_python):
        print("📦 Setting up environment (one-time only)...")
        import venv
        venv.create(VENV_DIR, with_pip=True)
        print("   ✅ Created virtual environment")
    
    # Re-run this script using the venv's Python
    print("   🔄 Switching to virtual environment...\n")
    os.execv(venv_python, [venv_python] + sys.argv)

def install_dependencies():
    """Install missing Python packages inside venv"""
    missing = []
    
    try:
        import requests
    except ImportError:
        missing.append('requests')
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        missing.append('beautifulsoup4')
    
    try:
        from PIL import Image
    except ImportError:
        missing.append('Pillow')
    
    if missing:
        print("📦 Installing packages:", ', '.join(missing))
        try:
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', '--quiet'
            ] + missing)
            print("   ✅ Packages installed!\n")
            # Restart to pick up new packages
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install packages: {e}")
            sys.exit(1)

# Auto-setup: ensure we're in venv, then install deps
ensure_venv()
install_dependencies()

# Now import everything (guaranteed to work after install)
import requests
from bs4 import BeautifulSoup
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

REQUESTS_AVAILABLE = True
BS4_AVAILABLE = True

# ============================================================================
# CONFIGURATION
# ============================================================================
HTML_FILE = 'memories_history.html'
DOWNLOAD_FOLDER = 'snapchat_memories'
LOG_FILE = 'downloaded_files.json'
ERROR_LOG_FILE = 'download_errors.json'
METADATA_JSON = 'metadata.json'

MAX_WORKERS = 5  # Number of parallel downloads
DELETE_FOLDERS_AFTER_COMBINE = True  # Delete overlay folders after combining

# Test mode settings (set via command line)
TEST_MODE = False
TEST_LIMIT = 5  # Default number of files in test mode

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def check_tool(tool_name):
    """Check if a command-line tool is available"""
    try:
        subprocess.run([tool_name, '-version' if tool_name == 'ffmpeg' else '-ver'], 
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def print_header(title):
    """Print a section header"""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()

def print_step(step_num, total, description):
    """Print a step indicator"""
    print(f"\n{'─' * 70}")
    print(f"  STEP {step_num}/{total}: {description}")
    print(f"{'─' * 70}\n")

# ============================================================================
# STEP 1: DOWNLOAD MEMORIES
# ============================================================================

def step_download_memories():
    """Download all Snapchat memories from the HTML file"""
    
    if not REQUESTS_AVAILABLE or not BS4_AVAILABLE:
        print("❌ Missing required packages!")
        print("   Run: pip install requests beautifulsoup4")
        return False
    
    if not os.path.exists(HTML_FILE):
        print(f"❌ '{HTML_FILE}' not found!")
        print("   Please place your memories_history.html file in this folder.")
        return False
    
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    
    # Check for exiftool
    exiftool_available = check_tool('exiftool')
    if exiftool_available:
        print("✅ exiftool found - Metadata will be written to files")
    else:
        print("⚠️  exiftool not found - Metadata will not be written")
    
    # Load existing progress
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            downloaded_files = json.load(f)
    else:
        downloaded_files = {}
    
    if os.path.exists(ERROR_LOG_FILE):
        with open(ERROR_LOG_FILE, 'r', encoding='utf-8') as f:
            error_log = json.load(f)
    else:
        error_log = {}
    
    # Parse HTML
    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract download links
    pattern = r"downloadMemories\('(.+?)',\s*this,\s*(true|false)\)"
    matches = re.findall(pattern, html_content)
    
    # Extract dates
    dates = []
    table = soup.select_one('body > div.rightpanel > table > tbody')
    if table:
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if cells:
                date_text = cells[0].get_text(strip=True)
                dates.append(date_text)
    
    print(f"📊 Found {len(matches)} files, {len(dates)} date entries")
    print(f"   Already downloaded: {len(downloaded_files)}")
    print(f"   Failed previously: {len(error_log)}")
    
    # Prepare download tasks
    download_tasks = []
    for i, (url, is_get) in enumerate(matches):
        date_str = dates[i] if i < len(dates) else None
        download_tasks.append((url, is_get == 'true', date_str, i))
    
    # In test mode, limit to TEST_LIMIT files (mix of photos and videos)
    if TEST_MODE:
        # Filter to only files we haven't downloaded yet
        pending_tasks = [t for t in download_tasks 
                        if extract_unique_id(t[0]) not in downloaded_files]
        download_tasks = pending_tasks[:TEST_LIMIT]
        print(f"🧪 TEST MODE: Limiting to {len(download_tasks)} files")
    
    to_download = len([t for t in download_tasks 
                       if extract_unique_id(t[0]) not in downloaded_files])
    
    if to_download == 0:
        print("✅ All files already downloaded!")
        return True
    
    print(f"   To download: {to_download}")
    print()
    
    # Thread locks
    json_lock = threading.Lock()
    error_lock = threading.Lock()
    
    # Counters
    completed = {'count': 0, 'downloaded': 0, 'skipped': 0, 'errors': 0}
    
    def download_file(url, is_get, date_str, index):
        unique_id = extract_unique_id(url)
        
        if unique_id in downloaded_files:
            completed['skipped'] += 1
            return unique_id, 'skipped'
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            if is_get:
                r = requests.get(url, headers=headers, stream=True, timeout=60)
            else:
                parts = url.split('?')
                r = requests.post(parts[0], headers=headers, data=parts[1] if len(parts) > 1 else '',
                                 stream=True, timeout=60)
            
            r.raise_for_status()
            content_type = r.headers.get('Content-Type', '')
            
            # Build filename
            filename = build_filename(unique_id, date_str, content_type, url)
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            
            # Download
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(1024*1024):
                    f.write(chunk)
            
            # Write metadata
            metadata_written = False
            if exiftool_available and date_str:
                metadata_written = write_metadata(filepath, date_str)
            
            # Extract ZIP if needed
            if filepath.endswith('.zip'):
                extract_zip(filepath, date_str, exiftool_available)
            
            with json_lock:
                downloaded_files[unique_id] = {
                    'filename': filename,
                    'url': url,
                    'date': date_str,
                    'content_type': content_type,
                    'timestamp': datetime.now().isoformat()
                }
                with open(LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(downloaded_files, f, indent=2, ensure_ascii=False)
            
            completed['downloaded'] += 1
            return unique_id, 'downloaded'
            
        except Exception as e:
            with error_lock:
                error_log[unique_id] = {
                    'url': url, 'date': date_str, 'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
                with open(ERROR_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(error_log, f, indent=2, ensure_ascii=False)
            
            completed['errors'] += 1
            return unique_id, 'error'
    
    # Run downloads
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(download_file, url, is_get, date, idx) 
                   for url, is_get, date, idx in download_tasks]
        
        total = len(futures)
        for i, future in enumerate(as_completed(futures), 1):
            future.result()
            if i % 20 == 0 or i == total:
                print(f"   Progress: {i}/{total} "
                      f"(Downloaded: {completed['downloaded']}, "
                      f"Skipped: {completed['skipped']}, "
                      f"Errors: {completed['errors']})")
    
    print()
    print(f"✅ Download complete!")
    print(f"   New downloads: {completed['downloaded']}")
    print(f"   Skipped: {completed['skipped']}")
    if completed['errors'] > 0:
        print(f"   ❌ Errors: {completed['errors']}")
    
    return True

def extract_unique_id(url):
    """Extract unique ID from URL"""
    mid_match = re.search(r'mid=([a-zA-Z0-9\-]+)', url)
    if mid_match:
        return mid_match.group(1)
    return hashlib.md5(url.encode()).hexdigest()

def build_filename(unique_id, date_str, content_type, url):
    """Build filename from components"""
    base_name = unique_id
    
    if date_str:
        try:
            for fmt in ['%Y-%m-%d %H:%M:%S %Z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(date_str.replace('UTC', '').strip(), fmt.replace(' %Z', ''))
                    base_name = f"{dt.strftime('%Y%m%d_%H%M%S')}_{unique_id}"
                    break
                except:
                    continue
        except:
            pass
    
    # Determine extension
    ext = None
    url_path = url.split('?')[0]
    if '.' in url_path.split('/')[-1]:
        ext = os.path.splitext(url_path)[1]
        if ext not in ['.mp4', '.jpg', '.jpeg', '.png', '.zip']:
            ext = None
    
    if not ext and content_type:
        if 'video' in content_type:
            ext = '.mp4'
        elif 'jpeg' in content_type or 'jpg' in content_type:
            ext = '.jpg'
        elif 'png' in content_type:
            ext = '.png'
        elif 'zip' in content_type:
            ext = '.zip'
    
    return base_name + (ext or '.mp4')

def write_metadata(filepath, date_str):
    """Write date metadata to file using exiftool"""
    try:
        dt = None
        for fmt in ['%Y-%m-%d %H:%M:%S %Z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
            try:
                dt = datetime.strptime(date_str.replace('UTC', '').strip(), fmt.replace(' %Z', ''))
                break
            except:
                continue
        
        if not dt:
            return False
        
        exif_date = dt.strftime('%Y:%m:%d %H:%M:%S')
        ext = os.path.splitext(filepath)[1].lower()
        
        if ext in ['.jpg', '.jpeg', '.png']:
            subprocess.run([
                'exiftool', '-overwrite_original', '-q',
                f'-DateTimeOriginal={exif_date}',
                f'-CreateDate={exif_date}',
                filepath
            ], capture_output=True)
        elif ext in ['.mp4', '.mov']:
            subprocess.run([
                'exiftool', '-overwrite_original', '-q',
                f'-CreateDate={exif_date}',
                f'-MediaCreateDate={exif_date}',
                filepath
            ], capture_output=True)
        
        os.utime(filepath, (dt.timestamp(), dt.timestamp()))
        return True
    except:
        return False

def extract_zip(zip_path, date_str, exiftool_available):
    """Extract ZIP and apply metadata"""
    try:
        import zipfile
        extract_folder = os.path.splitext(zip_path)[0]
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
        os.remove(zip_path)
        
        # Apply metadata to extracted files
        if exiftool_available and date_str:
            for root, dirs, files in os.walk(extract_folder):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                        write_metadata(os.path.join(root, file), date_str)
    except Exception as e:
        print(f"   ⚠️  ZIP extraction error: {e}")

# ============================================================================
# STEP 2: ADD LOCATION METADATA
# ============================================================================

def step_add_location_metadata():
    """Extract GPS coordinates from HTML and write to files"""
    
    if not os.path.exists(HTML_FILE):
        print(f"❌ '{HTML_FILE}' not found!")
        return False
    
    if not os.path.exists(LOG_FILE):
        print(f"❌ '{LOG_FILE}' not found! Run download step first.")
        return False
    
    exiftool_available = check_tool('exiftool')
    if not exiftool_available:
        print("⚠️  exiftool not found - GPS will only be saved to JSON")
    
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        downloaded_files = json.load(f)
    
    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract locations
    locations = []
    coord_pattern = re.compile(r'Latitude,\s*Longitude:\s*([+-]?\d+\.?\d*),\s*([+-]?\d+\.?\d*)')
    
    table = soup.select_one('body > div.rightpanel > table > tbody')
    if table:
        for row in table.find_all('tr'):
            for cell in row.find_all('td'):
                match = coord_pattern.search(cell.get_text(strip=True))
                if match:
                    locations.append({
                        'latitude': float(match.group(1)),
                        'longitude': float(match.group(2))
                    })
                    break
    
    # Extract URLs for mapping
    pattern = r"downloadMemories\('(.+?)',\s*this,\s*(true|false)\)"
    urls = [url for url, _ in re.findall(pattern, html_content)]
    
    print(f"📍 Found {len(locations)} GPS coordinates")
    print(f"📄 Processing {len(downloaded_files)} downloaded files")
    
    gps_written = 0
    files_with_gps = 0
    
    for i, url in enumerate(urls):
        unique_id = extract_unique_id(url)
        if unique_id not in downloaded_files:
            continue
        
        location = locations[i] if i < len(locations) else None
        if not location:
            continue
        
        files_with_gps += 1
        filename = downloaded_files[unique_id].get('filename')
        filepath = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if exiftool_available:
            if os.path.isfile(filepath):
                if write_gps(filepath, location['latitude'], location['longitude']):
                    gps_written += 1
            elif os.path.isdir(filepath.replace('.zip', '')):
                folder = filepath.replace('.zip', '')
                for root, dirs, files in os.walk(folder):
                    for file in files:
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                            write_gps(os.path.join(root, file), 
                                      location['latitude'], location['longitude'])
                            gps_written += 1
    
    print(f"✅ GPS metadata written to {gps_written} files")
    print(f"   Files with GPS data: {files_with_gps}")
    
    return True

def write_gps(filepath, lat, lon):
    """Write GPS coordinates to file"""
    try:
        lat_ref = 'N' if lat >= 0 else 'S'
        lon_ref = 'E' if lon >= 0 else 'W'
        
        subprocess.run([
            'exiftool', '-overwrite_original', '-q',
            f'-GPSLatitude={abs(lat)}',
            f'-GPSLatitudeRef={lat_ref}',
            f'-GPSLongitude={abs(lon)}',
            f'-GPSLongitudeRef={lon_ref}',
            filepath
        ], capture_output=True)
        return True
    except:
        return False

# ============================================================================
# STEP 3: COMBINE OVERLAYS
# ============================================================================

def step_combine_overlays():
    """Combine main images/videos with their overlay PNGs"""
    
    if not os.path.exists(DOWNLOAD_FOLDER):
        print(f"❌ '{DOWNLOAD_FOLDER}' not found!")
        return False
    
    ffmpeg_available = check_tool('ffmpeg')
    exiftool_available = check_tool('exiftool')
    
    print("Tool Status:")
    if PILLOW_AVAILABLE:
        print("  ✅ Pillow - Image combining enabled")
    else:
        print("  ❌ Pillow - Install with: pip install Pillow")
    
    if ffmpeg_available:
        print("  ✅ FFmpeg - Video combining enabled")
    else:
        print("  ❌ FFmpeg - Install with: brew install ffmpeg")
    print()
    
    if not PILLOW_AVAILABLE and not ffmpeg_available:
        print("⚠️  No combining tools available, skipping...")
        return True
    
    # Find overlay folders
    overlay_folders = []
    for item in os.listdir(DOWNLOAD_FOLDER):
        item_path = os.path.join(DOWNLOAD_FOLDER, item)
        if os.path.isdir(item_path):
            main_file = None
            overlay_file = None
            for file in os.listdir(item_path):
                if '-main.' in file.lower() or '_main.' in file.lower():
                    main_file = os.path.join(item_path, file)
                elif '-overlay.' in file.lower() or '_overlay.' in file.lower():
                    overlay_file = os.path.join(item_path, file)
            
            if main_file and overlay_file:
                overlay_folders.append({
                    'folder': item,
                    'path': item_path,
                    'main': main_file,
                    'overlay': overlay_file
                })
    
    if not overlay_folders:
        print("✅ No overlay folders to process!")
        return True
    
    # Count types
    image_count = sum(1 for f in overlay_folders 
                      if os.path.splitext(f['main'])[1].lower() in ['.jpg', '.jpeg', '.png'])
    video_count = len(overlay_folders) - image_count
    
    print(f"📊 Found {len(overlay_folders)} folders with overlays")
    print(f"   📷 Images: {image_count}")
    print(f"   🎬 Videos: {video_count}")
    print()
    
    success = 0
    errors = 0
    skipped = 0
    
    for folder_info in overlay_folders:
        main_file = folder_info['main']
        overlay_file = folder_info['overlay']
        folder_path = folder_info['path']
        folder_name = folder_info['folder']
        
        ext = os.path.splitext(main_file)[1]
        output_path = os.path.join(DOWNLOAD_FOLDER, folder_name + ext)
        
        is_video = ext.lower() in ['.mp4', '.mov', '.avi']
        
        if is_video:
            if not ffmpeg_available:
                skipped += 1
                continue
            if combine_video(main_file, overlay_file, output_path):
                success += 1
                if DELETE_FOLDERS_AFTER_COMBINE:
                    shutil.rmtree(folder_path)
            else:
                errors += 1
        else:
            if not PILLOW_AVAILABLE:
                skipped += 1
                continue
            if combine_image(main_file, overlay_file, output_path):
                success += 1
                if exiftool_available:
                    copy_metadata(main_file, output_path)
                if DELETE_FOLDERS_AFTER_COMBINE:
                    shutil.rmtree(folder_path)
            else:
                errors += 1
    
    print(f"✅ Combined: {success} files")
    if skipped > 0:
        print(f"⏭️  Skipped: {skipped} files (missing tools)")
    if errors > 0:
        print(f"❌ Errors: {errors} files")
    
    return True

def combine_image(main_path, overlay_path, output_path):
    """Combine image with overlay using Pillow"""
    try:
        main_img = Image.open(main_path).convert('RGBA')
        overlay_img = Image.open(overlay_path).convert('RGBA')
        
        if overlay_img.size != main_img.size:
            overlay_img = overlay_img.resize(main_img.size, Image.Resampling.LANCZOS)
        
        combined = Image.alpha_composite(main_img, overlay_img)
        
        ext = os.path.splitext(output_path)[1].lower()
        if ext in ['.jpg', '.jpeg']:
            combined = combined.convert('RGB')
            combined.save(output_path, 'JPEG', quality=95)
        else:
            combined.save(output_path, 'PNG')
        
        return True
    except Exception as e:
        print(f"   ❌ Image error: {e}")
        return False

def combine_video(video_path, overlay_path, output_path):
    """Combine video with overlay using FFmpeg"""
    try:
        # Get video dimensions
        probe = subprocess.run([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
            video_path
        ], capture_output=True, text=True)
        
        filter_complex = '[1:v]scale=iw:ih[scaled];[0:v][scaled]overlay=0:0:format=auto'
        
        if probe.returncode == 0 and probe.stdout.strip():
            dims = probe.stdout.strip().split(',')
            if len(dims) == 2:
                filter_complex = f'[1:v]scale={dims[0]}:{dims[1]}[scaled];[0:v][scaled]overlay=0:0:format=auto'
        
        result = subprocess.run([
            'ffmpeg', '-y', '-i', video_path, '-i', overlay_path,
            '-filter_complex', filter_complex,
            '-c:a', 'copy', '-c:v', 'libx264',
            '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
            output_path
        ], capture_output=True, text=True)
        
        return result.returncode == 0
    except:
        return False

def copy_metadata(source, dest):
    """Copy metadata from source to destination"""
    try:
        subprocess.run([
            'exiftool', '-overwrite_original', '-q',
            '-TagsFromFile', source, '-all:all', dest
        ], capture_output=True)
    except:
        pass

# ============================================================================
# STEP 4: DELETE DUPLICATES
# ============================================================================

def step_delete_duplicates():
    """Find and delete duplicate files in overlay folders"""
    
    if not os.path.exists(DOWNLOAD_FOLDER):
        print(f"❌ '{DOWNLOAD_FOLDER}' not found!")
        return False
    
    folders_with_dupes = []
    total_dupes = 0
    
    for item in os.listdir(DOWNLOAD_FOLDER):
        item_path = os.path.join(DOWNLOAD_FOLDER, item)
        if not os.path.isdir(item_path):
            continue
        
        # Get file hashes
        file_hashes = {}
        for file in os.listdir(item_path):
            file_path = os.path.join(item_path, file)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                    if file_hash not in file_hashes:
                        file_hashes[file_hash] = []
                    file_hashes[file_hash].append(file_path)
                except:
                    pass
        
        # Find duplicates
        for paths in file_hashes.values():
            if len(paths) > 1:
                folders_with_dupes.append({
                    'folder': item,
                    'keep': paths[0],
                    'delete': paths[1:]
                })
                total_dupes += len(paths) - 1
    
    if not folders_with_dupes:
        print("✅ No duplicates found!")
        return True
    
    print(f"📊 Found {total_dupes} duplicate files in {len(folders_with_dupes)} folders")
    
    deleted = 0
    for dup in folders_with_dupes:
        for path in dup['delete']:
            try:
                os.remove(path)
                deleted += 1
            except:
                pass
    
    print(f"✅ Deleted {deleted} duplicate files")
    
    return True

# ============================================================================
# MAIN MENU
# ============================================================================

def parse_args():
    """Parse command line arguments"""
    global TEST_MODE, TEST_LIMIT
    
    args = sys.argv[1:]
    run_full = False
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--test':
            TEST_MODE = True
            # Check if next arg is a number
            if i + 1 < len(args) and args[i + 1].isdigit():
                TEST_LIMIT = int(args[i + 1])
                i += 1
        elif arg == '--full':
            run_full = True
        elif arg in ['--help', '-h']:
            print("""
Snapchat Memories Downloader

Usage:
    python run_all.py              Interactive menu
    python run_all.py --test       Test mode: download 5 files first
    python run_all.py --test 10    Test mode: download 10 files first  
    python run_all.py --full       Skip menu, run full download

Options:
    --test [N]    Download only N files (default: 5) to test the pipeline
    --full        Run all steps without prompts
    --help, -h    Show this help message
""")
            sys.exit(0)
        i += 1
    
    return run_full

def main():
    global TEST_MODE, TEST_LIMIT
    
    run_full = parse_args()
    
    print()
    if TEST_MODE:
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print(f"║     🧪 TEST MODE - Downloading {TEST_LIMIT} files to verify pipeline            ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
    else:
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print("║          SNAPCHAT MEMORIES DOWNLOADER - All-in-One Script            ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    
    # Check dependencies
    print("📦 Checking tools...")
    
    exiftool_ok = check_tool('exiftool')
    ffmpeg_ok = check_tool('ffmpeg')
    
    print(f"   ✅ requests")
    print(f"   ✅ beautifulsoup4")
    print(f"   {'✅' if PILLOW_AVAILABLE else '⚠️ '} Pillow {'(image overlays)' if PILLOW_AVAILABLE else '- install for image overlays'}")
    print(f"   {'✅' if exiftool_ok else '⚠️ '} exiftool {'(metadata)' if exiftool_ok else '- brew install exiftool'}")
    print(f"   {'✅' if ffmpeg_ok else '⚠️ '} ffmpeg {'(video overlays)' if ffmpeg_ok else '- brew install ffmpeg'}")
    
    print()
    
    # Check for HTML file
    if not os.path.exists(HTML_FILE):
        print(f"❌ '{HTML_FILE}' not found!")
        print()
        print("Please download your data from Snapchat:")
        print("  1. Go to https://accounts.snapchat.com")
        print("  2. Click 'My Data'")
        print("  3. Select 'Export your Memories' → 'Request Only Memories'")
        print("  4. Download and place 'memories_history.html' in this folder")
        return
    
    print(f"✅ Found '{HTML_FILE}'")
    print()
    
    # Define all steps
    all_steps = [
        (1, 4, "Download Memories", step_download_memories),
        (2, 4, "Add GPS Metadata", step_add_location_metadata),
        (3, 4, "Combine Overlays", step_combine_overlays),
        (4, 4, "Delete Duplicates", step_delete_duplicates),
    ]
    
    # If --test or --full, skip the menu
    if TEST_MODE or run_full:
        choice = '1'
    else:
        # Menu
        print("What would you like to do?")
        print()
        print("  [1] Run ALL steps (recommended)")
        print("  [2] Download memories only")
        print("  [3] Add GPS metadata only")
        print("  [4] Combine overlays only")
        print("  [5] Delete duplicates only")
        print("  [0] Exit")
        print()
        
        choice = input("Enter choice (0-5): ").strip()
    
    steps = {
        '1': all_steps,
        '2': [(1, 1, "Download Memories", step_download_memories)],
        '3': [(1, 1, "Add GPS Metadata", step_add_location_metadata)],
        '4': [(1, 1, "Combine Overlays", step_combine_overlays)],
        '5': [(1, 1, "Delete Duplicates", step_delete_duplicates)],
    }
    
    if choice == '0':
        print("\nGoodbye! 👋")
        return
    
    if choice not in steps:
        print("\n❌ Invalid choice!")
        return
    
    print()
    
    for step_num, total, description, func in steps[choice]:
        print_step(step_num, total, description)
        try:
            func()
        except Exception as e:
            print(f"\n❌ Error in step: {e}")
    
    if TEST_MODE:
        print_header("TEST COMPLETE! 🧪")
        print(f"✅ Successfully tested with {TEST_LIMIT} files")
        print(f"   Your test files are in: ./{DOWNLOAD_FOLDER}/")
        print()
        print("If everything looks good, run the full download:")
        print("   python run_all.py --full")
        print()
    else:
        print_header("ALL DONE! 🎉")
        print(f"Your memories are in: ./{DOWNLOAD_FOLDER}/")
        print()

if __name__ == '__main__':
    main()

