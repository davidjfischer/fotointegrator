#!/usr/bin/env python3
"""
Migration script to rename existing state and log files with folder ID prefix.

Usage:
    python migrate_files.py FOLDER_ID

Example:
    python migrate_files.py 1a2b3c4d5e6f7g8h9i0j
"""

import os
import sys
import shutil
from datetime import datetime

STATE_DIR = 'state'
LOGS_DIR = 'logs'

OLD_FILES = {
    'processed': 'processed_files.txt',
    'failed': 'failed_files.txt',
    'skipped': 'skipped_files.txt',
    'planned': 'planned_files.txt'
}


def migrate_state_files(folder_id):
    """Migrate state files to include folder_id prefix."""
    print(f"\n{'='*70}")
    print(f"MIGRATING STATE FILES")
    print(f"{'='*70}\n")

    migrated_count = 0
    skipped_count = 0

    for file_type, old_filename in OLD_FILES.items():
        old_path = os.path.join(STATE_DIR, old_filename)
        new_filename = f"{folder_id}_{old_filename}"
        new_path = os.path.join(STATE_DIR, new_filename)

        if os.path.exists(old_path):
            if os.path.exists(new_path):
                print(f"⚠️  Skipping {old_filename}: Target file already exists")
                print(f"    Old: {old_path}")
                print(f"    New: {new_path} (already exists)")
                skipped_count += 1
            else:
                # Create backup first
                backup_path = f"{old_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(old_path, backup_path)
                print(f"✅ Created backup: {backup_path}")

                # Rename file
                shutil.move(old_path, new_path)
                print(f"✅ Migrated: {old_filename} → {new_filename}")
                migrated_count += 1
        else:
            print(f"ℹ️  Not found: {old_filename} (skipping)")

    print(f"\nState files migration complete:")
    print(f"  - Migrated: {migrated_count}")
    print(f"  - Skipped: {skipped_count}")


def migrate_log_files(folder_id):
    """Migrate log files to include folder_id prefix."""
    print(f"\n{'='*70}")
    print(f"MIGRATING LOG FILES")
    print(f"{'='*70}\n")

    if not os.path.exists(LOGS_DIR):
        print(f"ℹ️  Logs directory not found: {LOGS_DIR}")
        return

    migrated_count = 0
    skipped_count = 0

    # Find all log files that don't already have a folder_id prefix
    for filename in os.listdir(LOGS_DIR):
        if filename.endswith('.log') and not filename.startswith(f"{folder_id}_"):
            old_path = os.path.join(LOGS_DIR, filename)
            new_filename = f"{folder_id}_{filename}"
            new_path = os.path.join(LOGS_DIR, new_filename)

            if os.path.exists(new_path):
                print(f"⚠️  Skipping {filename}: Target file already exists")
                skipped_count += 1
            else:
                # Create backup first
                backup_path = f"{old_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(old_path, backup_path)
                print(f"✅ Created backup: {backup_path}")

                # Rename file
                shutil.move(old_path, new_path)
                print(f"✅ Migrated: {filename} → {new_filename}")
                migrated_count += 1

    print(f"\nLog files migration complete:")
    print(f"  - Migrated: {migrated_count}")
    print(f"  - Skipped: {skipped_count}")


def main():
    if len(sys.argv) != 2:
        print("Error: Folder ID is required")
        print()
        print("Usage:")
        print(f"    python {sys.argv[0]} FOLDER_ID")
        print()
        print("Example:")
        print(f"    python {sys.argv[0]} 1a2b3c4d5e6f7g8h9i0j")
        sys.exit(1)

    folder_id = sys.argv[1]

    print(f"\n{'='*70}")
    print(f"FILE MIGRATION SCRIPT")
    print(f"{'='*70}")
    print(f"\nFolder ID: {folder_id}")
    print(f"\nThis script will:")
    print(f"  1. Rename state files in '{STATE_DIR}/' to include folder ID prefix")
    print(f"  2. Rename log files in '{LOGS_DIR}/' to include folder ID prefix")
    print(f"  3. Create .backup files before renaming")
    print()

    response = input("Continue? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Migration cancelled")
        sys.exit(0)

    # Migrate state files
    migrate_state_files(folder_id)

    # Migrate log files
    migrate_log_files(folder_id)

    print(f"\n{'='*70}")
    print(f"MIGRATION COMPLETE!")
    print(f"{'='*70}\n")
    print("Note: Backup files were created with .backup_TIMESTAMP extension")
    print("You can safely delete them after verifying the migration was successful.")
    print()


if __name__ == '__main__':
    main()
