# Changelog

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
