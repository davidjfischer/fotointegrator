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

# ============================================================================
# CONSTANTS
# ============================================================================

# Directories
LOGS_DIR = 'logs'
STATE_DIR = 'state'

# File path helper functions (these will be set per folder_id)
def get_processed_files_log(folder_id):
    """Get path to processed files log for a specific folder."""
    return os.path.join(STATE_DIR, f'{folder_id}_processed_files.txt')

def get_failed_files_log(folder_id):
    """Get path to failed files log for a specific folder."""
    return os.path.join(STATE_DIR, f'{folder_id}_failed_files.txt')

def get_skipped_files_log(folder_id):
    """Get path to skipped files log for a specific folder."""
    return os.path.join(STATE_DIR, f'{folder_id}_skipped_files.txt')

def get_planned_files_log(folder_id):
    """Get path to planned files log for a specific folder."""
    return os.path.join(STATE_DIR, f'{folder_id}_planned_files.txt')

def get_log_filename(folder_id):
    """Get path to log file for a specific folder."""
    start_time = datetime.now(timezone.utc)
    return os.path.join(LOGS_DIR, f"{folder_id}_{start_time.strftime('%Y%m%d_%H%M%S_UTC')}_fotointegrator.log")

# OAuth Scopes (updated for post-March 31, 2025)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata'
]

# Retry configuration
MAX_RETRIES = 10
RETRY_WAIT_SECONDS = 30

# File size validation
MIN_FILE_SIZE_BYTES = 16384  # Default minimum file size in bytes (16 KB)

# File type extensions
AUDIO_EXTENSIONS = ['.mp3', '.m4a', '.aac', '.wav', '.wma', '.ogg', '.flac']
VIDEO_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm', '.mts', '.m2ts', '.mpg', '.mpeg', '.wmv']
DISK_IMAGE_EXTENSIONS = ['.iso', '.img', '.dmg', '.toast', '.vcd', '.bin', '.cue', '.nrg', '.mdf', '.mds']

# Video conversion
VIDEO_FORMATS_TO_CONVERT = ['.mts', '.m2ts', '.mod', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpg', '.mpeg', '.vob']
FFMPEG_CRF_QUALITY = '23'  # 18-28 recommended, 23 is default
FFMPEG_PRESET = 'medium'
AUDIO_BITRATE = '128k'

# Default album name
DEFAULT_ALBUM_NAME = 'FOTO'

# UI separators
SEPARATOR_LINE = "=" * 70

# ============================================================================
# INITIALIZATION
# ============================================================================

# Create directories
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

# Configure loguru (stdout only initially)
logger.remove()
logger.configure(patcher=lambda record: record.update(time=record["time"].astimezone(timezone.utc)))

logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS UTC}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
    backtrace=True,
    diagnose=True
)

# Global variable to store log filename
_log_filename = None

def setup_file_logging(folder_id):
    """Set up file logging for a specific folder."""
    global _log_filename
    _log_filename = get_log_filename(folder_id)
    logger.add(
        _log_filename,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS UTC} | {level: <8} | {message}",
        level="INFO",
        colorize=False,
        backtrace=True,
        diagnose=True
    )
    return _log_filename

# ============================================================================
# FILE TRACKING FUNCTIONS
# ============================================================================

def _load_file_ids_from_log(log_file, description="files"):
    """
    Generic function to load file IDs from a log file.

    Args:
        log_file: Path to the log file
        description: Description for logging purposes

    Returns:
        Set of file IDs
    """
    if not os.path.exists(log_file):
        return set()

    file_ids = set()
    with open(log_file, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if parts:
                file_ids.add(parts[0])
    return file_ids


def load_processed_files(folder_id):
    """Load the set of already processed file IDs."""
    return _load_file_ids_from_log(get_processed_files_log(folder_id), "processed")


def load_failed_files(folder_id):
    """Load the set of failed file IDs."""
    return _load_file_ids_from_log(get_failed_files_log(folder_id), "failed")


def load_skipped_files(folder_id):
    """Load the set of skipped file IDs."""
    return _load_file_ids_from_log(get_skipped_files_log(folder_id), "skipped")


def save_processed_file(folder_id, file_id, file_url):
    """Save a processed file ID and its Drive URL to the log file."""
    with open(get_processed_files_log(folder_id), 'a') as f:
        f.write(f"{file_id}|{file_url}\n")


def load_failed_files_detailed(folder_id):
    """
    Load failed files with full details from the log file.
    Returns a list of tuples: (file_id, file_url, file_name, error_msg)
    """
    failed_log = get_failed_files_log(folder_id)
    if not os.path.exists(failed_log):
        return []

    failed = []
    with open(failed_log, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 4:
                file_id, file_url, file_name, error_msg = parts[0], parts[1], parts[2], '|'.join(parts[3:])
                failed.append((file_id, file_url, file_name, error_msg))
            elif len(parts) == 3:
                # Old format without filename - use placeholder
                file_id, file_url, error_msg = parts[0], parts[1], parts[2]
                file_name = f"unknown_{file_id}"
                failed.append((file_id, file_url, file_name, error_msg))
    return failed


def save_failed_file(folder_id, file_id, file_url, file_name, error_msg):
    """Save a failed file to the log."""
    with open(get_failed_files_log(folder_id), 'a') as f:
        error_msg_cleaned = error_msg.replace('\n', ' ').replace('|', ':')
        f.write(f"{file_id}|{file_url}|{file_name}|{error_msg_cleaned}\n")


def remove_from_failed_files(folder_id, file_id):
    """Remove a file from the failed files log."""
    failed_log = get_failed_files_log(folder_id)
    if not os.path.exists(failed_log):
        return

    lines_to_keep = []
    with open(failed_log, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if parts and parts[0] != file_id:
                lines_to_keep.append(line)

    with open(failed_log, 'w') as f:
        f.writelines(lines_to_keep)


def save_skipped_file(folder_id, file_id, file_url, mime_type, reason="Not image/video"):
    """Save a skipped file to the log."""
    with open(get_skipped_files_log(folder_id), 'a') as f:
        f.write(f"{file_id}|{file_url}|{mime_type}|{reason}\n")


def save_planned_file(folder_id, file_id, file_url, file_name, mime_type):
    """Save a planned file to the plan file."""
    with open(get_planned_files_log(folder_id), 'a') as f:
        f.write(f"{file_id}|{file_url}|{file_name}|{mime_type}\n")


def load_planned_files(folder_id):
    """
    Load planned files from the plan file.
    Returns a list of tuples: (file_id, file_url, file_name, mime_type)
    """
    planned_log = get_planned_files_log(folder_id)
    if not os.path.exists(planned_log):
        return None

    planned = []
    with open(planned_log, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 4:
                file_id, file_url, file_name, mime_type = parts[0], parts[1], parts[2], parts[3]
                planned.append((file_id, file_url, file_name, mime_type))
    return planned


# ============================================================================
# GOOGLE API FUNCTIONS
# ============================================================================

def get_services():
    """Initialize and return Google Drive service and credentials."""
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
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        else:
            raise Exception("Credentials are invalid and cannot be refreshed")
    return creds.token


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

            for album in albums:
                if album.get('title') == album_title:
                    logger.info(f"Using existing album: {album_title}")
                    return album['id']

            page_token = result.get('nextPageToken')
            if not page_token:
                break
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


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_folder_id(input_str):
    """Extract folder ID from Google Drive URL or return the input if it's already an ID."""
    url_pattern = r'/folders/([a-zA-Z0-9_-]+)'
    match = re.search(url_pattern, input_str)
    if match:
        return match.group(1)
    return input_str


def check_ffmpeg_installed():
    """Check if ffmpeg is installed and available."""
    return shutil.which('ffmpeg') is not None


def check_ffprobe_installed():
    """Check if ffprobe is installed and available."""
    return shutil.which('ffprobe') is not None


def video_has_audio_stream(file_path):
    """
    Check if a video file contains an audio stream using ffprobe.
    Returns True if audio stream exists, False otherwise.
    """
    if not check_ffprobe_installed():
        logger.warning("  ffprobe not installed, cannot check for audio stream")
        return True  # Assume audio exists if we can't check

    try:
        logger.info(f"  Running ffprobe to detect audio stream...")
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_type',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )

        # If output contains 'audio', then audio stream exists
        has_audio = 'audio' in result.stdout.lower()

        if has_audio:
            logger.info(f"  ✓ Audio stream detected in video file")
        else:
            logger.warning(f"  ✗ No audio stream found in video file")

        return has_audio

    except Exception as e:
        logger.warning(f"  Error checking audio stream: {e}")
        return True  # Assume audio exists on error


def combine_video_and_audio(video_path, audio_path, output_path):
    """
    Combine video file (without audio) and audio file into a single video file.
    Uses ffmpeg to merge the streams.
    Returns the output path on success, raises exception on failure.
    """
    if not check_ffmpeg_installed():
        raise Exception("ffmpeg not installed, cannot combine video and audio")

    video_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
    audio_size = os.path.getsize(audio_path) / (1024 * 1024)  # MB

    logger.info(f"  Combining video and audio streams...")
    logger.info(f"    Video: {os.path.basename(video_path)} ({video_size:.1f}MB)")
    logger.info(f"    Audio: {os.path.basename(audio_path)} ({audio_size:.1f}MB)")
    logger.info(f"    Output: {os.path.basename(output_path)}")

    try:
        logger.info(f"  Running ffmpeg to merge streams (this may take a few minutes)...")
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',  # Copy video stream without re-encoding
            '-c:a', 'aac',   # Re-encode audio to AAC
            '-b:a', AUDIO_BITRATE,
            '-shortest',  # Match shortest stream duration
            '-y',
            output_path
        ]

        import time
        start_time = time.time()

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3600
        )

        elapsed_time = time.time() - start_time

        if result.returncode != 0:
            raise Exception(f"ffmpeg merge failed: {result.stderr}")

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Combined file is missing or empty")

        combined_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
        logger.success(f"  ✓ Successfully combined video+audio in {elapsed_time:.1f}s")
        logger.info(f"    Input:  {video_size:.1f}MB (video) + {audio_size:.1f}MB (audio)")
        logger.info(f"    Output: {combined_size:.1f}MB (combined)")

        return output_path

    except subprocess.TimeoutExpired:
        raise Exception("Video+audio combination timed out after 1 hour")
    except Exception as e:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        raise Exception(f"Failed to combine video and audio: {str(e)}")


def should_convert_video(file_name):
    """Check if video file should be converted to smaller format."""
    ext = os.path.splitext(file_name.lower())[1]
    return ext in VIDEO_FORMATS_TO_CONVERT


def normalize_filename_for_matching(filename):
    """
    Normalize a filename for matching audio/video pairs.
    Removes common keywords and separators to find related files.

    Examples:
        "video123" -> "123"
        "recording_video" -> "recording"
        "my_audio_file" -> "my_file"
    """
    # Convert to lowercase
    normalized = filename.lower()

    # Remove common video/audio keywords with various separators
    patterns_to_remove = [
        'video_', '_video', 'video-', '-video', 'video ', ' video',
        'audio_', '_audio', 'audio-', '-audio', 'audio ', ' audio',
        'vid_', '_vid', 'vid-', '-vid', 'vid ', ' vid',
        'aud_', '_aud', 'aud-', '-aud', 'aud ', ' aud',
    ]

    for pattern in patterns_to_remove:
        normalized = normalized.replace(pattern, '')

    # Also try removing the keywords without separators at start/end
    if normalized.startswith('video'):
        normalized = normalized[5:]
    if normalized.startswith('audio'):
        normalized = normalized[5:]
    if normalized.startswith('vid'):
        normalized = normalized[3:]
    if normalized.startswith('aud'):
        normalized = normalized[3:]

    if normalized.endswith('video'):
        normalized = normalized[:-5]
    if normalized.endswith('audio'):
        normalized = normalized[:-5]
    if normalized.endswith('vid'):
        normalized = normalized[:-3]
    if normalized.endswith('aud'):
        normalized = normalized[:-3]

    # Remove extra separators at start/end
    normalized = normalized.strip('_- ')

    return normalized


def filenames_match(name1, name2):
    """
    Check if two filenames match for audio/video pairing.

    Returns True if:
    1. Exact base name match, OR
    2. Normalized base names match (after removing video/audio keywords)
    """
    # Exact match
    if name1 == name2:
        return True

    # Normalized match
    norm1 = normalize_filename_for_matching(name1)
    norm2 = normalize_filename_for_matching(name2)

    # Only consider it a match if there's something left after normalization
    if norm1 and norm2 and norm1 == norm2:
        return True

    return False


def find_matching_audio_file(service, folder_id, video_filename):
    """
    Search for an audio file with the same base name as the video file.
    Handles common naming variations like "video123.mp4" / "audio123.m4a".
    Returns (file_id, file_name) tuple if found, None otherwise.
    """
    base_name = os.path.splitext(video_filename)[0]

    logger.info(f"  Searching for matching audio file...")
    logger.info(f"    Base name: {base_name}")
    logger.info(f"    Normalized: {normalize_filename_for_matching(base_name)}")
    logger.info(f"    Looking for extensions: {', '.join(AUDIO_EXTENSIONS)}")

    try:
        # Search broadly - look for all audio files in the folder
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])

        audio_candidates = []
        for item in items:
            item_ext = os.path.splitext(item['name'].lower())[1]
            # Explicitly exclude video file extensions
            if item_ext in VIDEO_EXTENSIONS:
                continue
            if item_ext in AUDIO_EXTENSIONS or 'audio' in item.get('mimeType', ''):
                audio_candidates.append(item)

        logger.info(f"    Found {len(audio_candidates)} audio file(s) in folder")

        for item in audio_candidates:
            item_base_name = os.path.splitext(item['name'])[0]
            logger.info(f"      - Checking: {item['name']}")
            logger.info(f"        Normalized: {normalize_filename_for_matching(item_base_name)}")

            # Check if filenames match (exact or normalized)
            if filenames_match(base_name, item_base_name):
                logger.info(f"  ✓ Found matching audio file: {item['name']}")
                return (item['id'], item['name'])

        logger.warning(f"  ✗ No matching audio file found in {len(audio_candidates)} audio file(s)")
        return None

    except Exception as e:
        logger.warning(f"  Error searching for audio file: {e}")
        return None


def find_matching_video_file(service, folder_id, audio_filename):
    """
    Search for a video file with the same base name as the audio file.
    Handles common naming variations like "audio123.m4a" / "video123.mp4".
    Returns (file_id, file_name, file_url) tuple if found, None otherwise.
    """
    base_name = os.path.splitext(audio_filename)[0]

    logger.info(f"  Searching for matching video file...")
    logger.info(f"    Base name: {base_name}")
    logger.info(f"    Normalized: {normalize_filename_for_matching(base_name)}")
    logger.info(f"    Looking for extensions: {', '.join(VIDEO_EXTENSIONS)}")

    try:
        # Search broadly - look for all video files in the folder
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, mimeType, webViewLink)").execute()
        items = results.get('files', [])

        video_candidates = []
        for item in items:
            item_ext = os.path.splitext(item['name'].lower())[1]
            # Explicitly exclude audio file extensions even if MIME type says "video"
            if item_ext in AUDIO_EXTENSIONS:
                continue
            if item_ext in VIDEO_EXTENSIONS or 'video' in item.get('mimeType', ''):
                video_candidates.append(item)

        logger.info(f"    Found {len(video_candidates)} video file(s) in folder")

        for item in video_candidates:
            item_base_name = os.path.splitext(item['name'])[0]
            logger.info(f"      - Checking: {item['name']}")
            logger.info(f"        Normalized: {normalize_filename_for_matching(item_base_name)}")

            # Check if filenames match (exact or normalized)
            if filenames_match(base_name, item_base_name):
                file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{item['id']}/view")
                logger.info(f"  ✓ Found matching video file: {item['name']}")
                return (item['id'], item['name'], file_url)

        logger.warning(f"  ✗ No matching video file found in {len(video_candidates)} video file(s)")
        return None

    except Exception as e:
        logger.warning(f"  Error searching for video file: {e}")
        return None


# ============================================================================
# FILE PROCESSING FUNCTIONS
# ============================================================================

def download_from_drive(service, file_id, file_name):
    """Download a file from Google Drive. Raises exception on failure."""
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(file_name, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return file_name


def convert_video_to_mp4(input_path, original_filename):
    """
    Convert video file to MP4 with H.264 encoding for smaller file size.
    Returns the path to the converted file. Raises exception on failure.
    """
    if not check_ffmpeg_installed():
        logger.warning("  ffmpeg not installed, skipping conversion (install with: brew install ffmpeg)")
        return input_path

    base_name = os.path.splitext(input_path)[0]
    output_path = f"{base_name}_converted.mp4"

    original_size = os.path.getsize(input_path) / (1024 * 1024)  # MB
    logger.info(f"  Converting {original_filename} ({original_size:.1f}MB) to MP4 using ffmpeg...")

    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',
            '-crf', FFMPEG_CRF_QUALITY,
            '-preset', FFMPEG_PRESET,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-movflags', '+faststart',
            '-y',
            output_path
        ]

        logger.info(f"  Running ffmpeg conversion (this may take several minutes)...")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3600
        )

        if result.returncode != 0:
            raise Exception(f"ffmpeg conversion failed: {result.stderr}")

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Converted file is missing or empty")

        converted_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
        reduction_pct = ((original_size - converted_size) / original_size * 100) if original_size > 0 else 0

        logger.success(f"  Conversion complete: {original_size:.1f}MB → {converted_size:.1f}MB ({reduction_pct:.1f}% reduction)")

        return output_path

    except subprocess.TimeoutExpired:
        raise Exception("Video conversion timed out after 1 hour")
    except Exception as e:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        raise Exception(f"Video conversion failed: {str(e)}")


def upload_to_photos(creds, file_path, filename, album_id=None):
    """Upload a file to Google Photos. Raises exception on failure."""
    token = get_valid_token(creds)

    # Step 1: Upload bytes
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

    # Step 2: Create media item
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

    if album_id:
        body["albumId"] = album_id

    res = requests.post(create_url, headers=headers, json=body)
    result = res.json()

    if res.status_code == 200 and result.get('newMediaItemResults'):
        status = result['newMediaItemResults'][0].get('status', {})
        if status.get('message') == 'Success' or not status:
            return True
        else:
            error_code = status.get('code', 'unknown')
            error_msg = status.get('message', 'unknown error')

            # Provide helpful context for common error codes
            if error_code == 3:
                hint = " (Possible causes: corrupted/empty file, unsupported format, or invalid upload token)"
            else:
                hint = ""

            raise Exception(f"Media item creation failed: code={error_code}, message='{error_msg}'{hint}")

    raise Exception(f"Failed to create media item (status {res.status_code}): {result}")


def process_single_file_with_retry(service, creds, file_id, file_name, folder_id, file_url, album_id=None, max_retries=MAX_RETRIES, retry_wait_seconds=RETRY_WAIT_SECONDS, min_bytes=MIN_FILE_SIZE_BYTES):
    """
    Process a single file with retry logic.

    Args:
        service: Google Drive service
        creds: Google credentials
        file_id: File ID to process
        file_name: Name of the file
        folder_id: Google Drive folder ID (for searching matching audio/video files)
        file_url: URL of the file
        album_id: Optional album ID to upload to
        max_retries: Maximum number of retry attempts (default: MAX_RETRIES)
        retry_wait_seconds: Seconds to wait between retries (default: RETRY_WAIT_SECONDS)
        min_bytes: Minimum file size in bytes (default: MIN_FILE_SIZE_BYTES)

    Returns (success: bool, error_message: str or None, additional_files: list of (file_id, file_url) tuples)
    """
    local_file = None
    converted_file = None
    combined_file = None
    audio_file = None
    video_file = None
    last_error = None

    # Track additional files (for audio+video pairs)
    additional_files = []

    file_ext = os.path.splitext(file_name.lower())[1]
    is_audio_file = file_ext in AUDIO_EXTENSIONS

    for attempt in range(1, max_retries + 1):
        try:
            # SPECIAL HANDLING FOR AUDIO FILES
            if is_audio_file:
                logger.info(f"  Audio file detected: {file_name}")
                logger.info(f"  Looking for matching video file...")

                # Get the actual parent folder ID of this file (not the root folder ID)
                # This handles cases where files are in subfolders
                file_metadata = service.files().get(fileId=file_id, fields='parents').execute()
                actual_folder_id = file_metadata.get('parents', [folder_id])[0]
                logger.info(f"  File's parent folder ID: {actual_folder_id}")

                # Find matching video file in the same folder
                video_match = find_matching_video_file(service, actual_folder_id, file_name)

                if not video_match:
                    logger.warning(f"  ✗ No matching video file found - skipping audio file")
                    return False, f"SKIP: Audio file without matching video", []

                video_file_id, video_file_name, video_file_url = video_match
                logger.info(f"  ✓ Found matching video: {video_file_name}")

                # Download both audio and video
                logger.info(f"  Downloading audio file: {file_name}...")
                audio_file = download_from_drive(service, file_id, file_name)
                audio_size_bytes = os.path.getsize(audio_file)
                audio_size = audio_size_bytes / (1024 * 1024)
                logger.info(f"  Downloaded audio: {audio_size:.1f}MB")

                logger.info(f"  Downloading video file: {video_file_name}...")
                video_file = download_from_drive(service, video_file_id, video_file_name)
                video_size_bytes = os.path.getsize(video_file)
                video_size = video_size_bytes / (1024 * 1024)
                logger.info(f"  Downloaded video: {video_size:.1f}MB")

                # Check if video needs to be skipped (too small)
                if video_size_bytes < min_bytes:
                    logger.warning(f"  Video file is too small ({video_size_bytes} bytes, minimum: {min_bytes} bytes)")
                    logger.warning(f"  Skipping BOTH audio and video files")
                    # Cleanup
                    if audio_file and os.path.exists(audio_file):
                        os.remove(audio_file)
                    if video_file and os.path.exists(video_file):
                        os.remove(video_file)
                    # Return skip for both files
                    additional_files = [(video_file_id, video_file_url)]
                    return False, f"SKIP: Video file too small ({video_size_bytes} bytes, minimum: {min_bytes} bytes)", additional_files

                # Check if audio needs to be skipped (too small)
                if audio_size_bytes < min_bytes:
                    logger.warning(f"  Audio file is too small ({audio_size_bytes} bytes, minimum: {min_bytes} bytes)")
                    logger.warning(f"  Skipping audio file only")
                    # Cleanup audio
                    if audio_file and os.path.exists(audio_file):
                        os.remove(audio_file)
                    # Continue processing video only - don't return yet
                    # Set audio_file to None so we don't try to combine
                    audio_file = None
                    local_file = video_file
                    file_name = video_file_name  # Use video name for the rest of processing
                    # Track the video file as additional so it's not processed again
                    additional_files = [(video_file_id, video_file_url)]
                    logger.info(f"  Will process video file normally without audio")
                else:
                    # Both files are valid size - check if video has audio
                    logger.info(f"  Checking if video already has audio stream...")
                    if video_has_audio_stream(video_file):
                        logger.info(f"  Video already has audio stream")
                        logger.warning(f"  Skipping audio file (video already has audio)")
                        # Cleanup audio
                        if audio_file and os.path.exists(audio_file):
                            os.remove(audio_file)
                        # Process video only
                        audio_file = None
                        local_file = video_file
                        file_name = video_file_name
                        # Track the video file as additional so it's not processed again
                        additional_files = [(video_file_id, video_file_url)]
                        logger.info(f"  Will process video file normally")
                    else:
                        # Video doesn't have audio - combine them
                        logger.info(f"  Video has no audio stream - will combine with audio file")
                        base_name = os.path.splitext(video_file)[0]
                        combined_file = f"{base_name}_combined.mp4"
                        combine_video_and_audio(video_file, audio_file, combined_file)

                        # Use combined file for upload
                        local_file = combined_file
                        file_name = video_file_name  # Use video name for upload
                        logger.info(f"  ✓ Will upload combined video+audio file")

                        # Track the video file as additional
                        additional_files = [(video_file_id, video_file_url)]

            else:
                # NORMAL HANDLING FOR VIDEO/IMAGE FILES
                # Download
                local_file = download_from_drive(service, file_id, file_name)
                download_size_bytes = os.path.getsize(local_file)
                download_size = download_size_bytes / (1024 * 1024)
                logger.info(f"  Downloaded: {download_size:.1f}MB")

                # Validate file size - skip files below minimum threshold
                if download_size_bytes < min_bytes:
                    logger.warning(f"  File is too small ({download_size_bytes} bytes, minimum: {min_bytes} bytes) - skipping")
                    # Cleanup and return skip indicator
                    if local_file and os.path.exists(local_file):
                        os.remove(local_file)
                    return False, f"SKIP: File too small ({download_size_bytes} bytes, minimum: {min_bytes} bytes)", []

            # Check for video files without audio and combine with separate audio if found
            # (This is the old logic for when we encounter video files first)
            file_ext_check = os.path.splitext(file_name.lower())[1]
            if file_ext_check in ['.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm'] and not is_audio_file:
                logger.info(f"  Video file detected: {file_name}")
                logger.info(f"  Checking for audio stream in video file...")
                if not video_has_audio_stream(local_file):
                    logger.warning(f"  Video file has no audio stream - attempting to find separate audio file")
                    # Search for matching audio file
                    audio_match = find_matching_audio_file(service, folder_id, file_name)
                    if audio_match:
                        audio_file_id, audio_file_name = audio_match
                        try:
                            # Download the audio file
                            logger.info(f"  Downloading matching audio file: {audio_file_name}...")
                            audio_file = download_from_drive(service, audio_file_id, audio_file_name)
                            audio_size = os.path.getsize(audio_file) / (1024 * 1024)
                            logger.info(f"  Downloaded audio file: {audio_size:.1f}MB")

                            # Combine video and audio
                            base_name = os.path.splitext(local_file)[0]
                            combined_file = f"{base_name}_combined.mp4"
                            combine_video_and_audio(local_file, audio_file, combined_file)

                            # Use combined file for further processing
                            old_file = local_file
                            local_file = combined_file
                            logger.info(f"  ✓ Will upload combined video+audio file instead of original video")
                        except Exception as audio_error:
                            logger.warning(f"  ✗ Failed to combine video+audio: {audio_error}")
                            logger.warning(f"  Will upload original video without audio")
                    else:
                        logger.warning(f"  ✗ No matching audio file found in folder")
                        logger.warning(f"  Will upload video without audio")
                else:
                    logger.info(f"  Video already has audio stream - no combination needed")

            # Convert if needed
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
                    file_to_upload = local_file

            # Upload
            logger.info(f"  Uploading to Google Photos...")
            upload_to_photos(creds, file_to_upload, file_name, album_id)

            # Success - cleanup
            if local_file and os.path.exists(local_file):
                os.remove(local_file)
            if converted_file and os.path.exists(converted_file) and converted_file != local_file:
                os.remove(converted_file)
            if audio_file and os.path.exists(audio_file):
                os.remove(audio_file)
            if video_file and os.path.exists(video_file):
                os.remove(video_file)
            if combined_file and os.path.exists(combined_file) and combined_file != local_file:
                os.remove(combined_file)
            return True, None, additional_files

        except Exception as e:
            last_error = str(e)
            logger.exception(f"  Attempt {attempt}/{max_retries} failed: {last_error}")

            # Check if this is a Google Photos API error code 3 (corrupted/empty/unsupported file)
            # These files should be skipped, not retried
            if "code=3" in last_error or "Media item creation failed: code=3" in last_error:
                logger.warning(f"  Google Photos API error code 3: File corrupted/empty/unsupported format")
                logger.warning(f"  Skipping file '{file_name}' - will not retry (error code 3 is permanent)")
                # Cleanup files
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
                if audio_file and os.path.exists(audio_file):
                    try:
                        os.remove(audio_file)
                    except:
                        pass
                if video_file and os.path.exists(video_file):
                    try:
                        os.remove(video_file)
                    except:
                        pass
                if combined_file and os.path.exists(combined_file) and combined_file != local_file:
                    try:
                        os.remove(combined_file)
                    except:
                        pass
                # Return SKIP status
                return False, f"SKIP: Google Photos rejected file (error code 3: corrupted/empty/unsupported format)", additional_files

            # Cleanup
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
            if audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except:
                    pass
            if video_file and os.path.exists(video_file):
                try:
                    os.remove(video_file)
                except:
                    pass
            if combined_file and os.path.exists(combined_file) and combined_file != local_file:
                try:
                    os.remove(combined_file)
                except:
                    pass

            # Wait before retry
            if attempt < max_retries:
                logger.info(f"  Waiting {retry_wait_seconds} seconds before retry...")
                time.sleep(retry_wait_seconds)
            else:
                logger.exception(f"  All {max_retries} attempts failed")

    return False, last_error, additional_files


# ============================================================================
# MODE HANDLER FUNCTIONS
# ============================================================================

def plan_folder(service, root_folder_id, current_folder_id, planned_count=None):
    """
    Scan folder recursively and save all image/video/audio files to planned_files.txt.

    Args:
        service: Google Drive service
        root_folder_id: The root folder ID (used for file naming)
        current_folder_id: The current folder being scanned
        planned_count: Dictionary tracking file counts

    Returns the total count of files found.
    """
    if planned_count is None:
        planned_count = {'images': 0, 'videos': 0, 'audio': 0, 'other': 0}

    query = f"'{current_folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name, mimeType, webViewLink)").execute()
    items = results.get('files', [])

    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            plan_folder(service, root_folder_id, item['id'], planned_count)
        else:
            # Check file extension to handle cases where MIME type is ambiguous
            file_ext = os.path.splitext(item['name'].lower())[1]

            file_id = item['id']
            file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")

            # Skip disk image files (they might have MIME types containing "image" but aren't photos)
            if file_ext in DISK_IMAGE_EXTENSIONS:
                planned_count['other'] += 1
                logger.debug(f"Skipping disk image: {item['name']} (type: {item['mimeType']})")
            # Prioritize file extension over MIME type for audio files
            # (because .m4a files often have video/mp4 MIME type)
            elif file_ext in AUDIO_EXTENSIONS:
                save_planned_file(root_folder_id, file_id, file_url, item['name'], item['mimeType'])
                planned_count['audio'] += 1
                logger.info(f"Found audio: {item['name']}")
            elif 'image' in item['mimeType']:
                save_planned_file(root_folder_id, file_id, file_url, item['name'], item['mimeType'])
                planned_count['images'] += 1
                logger.info(f"Found image: {item['name']}")
            elif file_ext in VIDEO_EXTENSIONS or 'video' in item['mimeType']:
                save_planned_file(root_folder_id, file_id, file_url, item['name'], item['mimeType'])
                planned_count['videos'] += 1
                logger.info(f"Found video: {item['name']}")
            elif 'audio' in item['mimeType']:
                save_planned_file(root_folder_id, file_id, file_url, item['name'], item['mimeType'])
                planned_count['audio'] += 1
                logger.info(f"Found audio: {item['name']}")
            else:
                planned_count['other'] += 1
                logger.debug(f"Skipping (not image/video/audio): {item['name']} (type: {item['mimeType']})")

    return planned_count


def process_from_plan(service, creds, folder_id, planned_files, album_id, processed_files, failed_files, max_retries=MAX_RETRIES, retry_wait_seconds=RETRY_WAIT_SECONDS, min_bytes=MIN_FILE_SIZE_BYTES):
    """Process files from the planned_files list."""
    total_files = len(planned_files)
    processed_count = 0
    failed_count = 0
    skipped_count = 0

    logger.info(f"Processing {total_files} files from plan...")

    for idx, (file_id, file_url, file_name, mime_type) in enumerate(planned_files, 1):
        if file_id in processed_files:
            logger.info(f"[{idx}/{total_files}] Skipping (already processed): {file_name}")
            skipped_count += 1
            continue

        if file_id in failed_files:
            logger.warning(f"[{idx}/{total_files}] Skipping (previously failed): {file_name}")
            skipped_count += 1
            continue

        logger.info(f"[{idx}/{total_files}] Processing: {file_name}...")
        success, error_msg, additional_files = process_single_file_with_retry(
            service, creds, file_id, file_name, folder_id, file_url, album_id, max_retries, retry_wait_seconds, min_bytes
        )

        if success:
            save_processed_file(folder_id, file_id, file_url)
            processed_files.add(file_id)
            processed_count += 1
            # Also save additional files (e.g., the video file when processing audio)
            for add_file_id, add_file_url in additional_files:
                save_processed_file(folder_id, add_file_id, add_file_url)
                processed_files.add(add_file_id)
                logger.info(f"  Also marked as processed: {add_file_id}")
            logger.success(f"[{idx}/{total_files}] Done: {file_name}")
        elif error_msg and error_msg.startswith("SKIP:"):
            # File should be skipped (e.g., zero bytes)
            skip_reason = error_msg[5:].strip()  # Remove "SKIP:" prefix
            save_skipped_file(folder_id, file_id, file_url, mime_type, skip_reason)
            skipped_count += 1
            # Also skip additional files
            for add_file_id, add_file_url in additional_files:
                save_skipped_file(folder_id, add_file_id, add_file_url, mime_type, skip_reason)
                logger.info(f"  Also marked as skipped: {add_file_id}")
            logger.warning(f"[{idx}/{total_files}] Skipped: {file_name} - {skip_reason}")
        else:
            save_failed_file(folder_id, file_id, file_url, file_name, error_msg)
            failed_files.add(file_id)
            failed_count += 1
            # Also fail additional files
            for add_file_id, add_file_url in additional_files:
                save_failed_file(folder_id, add_file_id, add_file_url, file_name, error_msg)
                failed_files.add(add_file_id)
                logger.info(f"  Also marked as failed: {add_file_id}")
            logger.error(f"[{idx}/{total_files}] Failed permanently: {file_name}")

    return processed_count, failed_count, skipped_count


def retry_failed_files(service, creds, folder_id, album_id, processed_files, max_retries=MAX_RETRIES, retry_wait_seconds=RETRY_WAIT_SECONDS, min_bytes=MIN_FILE_SIZE_BYTES):
    """Retry processing files from the failed files log."""
    failed_files_list = load_failed_files_detailed(folder_id)

    if not failed_files_list:
        logger.warning("No failed files to retry")
        return 0, 0

    total_files = len(failed_files_list)
    success_count = 0
    still_failed_count = 0

    logger.info(f"Retrying {total_files} failed files...")

    for idx, (file_id, file_url, file_name, old_error) in enumerate(failed_files_list, 1):
        # Fetch filename if unknown (old format)
        if file_name.startswith('unknown_'):
            try:
                file_metadata = service.files().get(fileId=file_id, fields='name').execute()
                file_name = file_metadata.get('name', file_name)
                logger.debug(f"Fetched filename from Drive: {file_name}")
            except Exception as e:
                logger.warning(f"Could not fetch filename for {file_id}: {e}")

        # Check if already processed
        if file_id in processed_files:
            logger.info(f"[{idx}/{total_files}] Skipping (already processed): {file_name}")
            remove_from_failed_files(folder_id, file_id)
            success_count += 1
            continue

        # Check if file should be skipped based on extension (e.g., disk images)
        file_ext = os.path.splitext(file_name.lower())[1]

        if file_ext in DISK_IMAGE_EXTENSIONS:
            logger.info(f"[{idx}/{total_files}] Skipping disk image: {file_name}")
            # Move from failed to skipped
            try:
                file_metadata = service.files().get(fileId=file_id, fields='mimeType').execute()
                mime_type = file_metadata.get('mimeType', 'unknown')
            except:
                mime_type = 'unknown'
            save_skipped_file(folder_id, file_id, file_url, mime_type, "Disk image file")
            remove_from_failed_files(folder_id, file_id)
            continue

        logger.info(f"[{idx}/{total_files}] Retrying: {file_name}")
        logger.info(f"  Previous error: {old_error}")

        success, error_msg, additional_files = process_single_file_with_retry(
            service, creds, file_id, file_name, folder_id, file_url, album_id, max_retries, retry_wait_seconds, min_bytes
        )

        if success:
            save_processed_file(folder_id, file_id, file_url)
            remove_from_failed_files(folder_id, file_id)
            processed_files.add(file_id)
            success_count += 1
            # Also process additional files
            for add_file_id, add_file_url in additional_files:
                save_processed_file(folder_id, add_file_id, add_file_url)
                remove_from_failed_files(folder_id, add_file_id)
                processed_files.add(add_file_id)
                logger.info(f"  Also marked as processed: {add_file_id}")
            logger.success(f"[{idx}/{total_files}] Success on retry: {file_name}")
        elif error_msg and error_msg.startswith("SKIP:"):
            # File should be skipped (e.g., zero bytes)
            skip_reason = error_msg[5:].strip()  # Remove "SKIP:" prefix
            # Try to fetch mime type from Drive
            try:
                file_metadata = service.files().get(fileId=file_id, fields='mimeType').execute()
                mime_type = file_metadata.get('mimeType', 'unknown')
            except:
                mime_type = 'unknown'
            save_skipped_file(folder_id, file_id, file_url, mime_type, skip_reason)
            remove_from_failed_files(folder_id, file_id)
            success_count += 1
            # Also skip additional files
            for add_file_id, add_file_url in additional_files:
                save_skipped_file(folder_id, add_file_id, add_file_url, mime_type, skip_reason)
                remove_from_failed_files(folder_id, add_file_id)
                logger.info(f"  Also marked as skipped: {add_file_id}")
            logger.warning(f"[{idx}/{total_files}] Skipped: {file_name} - {skip_reason}")
        else:
            remove_from_failed_files(folder_id, file_id)
            save_failed_file(folder_id, file_id, file_url, file_name, error_msg)
            still_failed_count += 1
            # Also fail additional files
            for add_file_id, add_file_url in additional_files:
                remove_from_failed_files(folder_id, add_file_id)
                save_failed_file(folder_id, add_file_id, add_file_url, file_name, error_msg)
                logger.info(f"  Also marked as failed: {add_file_id}")
            logger.error(f"[{idx}/{total_files}] Still failing: {file_name}")

    return success_count, still_failed_count


def process_folder(service, creds, root_folder_id, current_folder_id, album_id=None, processed_files=None, failed_files=None, skipped_files=None, max_retries=MAX_RETRIES, retry_wait_seconds=RETRY_WAIT_SECONDS, min_bytes=MIN_FILE_SIZE_BYTES):
    """Process all files in a folder recursively (legacy mode)."""
    if processed_files is None:
        processed_files = set()
    if failed_files is None:
        failed_files = set()
    if skipped_files is None:
        skipped_files = set()

    query = f"'{current_folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name, mimeType, webViewLink)").execute()
    items = results.get('files', [])

    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            process_folder(service, creds, root_folder_id, item['id'], album_id, processed_files, failed_files, skipped_files, max_retries, retry_wait_seconds, min_bytes)
        else:
            # Check file extension to identify audio/video files correctly
            file_ext = os.path.splitext(item['name'].lower())[1]

            # Exclude disk images even if MIME type contains "image"
            if file_ext in DISK_IMAGE_EXTENSIONS:
                is_media_file = False
            else:
                is_media_file = (
                    'image' in item['mimeType'] or
                    'video' in item['mimeType'] or
                    'audio' in item['mimeType'] or
                    file_ext in AUDIO_EXTENSIONS or
                    file_ext in VIDEO_EXTENSIONS
                )

            if is_media_file:
                file_id = item['id']
                file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")

                if file_id in processed_files:
                    logger.info(f"Skipping (already processed): {item['name']}")
                    continue

                if file_id in failed_files:
                    logger.warning(f"Skipping (previously failed): {item['name']}")
                    continue

                logger.info(f"Processing: {item['name']}...")
                success, error_msg, additional_files = process_single_file_with_retry(
                    service, creds, file_id, item['name'], root_folder_id, file_url, album_id, max_retries, retry_wait_seconds, min_bytes
                )

                if success:
                    save_processed_file(root_folder_id, file_id, file_url)
                    processed_files.add(file_id)
                    # Also process additional files
                    for add_file_id, add_file_url in additional_files:
                        save_processed_file(root_folder_id, add_file_id, add_file_url)
                        processed_files.add(add_file_id)
                        logger.info(f"  Also marked as processed: {add_file_id}")
                    logger.success(f"Done: {item['name']}")
                elif error_msg and error_msg.startswith("SKIP:"):
                    # File should be skipped (e.g., zero bytes)
                    skip_reason = error_msg[5:].strip()  # Remove "SKIP:" prefix
                    save_skipped_file(root_folder_id, file_id, file_url, item['mimeType'], skip_reason)
                    skipped_files.add(file_id)
                    # Also skip additional files
                    for add_file_id, add_file_url in additional_files:
                        save_skipped_file(root_folder_id, add_file_id, add_file_url, item['mimeType'], skip_reason)
                        skipped_files.add(add_file_id)
                        logger.info(f"  Also marked as skipped: {add_file_id}")
                    logger.warning(f"Skipped: {item['name']} - {skip_reason}")
                else:
                    save_failed_file(root_folder_id, file_id, file_url, item['name'], error_msg)
                    failed_files.add(file_id)
                    # Also fail additional files
                    for add_file_id, add_file_url in additional_files:
                        save_failed_file(root_folder_id, add_file_id, add_file_url, item['name'], error_msg)
                        failed_files.add(add_file_id)
                        logger.info(f"  Also marked as failed: {add_file_id}")
                    logger.error(f"Failed permanently: {item['name']}")
            else:
                file_id = item['id']
                file_url = item.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")

                if file_id not in skipped_files:
                    save_skipped_file(root_folder_id, file_id, file_url, item['mimeType'])
                    skipped_files.add(file_id)
                    logger.info(f"Skipping (not image/video/audio): {item['name']} (type: {item['mimeType']})")


# ============================================================================
# MODE EXECUTION FUNCTIONS (Extracted from main)
# ============================================================================

def run_retry_mode(args):
    """Execute retry mode."""
    if not args.folder:
        logger.error("Folder argument is required for --retry mode")
        logger.error(f"Example: python {sys.argv[0]} FOLDER_ID --retry")
        sys.exit(1)

    folder_id = extract_folder_id(args.folder)
    logger.info(f"Using folder ID: {folder_id}")

    # Set up file logging
    log_filename = setup_file_logging(folder_id)
    logger.info(f"Logging to: {log_filename}")

    failed_log = get_failed_files_log(folder_id)
    if not os.path.exists(failed_log):
        logger.warning(f"Failed files log not found: {failed_log}")
        logger.info("No failed files to retry")
        return

    logger.info("Running in RETRY mode - retrying failed files...")
    logger.info(f"Retry configuration: {args.retry_on_error} attempts, {args.wait_on_error} seconds wait, {args.min_bytes} bytes minimum")

    failed_files_list = load_failed_files_detailed(folder_id)
    if not failed_files_list:
        logger.info("No failed files to retry")
        return

    logger.info(f"Found {len(failed_files_list)} failed files to retry")

    processed_files = load_processed_files(folder_id)
    logger.info(f"Loaded {len(processed_files)} previously processed files")

    drive_service, creds = get_services()

    album_name = args.album if args.album else DEFAULT_ALBUM_NAME
    logger.info(f"Using album name: {album_name}")

    album_id = get_or_create_album(creds, album_name)

    success_count, still_failed_count = retry_failed_files(
        drive_service, creds, folder_id, album_id, processed_files, args.retry_on_error, args.wait_on_error, args.min_bytes
    )

    logger.info("Retry complete!")
    logger.info(f"Successfully processed on retry: {success_count} files")
    logger.info(f"Still failing: {still_failed_count} files")


def run_execute_mode(args):
    """Execute execute mode."""
    if not args.folder:
        logger.error("Folder argument is required for --execute mode")
        logger.error(f"Example: python {sys.argv[0]} FOLDER_ID --execute")
        sys.exit(1)

    folder_id = extract_folder_id(args.folder)
    logger.info(f"Using folder ID: {folder_id}")

    # Set up file logging
    log_filename = setup_file_logging(folder_id)
    logger.info(f"Logging to: {log_filename}")

    planned_log = get_planned_files_log(folder_id)
    if not os.path.exists(planned_log):
        logger.error(f"Plan file not found: {planned_log}")
        logger.error("Please run with --plan first to scan and create the plan file")
        logger.error(f"Example: python {sys.argv[0]} FOLDER_ID --plan")
        sys.exit(1)

    logger.info("Running in EXECUTE mode - processing files from plan...")
    logger.info(f"Retry configuration: {args.retry_on_error} attempts, {args.wait_on_error} seconds wait, {args.min_bytes} bytes minimum")

    planned_files = load_planned_files(folder_id)
    if not planned_files:
        logger.error("Plan file is empty or invalid")
        sys.exit(1)

    logger.info(f"Loaded {len(planned_files)} files from plan")

    processed_files = load_processed_files(folder_id)
    failed_files = load_failed_files(folder_id)
    logger.info(f"Loaded {len(processed_files)} previously processed files")
    logger.info(f"Loaded {len(failed_files)} previously failed files")

    drive_service, creds = get_services()

    album_name = args.album if args.album else DEFAULT_ALBUM_NAME
    logger.info(f"Using album name: {album_name}")

    album_id = get_or_create_album(creds, album_name)

    processed_count, failed_count, skipped_count = process_from_plan(
        drive_service, creds, folder_id, planned_files, album_id, processed_files, failed_files, args.retry_on_error, args.wait_on_error, args.min_bytes
    )

    logger.info("Execution complete!")
    logger.info(f"Successfully processed: {processed_count} files")
    logger.info(f"Failed: {failed_count} files")
    logger.info(f"Skipped (already processed/failed): {skipped_count} files")


def run_plan_mode(args):
    """Execute plan mode."""
    if not args.folder:
        logger.error("Folder argument is required for --plan mode")
        logger.error(f"Example: python {sys.argv[0]} FOLDER_ID --plan")
        sys.exit(1)

    folder_id = extract_folder_id(args.folder)
    logger.info(f"Using folder ID: {folder_id}")

    # Set up file logging
    log_filename = setup_file_logging(folder_id)
    logger.info(f"Logging to: {log_filename}")

    drive_service, creds = get_services()

    folder_name = get_folder_name(drive_service, folder_id)
    logger.info(f"Folder name: {folder_name}")

    logger.info("Running in PLAN mode - scanning folder structure...")

    planned_log = get_planned_files_log(folder_id)
    if os.path.exists(planned_log):
        os.remove(planned_log)
        logger.info(f"Cleared previous plan file: {planned_log}")

    counts = plan_folder(drive_service, folder_id, folder_id)

    logger.info("Planning complete!")
    logger.info(f"Found {counts['images']} image files")
    logger.info(f"Found {counts['videos']} video files")
    logger.info(f"Found {counts['audio']} audio files")
    logger.info(f"Found {counts['other']} other files (skipped)")
    logger.info(f"Plan saved to: {planned_log}")


def run_combined_mode(args):
    """Execute combined mode (plan + execute)."""
    if not args.folder:
        logger.error("Folder argument is required")
        logger.error(f"Example: python {sys.argv[0]} FOLDER_ID")
        sys.exit(1)

    folder_id = extract_folder_id(args.folder)
    logger.info(f"Using folder ID: {folder_id}")

    # Set up file logging
    log_filename = setup_file_logging(folder_id)
    logger.info(f"Logging to: {log_filename}")

    drive_service, creds = get_services()

    folder_name = get_folder_name(drive_service, folder_id)
    logger.info(f"Folder name: {folder_name}")

    logger.info("Running in COMBINED mode (plan + execute)...")
    logger.info(f"Retry configuration: {args.retry_on_error} attempts, {args.wait_on_error} seconds wait, {args.min_bytes} bytes minimum")
    logger.info("")
    logger.info(SEPARATOR_LINE)
    logger.info("STEP 1/2: PLANNING - Scanning folder structure...")
    logger.info(SEPARATOR_LINE)
    logger.info("")

    planned_log = get_planned_files_log(folder_id)
    if os.path.exists(planned_log):
        os.remove(planned_log)
        logger.info(f"Cleared previous plan file: {planned_log}")

    counts = plan_folder(drive_service, folder_id, folder_id)

    logger.info("")
    logger.info("Planning complete!")
    logger.info(f"Found {counts['images']} image files")
    logger.info(f"Found {counts['videos']} video files")
    logger.info(f"Found {counts['audio']} audio files")
    logger.info(f"Found {counts['other']} other files (skipped)")
    logger.info(f"Plan saved to: {planned_log}")

    logger.info("")
    logger.info(SEPARATOR_LINE)
    logger.info("STEP 2/2: EXECUTING - Processing files from plan...")
    logger.info(SEPARATOR_LINE)
    logger.info("")

    planned_files = load_planned_files(folder_id)
    if not planned_files:
        logger.error("Failed to load planned files")
        sys.exit(1)

    logger.info(f"Loaded {len(planned_files)} files from plan")

    processed_files = load_processed_files(folder_id)
    failed_files = load_failed_files(folder_id)
    logger.info(f"Loaded {len(processed_files)} previously processed files")
    logger.info(f"Loaded {len(failed_files)} previously failed files")

    album_name = args.album if args.album else folder_name
    logger.info(f"Using album name: {album_name}")

    album_id = get_or_create_album(creds, album_name)

    processed_count, failed_count, skipped_count = process_from_plan(
        drive_service, creds, folder_id, planned_files, album_id, processed_files, failed_files, args.retry_on_error, args.wait_on_error, args.min_bytes
    )

    logger.info("")
    logger.info(SEPARATOR_LINE)
    logger.info("ALL STEPS COMPLETE!")
    logger.info(SEPARATOR_LINE)
    logger.info(f"Successfully processed: {processed_count} files")
    logger.info(f"Failed: {failed_count} files")
    logger.info(f"Skipped (already processed/failed): {skipped_count} files")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Download photos/videos from Google Drive and upload to Google Photos',
        epilog='Default behavior (no flags): Run plan + execute sequentially')
    parser.add_argument('folder', nargs='?', help='Google Drive folder URL or folder ID')
    parser.add_argument('--plan', action='store_true',
                      help='PLAN ONLY: Scan folder and save list of files to planned_files.txt without processing')
    parser.add_argument('--execute', action='store_true',
                      help='EXECUTE ONLY: Process files from planned_files.txt (must run --plan first)')
    parser.add_argument('--retry', action='store_true',
                      help='RETRY ONLY: Retry processing files from failed_files.txt')
    parser.add_argument('--album', type=str, default=None,
                      help='Album name for Google Photos (default: FOTO for --execute, folder name for other modes)')
    parser.add_argument('--retry_on_error', type=int, default=3,
                      help='Number of retry attempts when processing a file fails (default: 3)')
    parser.add_argument('--wait_on_error', type=int, default=30,
                      help='Number of seconds to wait between retry attempts (default: 30)')
    parser.add_argument('--min_bytes', type=int, default=16384,
                      help='Minimum file size in bytes - files smaller will be skipped (default: 16384 = 16 KB)')
    args = parser.parse_args()

    logger.info("Fotointegrator started")

    # Route to appropriate mode handler
    if args.retry:
        run_retry_mode(args)
    elif args.execute:
        run_execute_mode(args)
    elif args.plan:
        run_plan_mode(args)
    else:
        run_combined_mode(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.exception(f"Fatal error in main execution: {e}")
        sys.exit(1)
