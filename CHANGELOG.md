# Changelog

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
