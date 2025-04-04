import os
import io
import pickle
import sys
import logging
from logging.handlers import RotatingFileHandler
import json

from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any, Union
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import time
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError

# Initialize paths
SCRIPT_DIR = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent.resolve()
CONFIG_DIR = SCRIPT_DIR / "config_dwnload_files"
CONFIG_FILE = CONFIG_DIR / "config_dwnld_from_gdrive.json"
CREDENTIALS_DIR = SCRIPT_DIR / "gdrive_credentials"

# Ensure directories exist
CREDENTIALS_DIR.mkdir(exist_ok=True)

# Load configuration
try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
    # Add paths section if missing
    if 'downloads_path' not in CONFIG:
        CONFIG['downloads_path'] = {}
    
    # Handle downloads directory: use config path or default to script_dir/downloads
    downloads_path = CONFIG['downloads_path'].get('downloads_dir', 'downloads')
    if os.path.isabs(downloads_path):
        # If it's an absolute path, use it directly
        DOWNLOADS_DIR = Path(downloads_path)
    else:
        # If it's a relative path, make it relative to the script directory
        DOWNLOADS_DIR = SCRIPT_DIR / downloads_path
        
    # Update the config with the resolved path
    CONFIG['downloads_path']['downloads_dir'] = str(DOWNLOADS_DIR)
    
    # Create downloads directory if it doesn't exist
    DOWNLOADS_DIR.mkdir(exist_ok=True, parents=True)
    
except FileNotFoundError:
    print(f"ERROR: Config file not found at {CONFIG_FILE}")
    sys.exit(1)
except json.JSONDecodeError:
    print(f"ERROR: Invalid JSON in config file {CONFIG_FILE}")
    sys.exit(1)

# Set up credentials paths
CREDENTIALS_FILE = CREDENTIALS_DIR / CONFIG['auth']['credentials_file']
TOKEN_FILE = CREDENTIALS_DIR / CONFIG['auth']['token_file']

# Initialize logger
logger = logging.getLogger(__name__)

def find_folder_by_name(service, folder_name):
    """Find a folder ID by its name in Google Drive.
    
    Args:
        service: Google Drive API service instance
        folder_name: Name of the folder to find
        
    Returns:
        str: Folder ID if found, None otherwise
    """
    try:
        # Search for folders with the given name
        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        items = results.get('files', [])
        
        if not items:
            logger.warning(f"No folder named '{folder_name}' found.")
            return None
            
        # Return the ID of the first matched folder
        folder_id = items[0]['id']
        logger.info(f"Found folder '{folder_name}' with ID: {folder_id}")
        return folder_id
        
    except Exception as e:
        logger.error(f"Error finding folder '{folder_name}': {str(e)}")
        return None

# Configure logging based on config
def configure_logging():
    """Configure logging with rotation based on config settings"""
    # Check if root logger already has handlers to avoid duplicate configuration
    root_logger = logging.getLogger()
    if root_logger.handlers:
        logging.debug("Logging already configured, skipping reconfiguration") 
        return

    log_level = getattr(logging, CONFIG.get('logging', {}).get('level', 'INFO'))
    log_format = CONFIG.get('logging', {}).get('format', '%(asctime)s - %(levelname)s - %(message)s')
    log_file_name = CONFIG.get('logging', {}).get('log_file', 'dwnld_audio.log')
    max_size = CONFIG.get('logging', {}).get('max_size_bytes', 1048576)  # Default 1MB
    backup_count = CONFIG.get('logging', {}).get('backup_count', 3)
    
    # Create the logs directory inside db_utils if it doesn't exist
    # Get the directory where this script is located
    dwnld_audio_files_dir = Path(__file__).parent
    logs_dir = dwnld_audio_files_dir / 'logs'
    logs_dir.mkdir(exist_ok=True)
    
    # Full path to the log file
    log_file_path = logs_dir / log_file_name

    # Create a formatter
    formatter = logging.Formatter(log_format)

    # Create handlers
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=max_size,
        backupCount=backup_count
    )
    file_handler.setFormatter(formatter)

    # Get the root logger
    root_logger.setLevel(log_level)
    
    # Add the handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Log the location of the log file
    logging.info(f"Logging to: {log_file_path.absolute()}")

# Configure logging
configure_logging()

def check_credentials_file() -> bool:
    """Check if credentials.json exists and provide help if not."""
    if not CREDENTIALS_FILE.exists():
        logger.error(f"'{CREDENTIALS_FILE}' file not found!")
        print("\nTo create your credentials file:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project or select an existing one")
        print("3. Enable the Google Drive API:")
        print("   - Navigate to 'APIs & Services' > 'Library'")
        print("   - Search for 'Google Drive API' and enable it")
        print("4. Create OAuth credentials:")
        print("   - Go to 'APIs & Services' > 'Credentials'")
        print("   - Click 'Create Credentials' > 'OAuth client ID'")
        print("   - Select 'Desktop app' as application type")
        print("   - Download the JSON file and rename it to 'credentials.json'")
        print(f"   - Place it in the '{CREDENTIALS_DIR}' directory")
        print("\nThen run this script again.")
        return False
    return True

def authenticate_google_drive():
    """Authenticate with Google Drive API using OAuth."""
    try:
        creds = None
        
        # The token.pickle file stores the user's access and refresh tokens
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
                
        # If no valid credentials are available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not check_credentials_file():
                    sys.exit(1)
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE), CONFIG['api']['scopes'])
                creds = flow.run_local_server(port=0)
                
            # Save the credentials for the next run
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        
        # Build the service with the credentials
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise

def list_files_in_folder(service, folder_id, file_extensions=None, sort_by='createdTime'):
    """List all files in a Google Drive folder with filtering by file extension.
    
    Args:
        service: Google Drive API service instance
        folder_id: ID of the folder to list files from
        file_extensions: Optional dict with 'include' list of file extensions
        sort_by: Field to sort results by (default: 'createdTime')
        
    Returns:
        list: List of file objects sorted by the specified field
    """
    if file_extensions is None:
        file_extensions = {"include": []}
    
    query = f"'{folder_id}' in parents and trashed = false"
    
    try:
        results = service.files().list(
            q=query,
            spaces='drive',
            fields=f'files(id, name, mimeType, {sort_by})',
            orderBy=f"{sort_by}"
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            logger.info(f"No files found in folder {folder_id}.")
            return []
        
        # Filter files by extension if extension lists are provided
        include_extensions = file_extensions.get("include", [])
        
        filtered_files = []
        for file in files:
            # Skip folders
            if file.get('mimeType') == 'application/vnd.google-apps.folder':
                continue
                
            filename = file['name']
            file_ext = os.path.splitext(filename)[1].lower()
            
            # Only include files with specified extensions
            if include_extensions and file_ext not in include_extensions:
                continue
                
            filtered_files.append(file)
        
        return filtered_files
        
    except Exception as e:
        logger.error(f"Error listing files in folder {folder_id}: {str(e)}")
        return []

def download_file(service, file_id, file_name=None, download_dir=None):
    """Download a file from Google Drive by ID.
    
    Args:
        service: Google Drive service instance
        file_id: ID of the file to download OR a file object with 'id' and 'name' keys
        file_name: Name of the file to save (optional if file_id is a dict) or full path to save the file to
        download_dir: Optional directory path where to save downloaded file
    
    Returns:
        dict: A dictionary with the download result information
    """
    try:
        # If file_id is a dict (file object), extract the id and name
        if isinstance(file_id, dict):
            file_info = file_id
            file_name = file_info.get('name')
            file_id = file_info.get('id')
        
        # Determine the output path
        if os.path.isabs(file_name) or '/' in file_name or '\\' in file_name:
            # file_name is already a full path
            output_path = Path(file_name)
            # Ensure parent directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Extract just the filename for logging
            display_name = output_path.name
        else:
            # file_name is just a filename, use download_dir
            if download_dir:
                download_dir_path = Path(download_dir)
            else:
                download_dir_path = Path(CONFIG['paths']['downloads'])
            
            download_dir_path.mkdir(exist_ok=True, parents=True)
            
            # Generate filename with timestamp if configured
            if CONFIG.get('download', {}).get('add_timestamps', False):
                timestamp_format = CONFIG.get('download', {}).get('timestamp_format', '%Y%m%d_%H%M%S_%f')
                output_filename = generate_filename_with_timestamp(file_name, timestamp_format)
            else:
                output_filename = file_name
                
            # Create the full file path
            output_path = download_dir_path / output_filename
            display_name = file_name
            
        logger.info(f"Downloading {display_name} as {output_path}")
        
        # Create a file handler
        with open(output_path, 'wb') as f:
            # Get the file as media content
            request = service.files().get_media(fileId=file_id)
            
            # Download the file
            downloader = MediaIoBaseDownload(f, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                logger.info(f"Download {int(status.progress() * 100)}% complete.")
        
        logger.info(f"Download complete! Saved as: {output_path}")
        
        return {
            "success": True,
            "original_filename": display_name,
            "saved_as": str(output_path),
            "file_id": file_id
        }
            
    except Exception as e:
        logger.error(f"Error downloading file {file_name}: {str(e)}")
        
        return {
            "success": False,
            "original_filename": file_name,
            "file_id": file_id,
            "error": str(e)
        }

def delete_file(service, file_id, file_name=None):
    """Delete a file from Google Drive.
    
    Args:
        service: Google Drive API service instance
        file_id: ID of the file to delete OR a file object with 'id' and 'name' keys
        file_name: Name of the file (for logging purposes), optional if file_id is a dict
        
    Returns:
        bool: True if deletion was successful, False otherwise
    """
    try:
        # If file_id is a dict (file object), extract the id and name
        if isinstance(file_id, dict):
            file_name = file_id.get('name', 'Unknown file')
            file_id = file_id.get('id')
        
        # Execute the deletion
        logger.info(f"Deleting file: {file_name}")
        service.files().delete(fileId=file_id).execute()
        logger.info(f"File '{file_name}' deleted successfully.")
        return True
    except Exception as e:
        logger.error(f"Error deleting file '{file_name}': {str(e)}")
        return False


def process_folder(service, folder_id, folder_name, parent_path="", dry_run=False):
    """Process files in a Google Drive folder (non-recursively)."""
    try:
        # Get sort settings from config
        sort_by = CONFIG.get('sorting', {}).get('sort_by', 'createdTime')
        sort_order = CONFIG.get('sorting', {}).get('sort_order', 'asc')
        
        # Prepare sort order parameter (asc or desc)
        order_direction = 'asc' if sort_order.lower() == 'asc' else 'desc'
        sort_param = f"{sort_by} {order_direction}"
        
        # Only look for files (not folders) in the specified folder
        query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(
            q=query,
            fields=f"files(id, name, mimeType, size, {sort_by}, fileExtension)",
            orderBy=sort_param,
            pageSize=1000
        ).execute()
        items = results.get('files', [])
        
        if not items:
            logger.info(f"No files found in folder: {folder_name}")
            return {
                'total_files': 0,
                'processed_files': 0,
                'downloaded_files': 0,
                'skipped_files': 0,
                'error_files': 0,
                'deleted_files': 0,
                'audio_files': 0,
                'image_files': 0,
                'video_files': 0
            }
            
        logger.info(f"Found {len(items)} files in folder: {folder_name}, sorted by {sort_by} {order_direction}")
        
        # Count metrics
        stats = {
            'total_files': len(items),
            'processed_files': 0,
            'downloaded_files': 0,
            'skipped_files': 0,
            'error_files': 0,
            'deleted_files': 0,
            'audio_files': 0,
            'image_files': 0,
            'video_files': 0
        }
        
        # Setup download directory - now using base downloads directory directly
        base_download_dir = Path(CONFIG['downloads_path']['downloads_dir'])
        
        # Get enabled file types and their configurations
        dl_audio_enabled = CONFIG.get('audio_file_types', {}).get('DL_audio_file_types', True)
        dl_image_enabled = CONFIG.get('image_file_types', {}).get('DL_image_file_types', True)
        dl_video_enabled = CONFIG.get('video_file_types', {}).get('DL_video_file_types', True)
        
        audio_file_types = CONFIG.get('audio_file_types', {}).get('include', [])
        image_file_types = CONFIG.get('image_file_types', {}).get('include', [])
        video_file_types = CONFIG.get('video_file_types', {}).get('include', [])
        
        # Process each file
        for item in items:
            item_id = item['id']
            item_name = item['name']
            mime_type = item.get('mimeType', '')
            created_time = item.get(sort_by, '')
            
            stats['processed_files'] += 1
            
            # Log file with its creation date if available
            if created_time:
                logger.info(f"Processing file '{item_name}' ({sort_by}: {created_time})")
            
            # Check file extension and determine file type
            file_ext = os.path.splitext(item_name)[1].lower()
            file_type = None
            should_download = False
            
            if file_ext in audio_file_types:
                file_type = "audio"
                should_download = dl_audio_enabled
                stats['audio_files'] += 1
            elif file_ext in image_file_types:
                file_type = "image"
                should_download = dl_image_enabled
                stats['image_files'] += 1
            elif file_ext in video_file_types:
                file_type = "video"
                should_download = dl_video_enabled
                stats['video_files'] += 1
            
            # If file type is not identified or not enabled for download, skip it
            if file_type is None:
                logger.info(f"Skipping file with unsupported extension: {item_name}")
                stats['skipped_files'] += 1
                continue
                
            if not should_download:
                logger.info(f"{file_type.capitalize()} downloads disabled, skipping file: {item_name}")
                stats['skipped_files'] += 1
                continue
            
            # Generate output path - now directly in downloads folder
            if CONFIG.get('download', {}).get('add_timestamps', False):
                timestamp_format = CONFIG.get('download', {}).get('timestamp_format', '%Y%m%d_%H%M%S_%f')
                timestamped_name = generate_filename_with_timestamp(item_name, timestamp_format)
                output_path = base_download_dir / timestamped_name
            else:
                output_path = base_download_dir / item_name
            
            # In dry run mode, just log what would happen
            if dry_run:
                print(f"Would download {file_type} file: {item_name} -> {output_path}")
                if CONFIG.get('download', {}).get('delete_after_download', False):
                    print(f"Would delete file from Google Drive after download: {item_name}")
                stats['downloaded_files'] += 1
                continue
            
            # Download the file
            try:
                download_result = download_file(service, item_id, str(output_path))
                
                if download_result['success']:
                    stats['downloaded_files'] += 1
                    logger.info(f"Successfully downloaded {file_type} file: {item_name}")
                    
                    # Delete file from Google Drive if configured
                    if CONFIG.get('download', {}).get('delete_after_download', False):
                        delete_file(service, item_id, item_name)
                        stats['deleted_files'] += 1
                else:
                    stats['error_files'] += 1
            except Exception as e:
                logger.error(f"Error processing file {item_name}: {str(e)}")
                stats['error_files'] += 1
        
        # Log statistics for this folder
        logger.info(f"Folder '{folder_name}' statistics:")
        logger.info(f"  - Total files: {stats['total_files']}")
        logger.info(f"  - Processed files: {stats['processed_files']}")
        logger.info(f"  - Downloaded files: {stats['downloaded_files']}")
        logger.info(f"  - Skipped files: {stats['skipped_files']}")
        logger.info(f"  - Failed files: {stats['error_files']}")
        logger.info(f"  - Deleted files: {stats['deleted_files']}")
        logger.info(f"  - By type: Audio: {stats['audio_files']}, Image: {stats['image_files']}, Video: {stats['video_files']}")
        
        return stats
        
    except Exception as e:
        logger.exception(f"Error processing folder '{folder_name}': {str(e)}")
        return {
            'total_files': 0,
            'processed_files': 0,
            'downloaded_files': 0,
            'skipped_files': 0,
            'error_files': 1,
            'deleted_files': 0,
            'audio_files': 0,
            'image_files': 0,
            'video_files': 0
        }

def generate_filename_with_timestamp(filename: str, timestamp_format: Optional[str] = None) -> str:
    """
    Generate a filename with a timestamp prefix.
    
    Args:
        filename: The original filename
        timestamp_format: Format string for the timestamp, if None the original filename is returned
    
    Returns:
        The filename with timestamp prefix added
    """
    if not timestamp_format:
        return filename
        
    timestamp = datetime.now().strftime(timestamp_format)
    return f"{timestamp}_{filename}"

def main():
    """Main function to process Google Drive files."""
    if not check_credentials_file():
        return
    
    try:
        # Check if any file downloads are enabled
        dl_audio_enabled = CONFIG.get('audio_file_types', {}).get('DL_audio_file_types', True)
        dl_image_enabled = CONFIG.get('image_file_types', {}).get('DL_image_file_types', True)
        dl_video_enabled = CONFIG.get('video_file_types', {}).get('DL_video_file_types', True)
        
        if not (dl_audio_enabled or dl_image_enabled or dl_video_enabled):
            logger.info("All file downloads are disabled in config. Exiting without making API calls to Google Drive.")
            print("All file downloads are disabled in configuration. No files will be downloaded.")
            return
            
        # Authenticate with Google Drive
        service = authenticate_google_drive()
        if not service:
            logger.error("Failed to authenticate with Google Drive.")
            return
            
        # Get target folders from configuration
        target_folders = CONFIG['folders'].get('target_folders', ['root'])
        
        # Check if running in dry run mode
        dry_run = CONFIG.get('dry_run', False)
        if dry_run:
            logger.info("Running in DRY RUN mode - no files will be downloaded or deleted")
            print("\n=== DRY RUN MODE - NO FILES WILL BE DOWNLOADED OR DELETED ===\n")
        
        # Process each target folder
        for folder_name in target_folders:
            if folder_name.lower() == 'root':
                # Root folder has a special ID
                folder_id = 'root'
                logger.info(f"Processing root folder")
            else:
                # Find folder by name
                logger.info(f"Looking for folder: {folder_name}")
                folder_id = find_folder_by_name(service, folder_name)
                
                if not folder_id:
                    logger.warning(f"Folder '{folder_name}' not found. Skipping.")
                    continue
                
                logger.info(f"Processing folder: {folder_name} (ID: {folder_id})")
            
            # Process files in the folder
            process_folder(service, folder_id, folder_name, dry_run=dry_run)
        
        logger.info("Google Drive download process completed.")
        
    except Exception as e:
        logger.exception(f"An error occurred during the download process: {str(e)}")


if __name__ == "__main__":
    main()
