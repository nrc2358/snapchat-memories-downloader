#!/usr/bin/env python3
"""
Script to combine main images/videos with their overlays in extracted ZIP folders.
This merges the base image with the transparent overlay PNG on top.
For videos, it uses FFmpeg to overlay the PNG.
"""

import os
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("⚠️  Pillow not installed - image combining disabled")
    print("   Run: pip install Pillow")

# Configuration
DOWNLOAD_FOLDER = 'snapchat_memories'
DRY_RUN = False  # Set to True for preview only
DELETE_FOLDER_AFTER = True  # Delete the folder after combining (keeps only the combined image/video)
KEEP_ORIGINALS = False  # Keep original main and overlay files in the folder
USE_EXIFTOOL = True  # Copy metadata from main image to combined image
PROCESS_VIDEOS = True  # Process video files with FFmpeg

def check_exiftool():
    """Checks if exiftool is installed"""
    try:
        subprocess.run(['exiftool', '-ver'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def check_ffmpeg():
    """Checks if ffmpeg is installed"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

exiftool_available = check_exiftool() if USE_EXIFTOOL else False
ffmpeg_available = check_ffmpeg() if PROCESS_VIDEOS else False

def find_overlay_folders(directory):
    """Finds all folders containing main + overlay image pairs"""
    overlay_folders = []
    
    if not os.path.exists(directory):
        print(f"❌ Directory '{directory}' does not exist!")
        return overlay_folders
    
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        
        if os.path.isdir(item_path):
            # Look for main and overlay files
            main_file = None
            overlay_file = None
            
            for file in os.listdir(item_path):
                file_lower = file.lower()
                if '-main.' in file_lower or '_main.' in file_lower:
                    main_file = os.path.join(item_path, file)
                elif '-overlay.' in file_lower or '_overlay.' in file_lower:
                    overlay_file = os.path.join(item_path, file)
            
            if main_file and overlay_file:
                overlay_folders.append({
                    'folder': item,
                    'path': item_path,
                    'main': main_file,
                    'overlay': overlay_file
                })
    
    return overlay_folders

def is_video_file(filepath):
    """Check if file is a video based on extension"""
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v']
    return os.path.splitext(filepath)[1].lower() in video_extensions

def is_image_file(filepath):
    """Check if file is an image based on extension"""
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    return os.path.splitext(filepath)[1].lower() in image_extensions

def combine_images(main_path, overlay_path, output_path):
    """Combines main image with overlay PNG"""
    if not PILLOW_AVAILABLE:
        print("   ❌ Pillow not available for image combining")
        return False
    
    try:
        # Open the main image
        main_img = Image.open(main_path)
        
        # Convert to RGBA if needed
        if main_img.mode != 'RGBA':
            main_img = main_img.convert('RGBA')
        
        # Open the overlay
        overlay_img = Image.open(overlay_path)
        
        # Ensure overlay is RGBA
        if overlay_img.mode != 'RGBA':
            overlay_img = overlay_img.convert('RGBA')
        
        # Resize overlay to match main image if needed
        if overlay_img.size != main_img.size:
            overlay_img = overlay_img.resize(main_img.size, Image.Resampling.LANCZOS)
        
        # Composite the images
        combined = Image.alpha_composite(main_img, overlay_img)
        
        # Convert back to RGB for JPG output (if needed)
        output_ext = os.path.splitext(output_path)[1].lower()
        if output_ext in ['.jpg', '.jpeg']:
            combined = combined.convert('RGB')
        
        # Save the combined image
        if output_ext in ['.jpg', '.jpeg']:
            combined.save(output_path, 'JPEG', quality=95)
        else:
            combined.save(output_path, 'PNG')
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error combining images: {e}")
        return False

def combine_video_with_overlay(video_path, overlay_path, output_path):
    """Combines video with overlay PNG using FFmpeg"""
    if not ffmpeg_available:
        print("   ❌ FFmpeg not available for video combining")
        return False
    
    try:
        # FFmpeg command to overlay PNG on video
        # Scale the overlay to match video dimensions, then overlay
        # [1:v]scale=W:H scales overlay to match video size
        # Then overlay at position 0:0
        filter_complex = (
            '[1:v]scale=iw:ih[scaled];'  # Scale overlay (will be resized to video dims below)
            '[0:v][scaled]overlay=0:0:format=auto'
        )
        
        # First, get video dimensions to scale overlay properly
        probe_result = subprocess.run([
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            video_path
        ], capture_output=True, text=True)
        
        if probe_result.returncode == 0 and probe_result.stdout.strip():
            dims = probe_result.stdout.strip().split(',')
            if len(dims) == 2:
                width, height = dims[0], dims[1]
                # Scale overlay to exact video dimensions
                filter_complex = (
                    f'[1:v]scale={width}:{height}[scaled];'
                    '[0:v][scaled]overlay=0:0:format=auto'
                )
        
        result = subprocess.run([
            'ffmpeg',
            '-y',  # Overwrite output
            '-i', video_path,  # Input video
            '-i', overlay_path,  # Input overlay
            '-filter_complex', filter_complex,
            '-c:a', 'copy',  # Copy audio stream
            '-c:v', 'libx264',  # Encode video with H.264
            '-preset', 'medium',  # Encoding preset
            '-crf', '18',  # Quality (lower = better, 18-23 is good)
            '-pix_fmt', 'yuv420p',  # Compatibility
            output_path
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            return True
        else:
            # Show more helpful error info
            stderr = result.stderr
            if len(stderr) > 300:
                stderr = stderr[:300] + "..."
            print(f"   ❌ FFmpeg error: {stderr}")
            return False
        
    except Exception as e:
        print(f"   ❌ Error combining video: {e}")
        return False

def copy_metadata(source_path, dest_path):
    """Copies EXIF metadata from source to destination using exiftool"""
    if not exiftool_available:
        return False
    
    try:
        result = subprocess.run([
            'exiftool',
            '-overwrite_original',
            '-q',
            '-TagsFromFile', source_path,
            '-all:all',
            dest_path
        ], capture_output=True)
        return result.returncode == 0
    except Exception:
        return False

def process_folders(directory, dry_run=True):
    """Processes all overlay folders and combines images/videos"""
    overlay_folders = find_overlay_folders(directory)
    
    if not overlay_folders:
        print("✅ No overlay folders found to process!")
        return
    
    # Separate images and videos
    image_folders = [f for f in overlay_folders if is_image_file(f['main'])]
    video_folders = [f for f in overlay_folders if is_video_file(f['main'])]
    
    print(f"📊 Found {len(overlay_folders)} folders with overlays")
    print(f"   📷 Images: {len(image_folders)}")
    print(f"   🎬 Videos: {len(video_folders)}")
    print()
    
    if video_folders and not ffmpeg_available:
        print("⚠️  FFmpeg not found - video overlays will be skipped")
        print("   Install FFmpeg: brew install ffmpeg (mac) or apt install ffmpeg (linux)")
        print()
    
    if image_folders and not PILLOW_AVAILABLE:
        print("⚠️  Pillow not found - image overlays will be skipped")
        print("   Install Pillow: pip install Pillow")
        print()
    
    print("=" * 80)
    print()
    
    success_count = 0
    error_count = 0
    skipped_count = 0
    
    for folder_info in overlay_folders:
        folder_name = folder_info['folder']
        folder_path = folder_info['path']
        main_file = folder_info['main']
        overlay_file = folder_info['overlay']
        
        # Determine output filename
        main_ext = os.path.splitext(main_file)[1]
        output_filename = folder_name + main_ext
        output_path = os.path.join(directory, output_filename)
        
        is_video = is_video_file(main_file)
        file_type = "🎬" if is_video else "📷"
        
        print(f"{file_type} {folder_name}/")
        print(f"   Main:    {os.path.basename(main_file)}")
        print(f"   Overlay: {os.path.basename(overlay_file)}")
        print(f"   Output:  {output_filename}")
        
        if dry_run:
            if is_video and not ffmpeg_available:
                print("   ⏭️  [DRY RUN] Would skip (FFmpeg not available)")
                skipped_count += 1
            elif not is_video and not PILLOW_AVAILABLE:
                print("   ⏭️  [DRY RUN] Would skip (Pillow not available)")
                skipped_count += 1
            else:
                print("   ⏭️  [DRY RUN] Would combine and create output")
                success_count += 1
        else:
            # Determine which combine function to use
            combine_success = False
            
            if is_video:
                if ffmpeg_available:
                    combine_success = combine_video_with_overlay(main_file, overlay_file, output_path)
                else:
                    print("   ⏭️  Skipped (FFmpeg not available)")
                    skipped_count += 1
                    print()
                    continue
            else:
                if PILLOW_AVAILABLE:
                    combine_success = combine_images(main_file, overlay_file, output_path)
                else:
                    print("   ⏭️  Skipped (Pillow not available)")
                    skipped_count += 1
                    print()
                    continue
            
            if combine_success:
                print("   ✅ Combined successfully!")
                
                # Copy metadata from main file
                if exiftool_available:
                    if copy_metadata(main_file, output_path):
                        print("   📋 Metadata copied")
                    else:
                        print("   ⚠️  Could not copy metadata")
                
                # Delete the folder if configured
                if DELETE_FOLDER_AFTER and not KEEP_ORIGINALS:
                    try:
                        shutil.rmtree(folder_path)
                        print("   🗑️  Folder deleted")
                    except Exception as e:
                        print(f"   ⚠️  Could not delete folder: {e}")
                
                success_count += 1
            else:
                error_count += 1
        
        print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    if dry_run:
        print("⚠️  DRY RUN MODE - No changes made!")
        print()
        print(f"📊 Folders to process: {len(overlay_folders)}")
        print(f"   📷 Images: {len(image_folders)}")
        print(f"   🎬 Videos: {len(video_folders)}")
        if skipped_count > 0:
            print(f"   ⏭️  Would skip: {skipped_count}")
        print()
        print("💡 To combine the overlays:")
        print("   Set DRY_RUN = False in the script")
    else:
        print(f"✅ Successfully combined: {success_count} files")
        if skipped_count > 0:
            print(f"⏭️  Skipped: {skipped_count} files")
        if error_count > 0:
            print(f"❌ Errors: {error_count} files")

def main():
    print("=" * 80)
    print("Combine Overlay Images & Videos")
    print("=" * 80)
    print()
    
    # Show tool availability
    print("Tool Status:")
    if PILLOW_AVAILABLE:
        print("  ✅ Pillow - Image combining enabled")
    else:
        print("  ❌ Pillow - Image combining disabled (pip install Pillow)")
    
    if ffmpeg_available:
        print("  ✅ FFmpeg - Video combining enabled")
    else:
        print("  ❌ FFmpeg - Video combining disabled (brew install ffmpeg)")
    
    if exiftool_available:
        print("  ✅ exiftool - Metadata will be preserved")
    else:
        print("  ⚠️  exiftool - Metadata will not be copied")
    print()
    
    if not PILLOW_AVAILABLE and not ffmpeg_available:
        print("❌ No combining tools available!")
        print("   Install at least one: pip install Pillow  or  brew install ffmpeg")
        return
    
    if DRY_RUN:
        print("⚠️  DRY RUN MODE - Preview only, no changes")
        print()
    else:
        print("⚠️  WARNING: This will combine files and delete original folders!")
        response = input("Continue? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            print("Cancelled.")
            return
        print()
    
    process_folders(DOWNLOAD_FOLDER, dry_run=DRY_RUN)

if __name__ == '__main__':
    main()

