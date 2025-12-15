#!/bin/bash
# Snapchat Memories Downloader - One-click runner
# This script handles virtual environment, dependencies, and runs the downloader

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║              Snapchat Memories Downloader                            ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found!${NC}"
    echo "   Install Python 3 from https://python.org or via Homebrew:"
    echo "   brew install python3"
    exit 1
fi

# Check for memories_history.html
if [ ! -f "memories_history.html" ]; then
    echo -e "${RED}❌ memories_history.html not found!${NC}"
    echo ""
    echo "Please download your data from Snapchat:"
    echo "  1. Go to https://accounts.snapchat.com"
    echo "  2. Click 'My Data'"
    echo "  3. Select 'Export your Memories' → 'Request Only Memories'"
    echo "  4. Download and place 'memories_history.html' in this folder"
    exit 1
fi

# Create/activate virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

echo "📦 Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Check for optional tools
echo ""
echo "🔍 Checking optional tools..."

if command -v exiftool &> /dev/null; then
    echo -e "  ${GREEN}✅ exiftool${NC} - Metadata will be written to files"
else
    echo -e "  ${YELLOW}⚠️  exiftool not found${NC} - Install with: brew install exiftool"
fi

if command -v ffmpeg &> /dev/null; then
    echo -e "  ${GREEN}✅ ffmpeg${NC} - Video overlay combining enabled"
else
    echo -e "  ${YELLOW}⚠️  ffmpeg not found${NC} - Install with: brew install ffmpeg"
fi

echo ""

# Run the script with any passed arguments
python3 run_all.py "$@"

