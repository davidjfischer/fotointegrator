import os
import io
import sys
import requests
import pickle
import argparse
import re
import time
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

# Add stdout handler (colorized)
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS UTC}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True
)

# Add file handler (no color codes in file)
logger.add(
    log_filename,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS UTC} | {level: <8} | {message}",
    level="INFO",
    colorize=False
)

# If modifying these scopes, delete the file token.pickle.
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary'
]

PROCESSED_FILES_LOG = 'processed_files.txt'
FAILED_FILES_LOG = 'failed_files.txt'
SKIPPED_FILES_LOG = 'skipped_files.txt'
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
    return drive_service, creds.token

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
        logger.error(f"Error getting folder name: {e}")
        return 'Untitled Folder'

def get_or_create_album(token, album_title):
    """Get existing album ID or create a new album in Google Photos."""
    headers = {
        'Content-type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    # Search for existing album
    list_url = 'https://photoslibrary.googleapis.com/v1/albums'
    response = requests.get(list_url, headers=headers)

    if response.status_code == 200:
        albums = response.json().get('albums', [])
        for album in albums:
            if album.get('title') == album_title:
                logger.info(f"Using existing album: {album_title}")
                return album['id']

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

def upload_to_photos(token, file_path, filename, album_id=None):
    """Upload a file to Google Photos. Raises exception on failure."""
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

    # Step 2: Create media item in library
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

def process_single_file_with_retry(service, token, file_id, file_name, album_id=None):
    """
    Process a single file with retry logic.
    Returns (success: bool, error_message: str or None)
    """
    local_file = None
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Download from Drive
            local_file = download_from_drive(service, file_id, file_name)

            # Upload to Photos
            upload_to_photos(token, local_file, file_name, album_id)

            # Success! Clean up and return
            if local_file and os.path.exists(local_file):
                os.remove(local_file)
            return True, None

        except Exception as e:
            last_error = str(e)
            logger.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed: {last_error}")

            # Clean up local file if it exists
            if local_file and os.path.exists(local_file):
                try:
                    os.remove(local_file)
                except:
                    pass

            # If not the last attempt, wait before retrying
            if attempt < MAX_RETRIES:
                logger.info(f"  Waiting {RETRY_WAIT_SECONDS} seconds before retry...")
                time.sleep(RETRY_WAIT_SECONDS)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed")

    # All retries failed
    return False, last_error

def process_folder(service, token, folder_id, album_id=None, processed_files=None, failed_files=None, skipped_files=None):
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
            process_folder(service, token, item['id'], album_id, processed_files, failed_files, skipped_files)
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
                service, token, file_id, item['name'], album_id
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
    parser = argparse.ArgumentParser(description='Download photos/videos from Google Drive and upload to Google Photos')
    parser.add_argument('folder', help='Google Drive folder URL or folder ID')
    args = parser.parse_args()

    logger.info(f"Fotointegrator started - Log file: {log_filename}")

    # Extract folder ID from URL if necessary
    folder_id = extract_folder_id(args.folder)
    logger.info(f"Using folder ID: {folder_id}")

    # Load previously processed, failed, and skipped files
    processed_files = load_processed_files()
    failed_files = load_failed_files()
    skipped_files = load_skipped_files()
    logger.info(f"Loaded {len(processed_files)} previously processed files")
    logger.info(f"Loaded {len(failed_files)} previously failed files")
    logger.info(f"Loaded {len(skipped_files)} previously skipped files")

    # Get services
    drive_service, auth_token = get_services()

    # Get folder name and create/get album
    folder_name = get_folder_name(drive_service, folder_id)
    logger.info(f"Folder name: {folder_name}")

    album_id = get_or_create_album(auth_token, folder_name)

    # Process folder and upload to album
    process_folder(drive_service, auth_token, folder_id, album_id, processed_files, failed_files, skipped_files)

    logger.info("Processing complete!")
    logger.info(f"Successfully processed: {len(processed_files)} files")
    logger.info(f"Failed: {len(failed_files)} files")
    logger.info(f"Skipped (non-image/video): {len(skipped_files)} files")

