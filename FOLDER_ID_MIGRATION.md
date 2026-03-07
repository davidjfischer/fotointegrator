# Folder ID Prefixing - Migration Guide

## Overview

The script has been updated so that all generated text files and log files now include the folder ID as a prefix. This allows the script to handle multiple Google Drive folders independently without conflicts.

## Changes

### File Naming Convention

**Before:**
```
state/processed_files.txt
state/failed_files.txt
state/skipped_files.txt
state/planned_files.txt
logs/20260307_120000_UTC_fotointegrator.log
```

**After:**
```
state/{FOLDER_ID}_processed_files.txt
state/{FOLDER_ID}_failed_files.txt
state/{FOLDER_ID}_skipped_files.txt
state/{FOLDER_ID}_planned_files.txt
logs/{FOLDER_ID}_20260307_120000_UTC_fotointegrator.log
```

### New Requirements

**All commands now require a folder ID/URL argument:**

```bash
# Plan mode
python run_fotointegrator.py FOLDER_ID --plan

# Execute mode
python run_fotointegrator.py FOLDER_ID --execute

# Retry mode
python run_fotointegrator.py FOLDER_ID --retry

# Combined mode (default)
python run_fotointegrator.py FOLDER_ID
```

## Migrating Existing Files

If you have existing state and log files without folder ID prefixes, use the migration script:

### Step 1: Find Your Folder ID

Your folder ID can be found in the Google Drive URL:
```
https://drive.google.com/drive/folders/1a2B3c4D5e6F7g8H9i0J
                                        ^^^^^^^^^^^^^^^^^^^
                                        This is your folder ID
```

Or you can check your existing log files to see what folder you were processing.

### Step 2: Run the Migration Script

```bash
python migrate_files.py YOUR_FOLDER_ID
```

**Example:**
```bash
python migrate_files.py 1a2B3c4D5e6F7g8H9i0J
```

### What the Migration Does

1. **Creates backups** of all files before renaming (`.backup_TIMESTAMP` extension)
2. **Renames state files**:
   - `processed_files.txt` → `{FOLDER_ID}_processed_files.txt`
   - `failed_files.txt` → `{FOLDER_ID}_failed_files.txt`
   - `skipped_files.txt` → `{FOLDER_ID}_skipped_files.txt`
   - `planned_files.txt` → `{FOLDER_ID}_planned_files.txt`
3. **Renames log files**:
   - `20260307_120000_UTC_fotointegrator.log` → `{FOLDER_ID}_20260307_120000_UTC_fotointegrator.log`

### Migration Script Output

```
======================================================================
FILE MIGRATION SCRIPT
======================================================================

Folder ID: 1a2B3c4D5e6F7g8H9i0J

This script will:
  1. Rename state files in 'state/' to include folder ID prefix
  2. Rename log files in 'logs/' to include folder ID prefix
  3. Create .backup files before renaming

Continue? (yes/no): yes

======================================================================
MIGRATING STATE FILES
======================================================================

✅ Created backup: state/processed_files.txt.backup_20260307_140530
✅ Migrated: processed_files.txt → 1a2B3c4D5e6F7g8H9i0J_processed_files.txt
✅ Created backup: state/failed_files.txt.backup_20260307_140530
✅ Migrated: failed_files.txt → 1a2B3c4D5e6F7g8H9i0J_failed_files.txt
...

State files migration complete:
  - Migrated: 4
  - Skipped: 0

======================================================================
MIGRATING LOG FILES
======================================================================

✅ Created backup: logs/20260307_120000_UTC_fotointegrator.log.backup_20260307_140530
✅ Migrated: 20260307_120000_UTC_fotointegrator.log → 1a2B3c4D5e6F7g8H9i0J_20260307_120000_UTC_fotointegrator.log
...

Log files migration complete:
  - Migrated: 3
  - Skipped: 0

======================================================================
MIGRATION COMPLETE!
======================================================================

Note: Backup files were created with .backup_TIMESTAMP extension
You can safely delete them after verifying the migration was successful.
```

## Benefits of Folder ID Prefixing

1. **Multi-folder support**: Process multiple Google Drive folders without conflicts
2. **Better organization**: Easily identify which files belong to which folder
3. **Clearer logs**: Log files are now associated with specific folders
4. **Isolation**: Each folder's state is tracked independently

## Backwards Compatibility

⚠️ **Breaking Change**: The folder ID/URL argument is now **required** for all modes.

**Old command (no longer works):**
```bash
python run_fotointegrator.py --retry
```

**New command (required):**
```bash
python run_fotointegrator.py FOLDER_ID --retry
```

## Cleaning Up After Migration

After verifying the migration was successful, you can remove the backup files:

```bash
# Review backups first
ls -la state/*.backup_*
ls -la logs/*.backup_*

# Delete backups if everything looks good
rm state/*.backup_*
rm logs/*.backup_*
```

## Troubleshooting

### "Folder argument is required" error

Make sure to provide the folder ID or URL in all commands:
```bash
python run_fotointegrator.py YOUR_FOLDER_ID --plan
```

### Migration script says "Target file already exists"

This means a file with the new name already exists. You can:
1. Check if you already migrated this folder
2. Manually inspect the conflicting files
3. Remove the existing file if it's not needed

### Can't find my folder ID

Check your previous log files or Google Drive URL. The folder ID is the long alphanumeric string in the URL.
