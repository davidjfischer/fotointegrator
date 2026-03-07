# Changelog

## [2026-03-08] Skip Files Rejected by Google Photos API (Error Code 3)

### Summary
Files that are rejected by Google Photos API with error code 3 (corrupted/empty/unsupported format) are now automatically moved to the skipped files list instead of remaining in the failed files list for endless retries.

### The Problem

When Google Photos API rejects a file with error code 3, it indicates:
- Corrupted or empty file
- Unsupported file format
- Invalid upload token

Previously, these files would:
1. Be marked as failed
2. Be retried on subsequent `--retry` runs
3. Fail again with the same error
4. Never be resolved

This wasted time and resources retrying files that would never succeed.

### The Solution

Modified the exception handler in `process_single_file_with_retry()` to detect error code 3 and immediately return a SKIP status instead of continuing to retry.

**Detection logic:**
```python
if "code=3" in last_error or "Media item creation failed: code=3" in last_error:
    logger.warning("Google Photos API rejected file (error code 3) - marking as skipped")
    return False, "SKIP: Google Photos rejected file (error code 3: corrupted/empty/unsupported format)", additional_files
```

### Changes

**Modified function:**
- `process_single_file_with_retry()` at line ~1006 - Added error code 3 detection and immediate SKIP return

### Behavior

**Before fix:**
```
Attempt 1/3 failed: Media item creation failed: code=3...
Waiting 30 seconds before retry...
Attempt 2/3 failed: Media item creation failed: code=3...
Waiting 30 seconds before retry...
Attempt 3/3 failed: Media item creation failed: code=3...
→ File marked as failed
→ Will be retried on next --retry run (endless loop)
```

**After fix:**
```
Attempt 1/3 failed: Media item creation failed: code=3...
Google Photos API error code 3: File corrupted/empty/unsupported format
Skipping file 'filename.jpg' - will not retry (error code 3 is permanent)
→ File immediately moved to skipped_files.txt
→ Reason: "Google Photos rejected file (error code 3: corrupted/empty/unsupported format)"
→ Will never be retried
```

**Log output example:**
```
[25/100] Processing: corrupted_photo.jpg...
  Downloaded: 2.3MB
  Uploading to Google Photos...
  Attempt 1/3 failed: Media item creation failed: code=3, message='Failed: There was an error while trying to create this media item.'
  Google Photos API error code 3: File corrupted/empty/unsupported format
  Skipping file 'corrupted_photo.jpg' - will not retry (error code 3 is permanent)
[25/100] Skipped: corrupted_photo.jpg - Google Photos rejected file (error code 3: corrupted/empty/unsupported format)
```

### Testing

All 38 unit tests pass.

### Benefits
✓ No more endless retry loops for permanently broken files
✓ Clear indication in skipped files why the file was rejected
✓ Saves time and API quota
✓ Cleaner failed files list (only contains temporary failures)

---

## [2026-03-08] Skip Disk Image Files (ISO, IMG, DMG, etc.)

### Summary
Added automatic detection and skipping of disk image files to prevent them from being uploaded to Google Photos.

### The Problem

Disk image files like `.iso`, `.img`, `.dmg` have MIME types that often contain the word "image" (e.g., `application/x-iso9660-image`), causing them to be incorrectly classified as photo images and uploaded to Google Photos.

### The Solution

Added explicit disk image extension checking that happens **before** MIME type checking, ensuring these files are always skipped:

**Skipped extensions:**
- `.iso` - ISO 9660 disk images
- `.img` - Raw disk images
- `.dmg` - macOS disk images
- `.toast` - Toast disk images
- `.vcd` - Virtual CD images
- `.bin` / `.cue` - Binary disk images with cue sheets
- `.nrg` - Nero disk images
- `.mdf` / `.mds` - Media Descriptor File images

### Changes

**Modified functions:**
- `plan_folder()` at line ~1079 - Added disk_image_extensions check before MIME type classification
- `process_folder()` at line ~1272 - Added disk_image_extensions exclusion from is_media_file check
- `retry_failed_files()` at line ~1199 - Added disk_image_extensions check to skip disk images during retry and move them from failed to skipped files

### Testing

All 38 unit tests pass.

**Real-world test with retry mode:**
```
[1/1] Skipping disk image: boot.iso
  - Removed from failed_files.txt
  - Added to skipped_files.txt with reason: "Disk image file"
  - MIME type: application/x-cd-image
```

**Example behavior:**
```
Found audio: audio1095480922.m4a
Found video: video1095480922.mp4
Skipping disk image: backup.iso (type: application/x-iso9660-image)
Skipping disk image: installer.dmg (type: application/x-apple-diskimage)
```

### Benefits
✓ Disk images are never uploaded to Google Photos
✓ Prevents confusion and clutter in photo albums
✓ Saves bandwidth and API quota
✓ Works for all common disk image formats

---

## [2026-03-08] Fix Subfolder File Matching for Audio/Video Pairs

### Summary
Fixed critical bug where audio files could not find their matching video files when both files were located in subfolders of the root folder.

### The Problem

When processing a folder structure like:
```
Root Folder (1dy8rpJAwbGLhZOOz8rNOuRPkPKk__fqI)
└── Subfolder "2023-05-06 20.21.02 Küss die Muse 2" (1-2okboaM3ewW7A08ca1e4kxy6n7amyB2)
    ├── audio1095480922.m4a
    ├── video1095480922.mp4
    ├── chat.txt
    └── recording.conf
```

The script would:
1. **Planning phase**: Correctly recurse into subfolders and find both files ✅
2. **Execution phase**: When processing `audio1095480922.m4a`, search for matching video in the ROOT folder ❌
3. **Result**: Find 0 video files (only the subfolder itself), skip the audio file ❌

**Root Cause:** `find_matching_video_file()` was called with the root folder ID, not the actual parent folder ID where the file was located.

### The Solution

Modified `process_single_file_with_retry()` to fetch each file's actual parent folder ID before searching for matches:

```python
# Get the actual parent folder ID of this file (not the root folder ID)
file_metadata = service.files().get(fileId=file_id, fields='parents').execute()
actual_folder_id = file_metadata.get('parents', [folder_id])[0]

# Find matching video file in the same folder
video_match = find_matching_video_file(service, actual_folder_id, file_name)
```

Now the script searches for matching files in the **same folder** as the audio file, not the root folder.

### Changes

**Modified function:** `process_single_file_with_retry()` at line ~838
- Added API call to fetch file's parent folder ID
- Pass actual parent folder ID to `find_matching_video_file()`

### Testing

**Before fix:**
```
[1/2] Processing: audio1095480922.m4a...
  Searching for matching video file...
  Querying folder_id: 1dy8rpJAwbGLhZOOz8rNOuRPkPKk__fqI (root)
  Total files in folder: 1
  DEBUG File: 2023-05-06 20.21.02 Küss die Muse 2 | MIME: application/vnd.google-apps.folder
  Found 0 video file(s) in folder
  ✗ No matching video file found
[1/2] Skipped: audio1095480922.m4a

[2/2] Processing: video1095480922.mp4...
  (processes video separately)
```

**After fix:**
```
[1/2] Processing: audio1095480922.m4a...
  Searching for matching video file...
  File's parent folder ID: 1-2okboaM3ewW7A08ca1e4kxy6n7amyB2 (subfolder)
  Querying folder_id: 1-2okboaM3ewW7A08ca1e4kxy6n7amyB2
  Total files in folder: 4
    recording.conf
    audio1095480922.m4a
    video1095480922.mp4
    chat.txt
  Found 1 video file(s) in folder
  ✓ Found matching video file: video1095480922.mp4
  (downloads both, uploads video)
[1/2] Done: audio1095480922.m4a

[2/2] Skipping (already processed): video1095480922.mp4
```

All 38 unit tests still pass.

### Benefits
✓ Audio/video matching works correctly in subfolders
✓ No more false "no matching video found" errors
✓ Handles arbitrarily nested folder structures
✓ Works with Google Drive's recursive folder scanning

---

## [2026-03-07] Fix Duplicate Video Processing When Paired with Audio

### Summary
Fixed a bug where video files were processed twice when they had matching audio files: once when processing the audio file, and again when processing the video file from the planned files list.

### The Problem
When an audio file was processed:
1. The script found the matching video file
2. Downloaded both audio and video files
3. Determined that the video already had audio
4. Skipped the audio file and uploaded the video
5. Marked only the audio file as processed

Then when the loop continued:
6. The video file (still in the planned files list) was processed again
7. Downloaded the same video file a second time
8. Uploaded it to Google Photos a second time

This wasted bandwidth, time, and potentially created duplicate photos in the album.

### The Solution
When processing an audio file that has a matching video, the script now tracks the video file ID in the `additional_files` list in three scenarios:

1. **Video already has audio** (most common):
   - Skips the audio file
   - Uploads the video
   - Marks both audio and video as processed

2. **Video needs audio combination**:
   - Combines audio and video streams
   - Uploads the combined file
   - Marks both files as processed

3. **Audio file is too small, video is normal**:
   - Skips the audio file
   - Uploads the video without audio
   - Marks both files as processed

In all cases, when the loop reaches the video file entry in the plan, it's already in the `processed_files` or `failed_files` set and gets skipped.

### Changes

**Modified function:** `process_single_file_with_retry()` at lines ~891 and ~877

Added `additional_files = [(video_file_id, video_file_url)]` after:
- Line 891: When video already has audio
- Line 877: When audio is too small to process

### Testing

Test execution on folder with `audio1095480922.m4a` and `video1095480922.mp4`:

**Before fix:**
```
[1/2] Processing: audio1095480922.m4a...
  ✓ Found matching video: video1095480922.mp4
  (downloads 526.9MB video)
  (uploads 526.9MB video)
[1/2] Done: audio1095480922.m4a

[2/2] Processing: video1095480922.mp4...
  (downloads 526.9MB video AGAIN)
  (uploads 526.9MB video AGAIN)
[2/2] Done: video1095480922.mp4
```

**After fix:**
```
[1/2] Processing: audio1095480922.m4a...
  ✓ Found matching video: video1095480922.mp4
  (downloads 526.9MB video)
  (uploads 526.9MB video)
[1/2] Done: audio1095480922.m4a

[2/2] Skipping (already processed): video1095480922.mp4
```

All 38 unit tests still pass.

### Benefits
✓ Eliminates duplicate downloads (saves bandwidth)
✓ Eliminates duplicate uploads (saves time and API quota)
✓ Prevents duplicate photos in Google Photos albums
✓ Proper state tracking for all processed file pairs

---

## [2026-03-07] Intelligent Audio/Video Pair Matching with Naming Variations

### Summary
Enhanced audio/video file matching to handle common naming patterns where filenames differ by keywords like "video" and "audio".

### New Matching Capabilities

The script now intelligently matches audio and video files even when they have different naming patterns:

**Examples of matched pairs:**
- `video1095480922.mp4` ↔ `audio1095480922.m4a`
- `recording_video.mov` ↔ `recording_audio.m4a`
- `video_concert.mp4` ↔ `audio_concert.m4a`
- `my_video_file.mp4` ↔ `my_audio_file.m4a`
- `vid123.mp4` ↔ `aud123.m4a` (short forms)
- `VIDEO123.mp4` ↔ `audio123.m4a` (case-insensitive)

### How It Works

**Filename Normalization:**
1. Converts filenames to lowercase
2. Removes common video/audio keywords with various separators:
   - Prefixes: `video_`, `audio_`, `vid_`, `aud_`
   - Suffixes: `_video`, `_audio`, `_vid`, `_aud`
   - With dashes: `video-`, `-video`, `audio-`, `-audio`
   - With spaces: `video `, ` video`, `audio `, ` audio`
3. Removes keywords at start/end without separators
4. Compares normalized versions for matching

**Matching Logic:**
1. First tries exact base name match (fastest)
2. Falls back to normalized comparison
3. Only considers it a match if both files have content after normalization

### Implementation Details

**New Functions:**
- `normalize_filename_for_matching(filename)` - Removes video/audio keywords for comparison
- `filenames_match(name1, name2)` - Checks if two filenames match using exact or normalized comparison

**Enhanced Functions:**
- `find_matching_audio_file()` - Now searches all audio files and uses intelligent matching
- `find_matching_video_file()` - Now searches all video files and uses intelligent matching

**Logging Enhancements:**
- Shows original base name
- Shows normalized version for debugging
- Lists all candidates checked
- Clear indication of match/no-match

### Testing

Added 16 comprehensive unit tests:

**TestFilenameNormalization (8 tests):**
- Video/audio prefix/suffix handling
- Short forms (vid/aud)
- Case insensitivity
- Complex names with multiple keywords
- Names without keywords (unchanged)

**TestFilenameMatching (8 tests):**
- Exact matches
- Prefix/suffix patterns
- Mixed patterns (prefix on one, suffix on other)
- Short form matching
- Different names (should not match)
- Case-insensitive matching
- Real-world example validation

All 38 unit tests pass successfully (22 original + 16 new).

### Benefits

✓ Handles diverse naming conventions automatically
✓ Case-insensitive for improved reliability
✓ Supports both full keywords and short forms
✓ Maintains exact match priority for performance
✓ Extensive test coverage ensures correctness
✓ Detailed logging for troubleshooting

---

## [2024-03-07] Automatic Video+Audio Stream Combination

### Summary
Added intelligent video+audio stream detection and automatic combination for videos without embedded audio.

### New Functionality

**Automatic Audio Detection:**
- For video files (MP4, MOV, AVI, MKV, M4V, WebM), the script now checks if an audio stream is present
- Uses ffprobe to detect audio streams in video files

**Automatic Audio Matching:**
- If a video has no audio stream, searches for a matching audio file with the same base name
- Supports audio formats: MP3, M4A, AAC, WAV, WMA, OGG, FLAC
- Example: `video.mp4` (no audio) → searches for `video.mp3`, `video.m4a`, etc.

**Automatic Combination:**
- Downloads both video and audio files
- Uses ffmpeg to combine them into a single video file
- Video stream is copied without re-encoding (fast)
- Audio is re-encoded to AAC format
- Uploads the combined video+audio file

### Workflow

1. **Download video file**
2. **Check for audio stream** (using ffprobe)
3. **If no audio found:**
   - Search Google Drive folder for matching audio file (same base filename)
   - Download audio file if found
   - Combine video + audio using ffmpeg
   - Use combined file for upload
4. **If audio exists or no match found:**
   - Continue with normal processing (upload video as-is)

### Requirements

- **ffprobe** - Required for audio stream detection (part of ffmpeg package)
- **ffmpeg** - Required for combining video+audio streams

Install on macOS: `brew install ffmpeg`
Install on Linux: `apt-get install ffmpeg` or `yum install ffmpeg`

### Use Cases

**Solves the problem of:**
- Videos exported without audio tracks
- Separate video and audio file exports from recording software
- Videos with corrupted or missing audio streams

**Example scenarios:**
- Screen recording software that exports video and audio separately
- Video editing software that outputs separate tracks
- Corrupted video files where audio was extracted to a separate file

### Log Output Example

```
[25/100] Processing: recording.mp4...
  Downloaded: 45.2MB
  Checking for audio stream in video file...
  Video file has no audio stream
  Searching for matching audio file for: recording
  Found matching audio file: recording.mp3
  Downloading matching audio file...
  Combining video and audio streams...
    Video: recording.mp4
    Audio: recording.mp3
  Successfully combined video+audio: 47.8MB
  Using combined video+audio file
  Uploading to Google Photos...
[25/100] Done: recording.mp4
```

### Implementation Details

**New Functions:**
- `check_ffprobe_installed()` - Checks if ffprobe is available
- `video_has_audio_stream(file_path)` - Detects audio stream using ffprobe
- `find_matching_audio_file(service, folder_id, video_filename)` - Searches for matching audio
- `combine_video_and_audio(video_path, audio_path, output_path)` - Merges streams using ffmpeg

**Updated Functions:**
- `process_single_file_with_retry()` - Now accepts folder_id parameter and includes audio detection/combination logic

### Error Handling

- If ffprobe is not installed, assumes audio exists (no detection)
- If audio file search fails, uploads video without audio
- If combination fails, uploads original video without audio
- All temporary files (audio, combined) are cleaned up after processing

### Testing

All 22 unit tests pass successfully.

---

## [2024-03-07] Configurable Minimum File Size

### Summary
Added `--min_bytes` parameter to configure the minimum file size threshold for skipping files.

### New Parameter

**`--min_bytes`** (integer, default: 16384 = 16 KB)
- Specifies the minimum file size in bytes
- Files smaller than this threshold are skipped (not failed)
- Replaces hardcoded 0-byte check with configurable threshold

### Usage Examples

```bash
# Use default (16 KB minimum)
python run_fotointegrator.py FOLDER_ID

# Skip files smaller than 1 KB (more lenient)
python run_fotointegrator.py FOLDER_ID --min_bytes 1024

# Skip files smaller than 100 KB (stricter)
python run_fotointegrator.py FOLDER_ID --min_bytes 102400

# Only skip zero-byte files (most lenient)
python run_fotointegrator.py FOLDER_ID --min_bytes 1

# Retry mode with custom minimum size
python run_fotointegrator.py FOLDER_ID --retry --min_bytes 5000
```

### Implementation Details

**Updated Functions:**
- `process_single_file_with_retry()` - accepts `min_bytes` parameter
- All mode handlers pass `args.min_bytes` through the call chain
- Log messages show configured threshold

**Behavior:**
- Files below threshold are detected after download
- Logged as: `"File is too small (X bytes, minimum: Y bytes) - skipping"`
- Saved to `skipped_files.txt` with reason
- Skip reason format: `"File too small (X bytes, minimum: Y bytes)"`

**Why 16 KB default?**
- Reasonable threshold for valid image/video files (even thumbnails are typically larger)
- Catches corrupted files that download with minimal data
- Prevents processing of incomplete or damaged downloads
- Can be adjusted per use case (1 for only zero-byte, 1024 for 1 KB, etc.)

### Testing

All 22 unit tests pass successfully.

---

## [2024-03-07] Zero-Byte Files Now Skipped Instead of Failed

### Summary
Zero-byte (empty) files are now treated as skipped files rather than failed files.

### Changes

**New Behavior:**
- Files that download as 0 bytes are automatically skipped
- These files are saved to `{FOLDER_ID}_skipped_files.txt` instead of `{FOLDER_ID}_failed_files.txt`
- Skip reason is included in the log: `File is empty (0 bytes)`

**Updated File Format:**
The skipped files log now includes a reason field:
```
file_id|file_url|mime_type|reason
```

**Example entries:**
```
1a2b3c4d5e|https://drive.google.com/file/d/1a2b3c4d5e|image/jpeg|File is empty (0 bytes)
9x8y7z6w5v|https://drive.google.com/file/d/9x8y7z6w5v|video/mp4|Not image/video
```

**Benefits:**
- ✅ Failed files list is cleaner (only contains actual processing failures)
- ✅ Empty/corrupted files are properly categorized as skipped
- ✅ Easy to identify zero-byte files in the skipped files log
- ✅ Retry mode won't keep retrying files that are permanently empty

**Implementation:**
- `process_single_file_with_retry()` returns `(False, "SKIP: reason")` for zero-byte files
- All mode handlers check for "SKIP:" prefix and save to skipped files accordingly
- `save_skipped_file()` now accepts optional `reason` parameter (default: "Not image/video")

### Testing

All 22 unit tests pass successfully.

---

## [2024-03-07] Improved Error Handling for Corrupted Files

### Summary
Enhanced error detection and reporting for empty or corrupted files.

### Changes

**Empty File Detection:**
- Added validation after download to detect 0-byte files
- Files with 0 bytes are immediately rejected with clear error message
- Prevents confusing Google Photos API errors for empty files

**Small File Warning:**
- Added warning for suspiciously small files (< 100 bytes)
- Helps identify potentially corrupted files early

**Improved Error Messages:**
- Google Photos API errors now include error code and clearer messages
- Code 3 errors (INVALID_ARGUMENT) now include helpful hints:
  - "Possible causes: corrupted/empty file, unsupported format, or invalid upload token"

### Problem This Solves

Previously, when a file downloaded as 0 bytes (corrupted in Google Drive), the upload to Google Photos would fail with a cryptic error:
```
Media item creation failed: {'code': 3, 'message': 'Failed: There was an error while trying to create this media item.'}
```

Now, the script detects this early and provides a clear error:
```
Downloaded file is empty (0 bytes) - file may be corrupted in Google Drive
```

### Testing

All 22 unit tests pass successfully.

---

## [2024-03-07] Configurable Retry Parameters

### Summary
Added command-line parameters to configure retry behavior when processing files.

### New Parameters

**`--retry_on_error`** (integer, default: 3)
- Specifies the number of retry attempts when a file fails to process
- Example: `--retry_on_error 5` will retry up to 5 times before marking a file as failed

**`--wait_on_error`** (integer, default: 30)
- Specifies the number of seconds to wait between retry attempts
- Example: `--wait_on_error 60` will wait 60 seconds between retries

### Usage Examples

```bash
# Use default retry settings (3 attempts, 30 seconds wait)
python run_fotointegrator.py FOLDER_ID

# Custom retry settings: 5 attempts with 60 seconds wait
python run_fotointegrator.py FOLDER_ID --retry_on_error 5 --wait_on_error 60

# Retry failed files with custom settings
python run_fotointegrator.py FOLDER_ID --retry --retry_on_error 10 --wait_on_error 120

# Execute mode with custom retry settings
python run_fotointegrator.py FOLDER_ID --execute --retry_on_error 2 --wait_on_error 15
```

### Implementation Details

- Updated `process_single_file_with_retry()` to accept configurable retry parameters
- Updated all mode handlers to pass retry parameters through the call chain
- Parameters apply to all processing modes: combined, execute, and retry
- Log messages now show retry configuration at startup

### Testing

All 22 unit tests pass successfully.

---

## [2024-03-07] Folder ID Prefixing Update

### Summary
All generated text files and log files now include the folder ID as a prefix. This enables the script to handle multiple Google Drive folders independently.

### Breaking Changes

⚠️ **All commands now require a folder ID/URL argument:**

**Before:**
```bash
python run_fotointegrator.py --plan
python run_fotointegrator.py --execute
python run_fotointegrator.py --retry
```

**After:**
```bash
python run_fotointegrator.py FOLDER_ID --plan
python run_fotointegrator.py FOLDER_ID --execute
python run_fotointegrator.py FOLDER_ID --retry
python run_fotointegrator.py FOLDER_ID  # Combined mode
```

### Changed Files

#### run_fotointegrator.py
- Added helper functions for folder-specific file paths:
  - `get_processed_files_log(folder_id)`
  - `get_failed_files_log(folder_id)`
  - `get_skipped_files_log(folder_id)`
  - `get_planned_files_log(folder_id)`
  - `get_log_filename(folder_id)`
- Updated `setup_file_logging(folder_id)` to create folder-specific log files
- Updated all file tracking functions to accept `folder_id` parameter:
  - `load_processed_files(folder_id)`
  - `load_failed_files(folder_id)`
  - `load_skipped_files(folder_id)`
  - `save_processed_file(folder_id, file_id, file_url)`
  - `load_failed_files_detailed(folder_id)`
  - `save_failed_file(folder_id, file_id, file_url, file_name, error_msg)`
  - `remove_from_failed_files(folder_id, file_id)`
  - `save_skipped_file(folder_id, file_id, file_url, mime_type)`
  - `save_planned_file(folder_id, file_id, file_url, file_name, mime_type)`
  - `load_planned_files(folder_id)`
- Updated mode handler functions:
  - `plan_folder()` now accepts `root_folder_id` and `current_folder_id`
  - `process_from_plan()` accepts `folder_id` parameter
  - `retry_failed_files()` accepts `folder_id` parameter
  - `process_folder()` accepts `root_folder_id` and `current_folder_id`
- Updated mode execution functions:
  - `run_retry_mode()` now extracts folder_id and sets up logging
  - `run_execute_mode()` now extracts folder_id and sets up logging
  - `run_plan_mode()` now extracts folder_id and sets up logging
  - `run_combined_mode()` now extracts folder_id and sets up logging

#### test_fotointegrator.py
- Updated tests to use folder_id parameter with mocked `get_planned_files_log()`
- All 22 tests still passing

#### New Files
- `migrate_files.py` - Migration script to rename existing files with folder ID prefix
- `FOLDER_ID_MIGRATION.md` - Comprehensive migration guide
- `CHANGELOG.md` - This file

### Migration Required

If you have existing state and log files, run the migration script:

```bash
python migrate_files.py YOUR_FOLDER_ID
```

See `FOLDER_ID_MIGRATION.md` for detailed instructions.

### File Naming Examples

**State files:**
```
state/1a2B3c4D5e6F7g8H9i0J_processed_files.txt
state/1a2B3c4D5e6F7g8H9i0J_failed_files.txt
state/1a2B3c4D5e6F7g8H9i0J_skipped_files.txt
state/1a2B3c4D5e6F7g8H9i0J_planned_files.txt
```

**Log files:**
```
logs/1a2B3c4D5e6F7g8H9i0J_20260307_140530_UTC_fotointegrator.log
```

### Benefits

1. **Multi-folder support**: Process multiple Google Drive folders without conflicts
2. **Better organization**: Files are clearly associated with their source folder
3. **Independent state tracking**: Each folder maintains its own processing state
4. **Clearer debugging**: Log files are scoped to specific folders

### Testing

All unit tests pass:
```bash
$ pytest test_fotointegrator.py -v
...
============================== 22 passed in 0.40s ==============================
```

---

## Previous Changes

See git history for details on previous updates:
- OAuth scope updates (post-March 2025 API changes)
- Video conversion with ffmpeg
- Plan/execute/retry modes
- Code refactoring
- Unit test implementation
