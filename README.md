# Fotointegrator

A robust Python script for migrating photos and videos from Google Drive to Google Photos with intelligent audio/video pair handling and comprehensive error management.

## Features

### Core Functionality
- 📁 **Recursive folder scanning** - Processes all files in a folder and its subfolders
- 📸 **Smart file detection** - Automatically identifies images, videos, and audio files
- 🎵 **Audio/video pairing** - Intelligently matches and combines audio/video pairs
- 🔄 **Video conversion** - Converts incompatible video formats (MTS, M2TS, AVI, etc.) to MP4
- 📊 **State tracking** - Maintains processed, failed, and skipped file lists
- ♻️ **Retry mechanism** - Configurable retry logic for temporary failures

### Advanced Features
- 🎯 **Intelligent filename matching** - Handles naming variations like `video123.mp4` ↔ `audio123.m4a`
- 🎬 **Audio stream detection** - Automatically detects if videos already have audio
- 🎼 **Audio/video combination** - Uses FFmpeg to merge separate audio and video streams
- 📦 **Subfolder support** - Correctly handles files in nested folder structures
- 🚫 **Smart skipping** - Automatically skips disk images, corrupted files, and unsupported formats
- 📋 **Dual logging** - Logs to both screen and timestamped log files

## Requirements

### Python Dependencies
```bash
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 loguru
```

### System Requirements
- **FFmpeg** - Required for video conversion and audio/video combination
  - macOS: `brew install ffmpeg`
  - Linux: `apt-get install ffmpeg` or `yum install ffmpeg`
  - Windows: Download from [ffmpeg.org](https://ffmpeg.org/)

### Google API Credentials
1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Drive API and Google Photos Library API
3. Create OAuth 2.0 credentials
4. Download `credentials.json` to the script directory

## Usage

### Basic Modes

#### Combined Mode (Plan + Execute)
Scan and process files in one command:
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID>
```

#### Plan Mode
Scan folder and create execution plan without uploading:
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID> --plan
```

#### Execute Mode
Execute previously created plan:
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID> --execute
```

#### Retry Mode
Retry previously failed files:
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID> --retry
```

### Advanced Options

#### Custom Album Name
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID> --album "My Vacation 2024"
```

#### Retry Configuration
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID> --retry_on_error 5 --wait_on_error 60
```

#### Minimum File Size
```bash
python run_fotointegrator.py <FOLDER_URL_OR_ID> --min_bytes 102400  # Skip files < 100 KB
```

## How It Works

### Audio/Video Pair Processing

When the script encounters an audio file (`.m4a`, `.mp3`, etc.), it:
1. Searches for a matching video file with the same base name
2. Downloads both files
3. Checks if the video already has an audio stream
4. If no audio: Combines audio and video using FFmpeg
5. If audio exists: Skips the audio file, uploads video only
6. Marks both files as processed to prevent duplicate processing

### Filename Matching

The script intelligently matches audio/video pairs even when filenames differ:

**Examples:**
- `video1095480922.mp4` ↔ `audio1095480922.m4a` ✅
- `recording_video.mov` ↔ `recording_audio.m4a` ✅
- `my_video_file.mp4` ↔ `my_audio_file.m4a` ✅
- `vid123.mp4` ↔ `aud123.m4a` ✅
- `VIDEO123.mp4` ↔ `audio123.m4a` ✅ (case-insensitive)

### File Skipping

The script automatically skips:
- 💿 **Disk images**: `.iso`, `.img`, `.dmg`, etc.
- 🚫 **Corrupted files**: Google Photos API error code 3
- 📏 **Too small files**: Below minimum size threshold (default: 16 KB)
- ❌ **Non-media files**: Documents, archives, etc.

### State Management

The script maintains state in the `state/` directory:
- `{FOLDER_ID}_processed_files.txt` - Successfully uploaded files
- `{FOLDER_ID}_failed_files.txt` - Files that failed to upload
- `{FOLDER_ID}_skipped_files.txt` - Files intentionally skipped (with reasons)
- `{FOLDER_ID}_planned_files.txt` - Files queued for processing

Logs are stored in `logs/` with timestamps: `{FOLDER_ID}_{TIMESTAMP}_UTC_fotointegrator.log`

## Examples

### Process a Google Drive folder
```bash
python run_fotointegrator.py "https://drive.google.com/drive/folders/1abcdefghijklmnop"
```

### Create execution plan for large folder
```bash
# First, create the plan (quick)
python run_fotointegrator.py "1abcdefghijklmnop" --plan

# Review the plan in state/1abcdefghijklmnop_planned_files.txt

# Then execute when ready
python run_fotointegrator.py "1abcdefghijklmnop" --execute
```

### Retry failed files with custom settings
```bash
python run_fotointegrator.py "1abcdefghijklmnop" --retry --retry_on_error 10 --wait_on_error 120
```

### Process to custom album with lenient file size
```bash
python run_fotointegrator.py "1abcdefghijklmnop" --album "Trip to Italy" --min_bytes 1024
```

## Troubleshooting

### "No matching video file found"
- Ensure audio and video files are in the same folder
- Check that filenames match (the script handles common variations)
- Verify video file extension is supported (`.mp4`, `.mov`, `.avi`, etc.)

### "FFmpeg not installed"
- Install FFmpeg: `brew install ffmpeg` (macOS) or `apt-get install ffmpeg` (Linux)
- Video conversion and audio/video combination require FFmpeg

### "Google Photos API error code 3"
- File is corrupted, empty, or unsupported format
- Script automatically skips these files
- Check `{FOLDER_ID}_skipped_files.txt` for details

### "Quota exceeded for concurrent write request"
- Too many simultaneous upload operations
- Script will retry automatically after waiting
- Consider reducing concurrent operations or waiting between batches

## Testing

Run the comprehensive test suite:
```bash
# Install pytest
pip install pytest

# Run all tests
pytest test_fotointegrator.py -v
```

**Current test coverage:** 45 tests covering:
- URL/ID parsing
- Video format detection
- Filename normalization and matching
- Disk image detection
- File extension constants
- Planned file handling

See [TESTING.md](TESTING.md) for detailed test documentation.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed version history and feature additions.

## License

This project is provided as-is for personal use.

## Contributing

Contributions are welcome! Please ensure all tests pass before submitting pull requests:
```bash
pytest test_fotointegrator.py -v
```
