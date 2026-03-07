import os
import io
import sys
import requests
import pickle
import argparse
import re
import time
import subprocess
import shutil
from datetime import datetime, timezone
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from loguru import logger

# Create logs directory if it doesn't exist
LOGS_DIR = 'logs'
os.makedirs(LOGS_DIR, exist_ok=True)

# Generate timestamped log filename
start_time = datetime.now(timezone.utc)
log_filename = os.path.join(LOGS_DIR, f"{start_time.strftime('%Y%m%d_%H%M%S_UTC')}_fotointegrator.log")

# Configure loguru to use UTC time
logger.remove()  # Remove default handler
logger.configure(patcher=lambda record: record.update(time=record["time"].astimezone(timezone.utc)))

# Add stdout handler (colorized, with backtrace and diagnose for errors)
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS UTC}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
    backtrace=True,
    diagnose=True
)

# Add file handler (no color codes in file, with backtrace and diagnose for errors)
logger.add(
    log_filename,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS UTC} | {level: <8} | {message}",
    level="INFO",
    colorize=False,
    backtrace=True,
    diagnose=True
)

# If modifying these scopes, delete the file token.pickle.
# Updated to use new scopes (legacy scopes deprecated after March 31, 2025)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata'
]

# Create state directory for file tracking logs
STATE_DIR = 'state'
os.makedirs(STATE_DIR, exist_ok=True)

PROCESSED_FILES_LOG = os.path.join(STATE_DIR, 'processed_files.txt')
FAILED_FILES_LOG = os.path.join(STATE_DIR, 'failed_files.txt')
SKIPPED_FILES_LOG = os.path.join(STATE_DIR, 'skipped_files.txt')
PLANNED_FILES_LOG = os.path.join(STATE_DIR, 'planned_files.txt')
MAX_RETRIES = 10
RETRY_WAIT_SECONDS = 30

def load_processed_files():
    """Load the set of already processed file IDs from the log file."""
    if not os.path.exists(PROCESSED_FILES_LOG):
        return set()

    processed = set()
    with open(PROCESSED_FILES_LOG, 'r') as f:
        for line in f:
            # Extract file ID from each line (format: file_id|url)
            parts = line.strip().split('|')
            if parts:
                processed.add(parts[0])
    return processed

def save_processed_file(file_id, file_url):
    """Save a processed file ID and its Drive URL to the log file."""
    with open(PROCESSED_FILES_LOG, 'a') as f:
        f.write(f"{file_id}|{file_url}\n")

def load_failed_files():
    """Load the set of failed file IDs from the log file."""
    if not os.path.exists(FAILED_FILES_LOG):
        return set()

    failed = set()
    with open(FAILED_FILES_LOG, 'r') as f:
        for line in f:
            # Extract file ID from each line (format: file_id|url|error)
            parts = line.strip().split('|')
            if parts:
                failed.add(parts[0])
    return failed

def save_failed_file(file_id, file_url, error_msg):
    """Save a failed file ID, its Drive URL, and error message to the log file."""
    with open(FAILED_FILES_LOG, 'a') as f:
        # Replace newlines and pipes in error message to keep format consistent
        error_msg_cleaned = error_msg.replace('\n', ' ').replace('|', ':')
        f.write(f"{file_id}|{file_url}|{error_msg_cleaned}\n")

def load_skipped_files():
    """Load the set of skipped file IDs from the log file."""
    if not os.path.exists(SKIPPED_FILES_LOG):
        return set()

    skipped = set()
    with open(SKIPPED_FILES_LOG, 'r') as f:
        for line in f:
            # Extract file ID from each line (format: file_id|url|mimetype)
            parts = line.strip().split('|')
            if parts:
                skipped.add(parts[0])
    return skipped

def save_skipped_file(file_id, file_url, mime_type):
    """Save a skipped file ID, its Drive URL, and MIME type to the log file."""
    with open(SKIPPED_FILES_LOG, 'a') as f:
        f.write(f"{file_id}|{file_url}|{mime_type}\n")

def save_planned_file(file_id, file_url, file_name, mime_type):
    """Save a planned file ID, URL, name, and MIME type to the plan file."""
    with open(PLANNED_FILES_LOG, 'a') as f:
        f.write(f"{file_id}|{file_url}|{file_name}|{mime_type}\n")

def load_planned_files():
    """
    Load planned files from the plan file.
    Returns a list of tuples: (file_id, file_url, file_name, mime_type)
    """
    if not os.path.exists(PLANNED_FILES_LOG):
        return None

    planned = []
    with open(PLANNED_FILES_LOG, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 4:
                file_id, file_url, file_name, mime_type = parts[0], parts[1], parts[2], parts[3]
                planned.append((file_id, file_url, file_name, mime_type))
    return planned

def get_services():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    drive_service = build('drive', 'v3', credentials=creds)
    return drive_service, creds

def get_valid_token(creds):
    """
    Get a valid access token from credentials, refreshing if necessary.
    This should be called before each API request to ensure the token is fresh.
    """
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            logger.info("  Token expired, refreshing...")
            creds.refresh(Request())
            # Update the pickled credentials
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        else:
            raise Exception("Credentials are invalid and cannot be refreshed")
    return creds.token

def extract_folder_id(input_str):
    """Extract folder ID from Google Drive URL or return the input if it's already an ID."""
    # Pattern to match folder ID in Google Drive URLs
    url_pattern = r'/folders/([a-zA-Z0-9_-]+)'
    match = re.search(url_pattern, input_str)
    if match:
        return match.group(1)
    # If no match, assume it's already a folder ID
    return input_str

def get_folder_name(service, folder_id):
    """Get the name of a Google Drive folder by its ID."""
    try:
        folder = service.files().get(fileId=folder_id, fields='name').execute()
        return folder.get('name', 'Untitled Folder')
    except Exception as e:
        logger.exception(f"Error getting folder name: {e}")
        return 'Untitled Folder'

def get_or_create_album(creds, album_title):
    """Get existing album ID or create a new album in Google Photos."""
    token = get_valid_token(creds)
    headers = {
        'Content-type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    # Search for existing album with pagination
    list_url = 'https://photoslibrary.googleapis.com/v1/albums'
    page_token = None

    while True:
        params = {'pageSize': 50}
        if page_token:
            params['pageToken'] = page_token

        response = requests.get(list_url, headers=headers, params=params)

        if response.status_code == 200:
            result = response.json()
            albums = result.get('albums', [])

            # Check if album exists in this page
            for album in albums:
                if album.get('title') == album_title:
                    logger.info(f"Using existing album: {album_title}")
                    return album['id']

            # Check if there are more pages
            page_token = result.get('nextPageToken')
            if not page_token:
                break  # No more pages
        else:
            logger.warning(f"Failed to list albums: {response.text}")
            break

    # Create new album if not found
    create_url = 'https://photoslibrary.googleapis.com/v1/albums'
    body = {"album": {"title": album_title}}
    response = requests.post(create_url, headers=headers, json=body)

    if response.status_code == 200:
        album_id = response.json()['id']
        logger.info(f"Created new album: {album_title}")
        return album_id
    else:
        logger.error(f"Failed to create album: {response.text}")
        return None

def download_from_drive(service, file_id, file_name):
    """Download a file from Google Drive. Raises exception on failure."""
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(file_name, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return file_name

def check_ffmpeg_installed():
    """Check if ffmpeg is installed and available."""
    return shutil.which('ffmpeg') is not None

def should_convert_video(file_name):
    """Check if video file should be converted to smaller format."""
    # File extensions that typically have large file sizes
    large_video_formats = ['.mts', '.m2ts', '.mod', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpg', '.mpeg', '.vob']
    ext = os.path.splitext(file_name.lower())[1]
    return ext in large_video_formats

def convert_video_to_mp4(input_path, original_filename):
    """
    Convert video file to MP4 with H.264 encoding for smaller file size.
    Returns the path to the converted file. Raises exception on failure.
    """
    if not check_ffmpeg_installed():
        logger.warning("  ffmpeg not installed, skipping conversion (install with: brew install ffmpeg)")
        return input_path

    # Create output filename
    base_name = os.path.splitext(input_path)[0]
    output_path = f"{base_name}_converted.mp4"

    original_size = os.path.getsize(input_path) / (1024 * 1024)  # MB
    logger.info(f"  Converting {original_filename} ({original_size:.1f}MB) to MP4 using ffmpeg...")

    try:
        # FFmpeg command for good quality with reasonable file size
        # -crf 23 is the default quality (lower = better, 18-28 is reasonable range)
        # -preset medium balances speed and compression
        # -movflags +faststart optimizes for streaming/web playback
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',          # H.264 video codec
            '-crf', '23',                # Quality level (18-28 recommended)
            '-preset', 'medium',         # Encoding speed/compression balance
            '-c:a', 'aac',               # AAC audio codec
            '-b:a', '128k',              # Audio bitrate
            '-movflags', '+faststart',   # Optimize for streaming
            '-y',                        # Overwrite output file
            output_path
        ]

        # Run ffmpeg
        logger.info(f"  Running ffmpeg conversion (this may take several minutes)...")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3600  # 1 hour timeout for very large files
        )

        if result.returncode != 0:
            raise Exception(f"ffmpeg conversion failed: {result.stderr}")

        # Check that output file was created and is not empty
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Converted file is missing or empty")

        # Log size reduction
        converted_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
        reduction_pct = ((original_size - converted_size) / original_size * 100) if original_size > 0 else 0

        logger.success(f"  Conversion complete: {original_size:.1f}MB → {converted_size:.1f}MB ({reduction_pct:.1f}% reduction)")

        return output_path

    except subprocess.TimeoutExpired:
        raise Exception("Video conversion timed out after 1 hour")
    except Exception as e:
        # Clean up partial output file if it exists
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        raise Exception(f"Video conversion failed: {str(e)}")

def upload_to_photos(creds, file_path, filename, album_id=None):
    """Upload a file to Google Photos. Raises exception on failure."""
    # Get a fresh token for this upload
    token = get_valid_token(creds)

    # Step 1: Upload bytes to get an upload token
    upload_url = 'https://photoslibrary.googleapis.com/v1/uploads'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-type': 'application/octet-stream',
        'X-Goog-Upload-Protocol': 'raw',
        'X-Goog-Upload-File-Name': os.path.basename(file_path),
    }

    with open(file_path, 'rb') as f:
        response = requests.post(upload_url, headers=headers, data=f)

    if response.status_code != 200:
        error_msg = f"Upload failed with status {response.status_code}: {response.text}"
        raise Exception(error_msg)

    upload_token = response.text

    # Step 2: Create media item in library (refresh token again if needed)
    token = get_valid_token(creds)
    create_url = 'https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate'
    headers = {
        'Content-type': 'application/json',
        'Authorization': f'Bearer {token}',
    }
    body = {
        "newMediaItems": [{
            "description": f"Original filename: {filename}",
            "simpleMediaItem": {"uploadToken": upload_token}
        }]
    }

    # Add album if specified
    if album_id:
        body["albumId"] = album_id

    res = requests.post(create_url, headers=headers, json=body)
    result = res.json()

    # Check if upload was successful
    if res.status_code == 200 and result.get('newMediaItemResults'):
        status = result['newMediaItemResults'][0].get('status', {})
        if status.get('message') == 'Success' or not status:
            return True
        else:
            raise Exception(f"Media item creation failed: {status}")

    raise Exception(f"Failed to create media item (status {res.status_code}): {result}")

def process_single_file_with_retry(service, creds, file_id, file_name, album_id=None):
    """
    Process a single file with retry logic.
    Returns (success: bool, error_message: str or None)
    """
    local_file = None
    converted_file = None
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Download from Drive
            local_file = download_from_drive(service, file_id, file_name)
            download_size = os.path.getsize(local_file) / (1024 * 1024)  # MB
            logger.info(f"  Downloaded: {download_size:.1f}MB")

            # Check if video should be converted
            file_to_upload = local_file
            if should_convert_video(file_name):
                logger.info(f"  Large video format detected, will convert to MP4")
                try:
                    converted_file = convert_video_to_mp4(local_file, file_name)
                    if converted_file != local_file:
                        file_to_upload = converted_file
                        logger.info(f"  Using converted file for upload")
                    else:
                        file_to_upload = local_file
                        logger.info(f"  Conversion skipped, using original file")
                except Exception as conv_error:
                    logger.warning(f"  Video conversion failed, uploading original: {conv_error}")
                    # Continue with original file if conversion fails
                    file_to_upload = local_file

            # Upload to Photos
            logger.info(f"  Uploading to Google Photos...")
            upload_to_photos(creds, file_to_upload, file_name, album_id)

            # Success! Clean up and return
            if local_file and os.path.exists(local_file):
                os.remove(local_file)
            if converted_file and os.path.exists(converted_file) and converted_file != local_file:
                os.remove(converted_file)
            return True, None

        except Exception as e:
            last_error = str(e)
            logger.exception(f"  Attempt {attempt}/{MAX_RETRIES} failed: {last_error}")

            # Clean up local files if they exist
            if local_file and os.path.exists(local_file):
                try:
                    os.remove(local_file)
                except:
                    pass
            if converted_file and os.path.exists(converted_file) and converted_file != local_file:
                try:
                    os.remove(converted_file)
                except:
                    pass

            # If not the last attempt, wait before retrying
            if attempt < MAX_RETRIES:
                logger.info(f"  Waiting {RETRY_WAIT_SECONDS} seconds before retry...")
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                logger.exception(f"  All {MAX_RETRIES} attempts failed")

    # All retries failed
    return False, last_error

def plan_folder(service, folder_id, planned_count=None):
    """
    Scan folder recursively and save all image/video files to planned_files.txt.
    Returns the total count of files found.
    """
    if planned_count is None:
        planned_count = {'images': 0, 'videos': 0, 'other': 0}

    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name, mimeType, webViewLink)").execute()
    items = results.get('files', [])

    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            # Recursively scan subfolders
            plan_folder(service, item['id'], planned_count)
        elif 'image' in item['mimeType']:
            # Found an image file
            file_id = item['id']
            file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")
            save_planned_file(file_id, file_url, item['name'], item['mimeType'])
            planned_count['images'] += 1
            logger.info(f"Found image: {item['name']}")
        elif 'video' in item['mimeType']:
            # Found a video file
            file_id = item['id']
            file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")
            save_planned_file(file_id, file_url, item['name'], item['mimeType'])
            planned_count['videos'] += 1
            logger.info(f"Found video: {item['name']}")
        else:
            # Non-image/video file
            planned_count['other'] += 1
            logger.debug(f"Skipping (not image/video): {item['name']} (type: {item['mimeType']})")

    return planned_count

def process_from_plan(service, creds, planned_files, album_id, processed_files, failed_files):
    """
    Process files from the planned_files list.
    """
    total_files = len(planned_files)
    processed_count = 0
    failed_count = 0
    skipped_count = 0

    logger.info(f"Processing {total_files} files from plan...")

    for idx, (file_id, file_url, file_name, mime_type) in enumerate(planned_files, 1):
        # Check if already processed
        if file_id in processed_files:
            logger.info(f"[{idx}/{total_files}] Skipping (already processed): {file_name}")
            skipped_count += 1
            continue

        # Check if previously failed
        if file_id in failed_files:
            logger.warning(f"[{idx}/{total_files}] Skipping (previously failed): {file_name}")
            skipped_count += 1
            continue

        logger.info(f"[{idx}/{total_files}] Processing: {file_name}...")
        success, error_msg = process_single_file_with_retry(
            service, creds, file_id, file_name, album_id
        )

        if success:
            # Save to processed files log
            save_processed_file(file_id, file_url)
            processed_files.add(file_id)
            processed_count += 1
            logger.success(f"[{idx}/{total_files}] Done: {file_name}")
        else:
            # Save to failed files log
            save_failed_file(file_id, file_url, error_msg)
            failed_files.add(file_id)
            failed_count += 1
            logger.error(f"[{idx}/{total_files}] Failed permanently: {file_name}")

    return processed_count, failed_count, skipped_count

def process_folder(service, creds, folder_id, album_id=None, processed_files=None, failed_files=None, skipped_files=None):
    if processed_files is None:
        processed_files = set()
    if failed_files is None:
        failed_files = set()
    if skipped_files is None:
        skipped_files = set()

    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name, mimeType, webViewLink)").execute()
    items = results.get('files', [])

    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            process_folder(service, creds, item['id'], album_id, processed_files, failed_files, skipped_files)
        elif 'image' in item['mimeType'] or 'video' in item['mimeType']:
            file_id = item['id']
            file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")

            # Check if already processed
            if file_id in processed_files:
                logger.info(f"Skipping (already processed): {item['name']}")
                continue

            # Check if previously failed
            if file_id in failed_files:
                logger.warning(f"Skipping (previously failed): {item['name']}")
                continue

            logger.info(f"Processing: {item['name']}...")
            success, error_msg = process_single_file_with_retry(
                service, creds, file_id, item['name'], album_id
            )

            if success:
                # Save to processed files log
                save_processed_file(file_id, file_url)
                processed_files.add(file_id)
                logger.success(f"Done: {item['name']}")
            else:
                # Save to failed files log
                save_failed_file(file_id, file_url, error_msg)
                failed_files.add(file_id)
                logger.error(f"Failed permanently: {item['name']}")
        else:
            # Skip non-image/video files
            file_id = item['id']
            file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")

            # Check if already logged as skipped
            if file_id not in skipped_files:
                save_skipped_file(file_id, file_url, item['mimeType'])
                skipped_files.add(file_id)
                logger.info(f"Skipping (not image/video): {item['name']} (type: {item['mimeType']})")

if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Download photos/videos from Google Drive and upload to Google Photos')
        parser.add_argument('folder', nargs='?', help='Google Drive folder URL or folder ID (required for --plan mode)')
        parser.add_argument('--plan', action='store_true',
                          help='Scan folder and save list of files to planned_files.txt without processing')
        parser.add_argument('--execute', action='store_true',
                          help='Process files from planned_files.txt (must run --plan first)')
        parser.add_argument('--album', type=str, default=None,
                          help='Album name for Google Photos (default: FOTO for --execute, folder name for other modes)')
        args = parser.parse_args()

        logger.info(f"Fotointegrator started - Log file: {log_filename}")

        # Validate argument combinations
        if args.execute:
            # Execute mode: process from plan file
            if not os.path.exists(PLANNED_FILES_LOG):
                logger.error(f"Plan file not found: {PLANNED_FILES_LOG}")
                logger.error("Please run with --plan first to scan and create the plan file")
                logger.error(f"Example: python {sys.argv[0]} FOLDER_ID --plan")
                sys.exit(1)

            logger.info("Running in EXECUTE mode - processing files from plan...")

            # Load planned files
            planned_files = load_planned_files()
            if not planned_files:
                logger.error("Plan file is empty or invalid")
                sys.exit(1)

            logger.info(f"Loaded {len(planned_files)} files from plan")

            # Load previously processed and failed files
            processed_files = load_processed_files()
            failed_files = load_failed_files()
            logger.info(f"Loaded {len(processed_files)} previously processed files")
            logger.info(f"Loaded {len(failed_files)} previously failed files")

            # Get services
            drive_service, creds = get_services()

            # Determine album name
            album_name = args.album if args.album else 'FOTO'
            logger.info(f"Using album name: {album_name}")

            # Create/get album
            album_id = get_or_create_album(creds, album_name)

            # Process files from plan
            processed_count, failed_count, skipped_count = process_from_plan(
                drive_service, creds, planned_files, album_id, processed_files, failed_files
            )

            logger.info("Execution complete!")
            logger.info(f"Successfully processed: {processed_count} files")
            logger.info(f"Failed: {failed_count} files")
            logger.info(f"Skipped (already processed/failed): {skipped_count} files")

        elif args.plan:
            # Plan mode: scan and save file list without processing
            if not args.folder:
                logger.error("Folder argument is required for --plan mode")
                logger.error(f"Example: python {sys.argv[0]} FOLDER_ID --plan")
                sys.exit(1)

            # Extract folder ID from URL if necessary
            folder_id = extract_folder_id(args.folder)
            logger.info(f"Using folder ID: {folder_id}")

            # Get services
            drive_service, creds = get_services()

            # Get folder name
            folder_name = get_folder_name(drive_service, folder_id)
            logger.info(f"Folder name: {folder_name}")

            logger.info("Running in PLAN mode - scanning folder structure...")

            # Clear previous plan file
            if os.path.exists(PLANNED_FILES_LOG):
                os.remove(PLANNED_FILES_LOG)
                logger.info(f"Cleared previous plan file: {PLANNED_FILES_LOG}")

            # Scan folder recursively
            counts = plan_folder(drive_service, folder_id)

            logger.info("Planning complete!")
            logger.info(f"Found {counts['images']} image files")
            logger.info(f"Found {counts['videos']} video files")
            logger.info(f"Found {counts['other']} other files (skipped)")
            logger.info(f"Plan saved to: {PLANNED_FILES_LOG}")
        else:
            # Normal processing mode
            if not args.folder:
                logger.error("Folder argument is required for normal processing mode")
                logger.error(f"Example: python {sys.argv[0]} FOLDER_ID")
                sys.exit(1)

            # Extract folder ID from URL if necessary
            folder_id = extract_folder_id(args.folder)
            logger.info(f"Using folder ID: {folder_id}")

            # Get services
            drive_service, creds = get_services()

            # Get folder name
            folder_name = get_folder_name(drive_service, folder_id)
            logger.info(f"Folder name: {folder_name}")

            # Load previously processed, failed, and skipped files
            processed_files = load_processed_files()
            failed_files = load_failed_files()
            skipped_files = load_skipped_files()
            logger.info(f"Loaded {len(processed_files)} previously processed files")
            logger.info(f"Loaded {len(failed_files)} previously failed files")
            logger.info(f"Loaded {len(skipped_files)} previously skipped files")

            # Determine album name (use --album if provided, otherwise folder name)
            album_name = args.album if args.album else folder_name
            logger.info(f"Using album name: {album_name}")

            # Create/get album
            album_id = get_or_create_album(creds, album_name)

            # Process folder and upload to album
            process_folder(drive_service, creds, folder_id, album_id, processed_files, failed_files, skipped_files)

            logger.info("Processing complete!")
            logger.info(f"Successfully processed: {len(processed_files)} files")
            logger.info(f"Failed: {len(failed_files)} files")
            logger.info(f"Skipped (non-image/video): {len(skipped_files)} files")

    except Exception as e:
        logger.exception(f"Fatal error in main execution: {e}")
        sys.exit(1)

