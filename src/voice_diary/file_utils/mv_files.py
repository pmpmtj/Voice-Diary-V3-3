#!/usr/bin/env python3
"""
File mover utility module.

This module provides functionality to move files from a source directory to various
target directories based on file extensions.
"""

import os
import sys
import json
import shutil
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Tuple, Set, Optional, Union

# Handle both frozen (PyInstaller) and regular Python execution
SCRIPT_DIR = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def load_config(config_path: Union[str, Path]) -> Dict:
    """
    Load configuration from JSON file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        Dictionary containing configuration settings
        
    Raises:
        FileNotFoundError: If the config file is not found
        json.JSONDecodeError: If the config file is not valid JSON
    """
    with open(config_path, 'r') as config_file:
        return json.load(config_file)


def get_extensions_from_gdrive_config() -> Dict[str, List[str]]:
    """
    Get file extensions from the principal Google Drive config file.
    
    Returns:
        Dictionary with keys 'audio', 'image', 'video' mapping to lists of extensions
    """
    extensions = {
        'audio': [],
        'image': [],
        'video': []
    }
    
    try:
        # Find the main config file relative to this module
        project_root = SCRIPT_DIR.parent
        gdrive_config_path = project_root / "dwnload_files" / "config_dwnload_files" / "config_dwnld_from_gdrive.json"
        
        if not gdrive_config_path.exists():
            return extensions
            
        with open(gdrive_config_path, 'r') as f:
            gdrive_config = json.load(f)
        
        # Extract extensions from the gdrive config
        if 'audio_file_types' in gdrive_config and 'include' in gdrive_config['audio_file_types']:
            extensions['audio'] = gdrive_config['audio_file_types']['include']
            
        if 'image_file_types' in gdrive_config and 'include' in gdrive_config['image_file_types']:
            extensions['image'] = gdrive_config['image_file_types']['include']
            
        if 'video_file_types' in gdrive_config and 'include' in gdrive_config['video_file_types']:
            extensions['video'] = gdrive_config['video_file_types']['include']
            
    except Exception as e:
        # Log error but continue with empty extensions lists
        print(f"Error loading extensions from Google Drive config: {str(e)}")
    
    return extensions


def merge_config_with_gdrive_extensions(config: Dict) -> Dict:
    """
    Merge the local config with extensions from the Google Drive config.
    
    Args:
        config: Local configuration dictionary
        
    Returns:
        Updated configuration with extensions from Google Drive config if available
    """
    # Make a deep copy of the config to avoid modifying the original
    merged_config = config.copy()
    
    # Get extensions from Google Drive config
    gdrive_extensions = get_extensions_from_gdrive_config()
    
    # Merge extensions with local config (only if gdrive extensions are available)
    if gdrive_extensions['audio'] and merged_config['audio_file_types']['enabled']:
        merged_config['audio_file_types']['extensions'] = gdrive_extensions['audio']
        
    if gdrive_extensions['image'] and merged_config['image_file_types']['enabled']:
        merged_config['image_file_types']['extensions'] = gdrive_extensions['image']
        
    if gdrive_extensions['video'] and merged_config['video_file_types']['enabled']:
        merged_config['video_file_types']['extensions'] = gdrive_extensions['video']
    
    return merged_config


def setup_logging(config: Dict) -> logging.Logger:
    """
    Configure logging based on settings in config.
    
    Args:
        config: Configuration dictionary containing logging settings
        
    Returns:
        Configured logger instance
    """
    log_config = config.get('logging', {})
    log_level = log_config.get('level', 'INFO')
    log_format = log_config.get('format', '%(asctime)s - %(levelname)s - %(message)s')
    log_file = log_config.get('log_file', 'file_utils.log')
    max_bytes = log_config.get('max_size_bytes', 1048576)
    backup_count = log_config.get('backup_count', 3)
    
    # Create logs directory if it doesn't exist
    log_dir = SCRIPT_DIR / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    log_path = log_dir / log_file
    
    logger = logging.getLogger('file_mover')
    logger.setLevel(getattr(logging, log_level))
    
    # Clear existing handlers to prevent duplicates
    logger.handlers = []
    
    # Create handler for logging to file with rotation
    file_handler = RotatingFileHandler(
        log_path, 
        maxBytes=max_bytes, 
        backupCount=backup_count
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # Create handler for logging to console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def ensure_directories_exist(directories: List[Path]) -> None:
    """
    Ensure all directories in the list exist, creating them if necessary.
    
    Args:
        directories: List of directory paths to check/create
    """
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def get_file_type(file_path: Path, config: Dict) -> Optional[str]:
    """
    Determine the type of file based on its extension.
    
    Args:
        file_path: Path to the file
        config: Configuration dictionary with file type definitions
        
    Returns:
        String indicating file type ('audio', 'image', 'video') or None if no match
    """
    extension = file_path.suffix.lower()
    
    # Check each file type category
    if config['audio_file_types']['enabled'] and extension in config['audio_file_types']['extensions']:
        return 'audio'
    elif config['image_file_types']['enabled'] and extension in config['image_file_types']['extensions']:
        return 'image'
    elif config['video_file_types']['enabled'] and extension in config['video_file_types']['extensions']:
        return 'video'
    
    return None


def move_file(file_path: Path, destination_dir: Path, logger: logging.Logger, 
              delete_source: bool = False) -> bool:
    """
    Move a file to the destination directory.
    
    Args:
        file_path: Path to the file to move
        destination_dir: Directory to move the file to
        logger: Logger instance for logging
        delete_source: Whether to delete the source file after copying
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure destination directory exists
        destination_dir.mkdir(parents=True, exist_ok=True)
        
        # Create destination path
        destination_path = destination_dir / file_path.name
        
        # Handle duplicate file names
        if destination_path.exists():
            base_name = destination_path.stem
            extension = destination_path.suffix
            counter = 1
            
            while destination_path.exists():
                new_name = f"{base_name}_{counter}{extension}"
                destination_path = destination_dir / new_name
                counter += 1
        
        # If delete_source is True, move the file; otherwise, copy it
        if delete_source:
            shutil.move(str(file_path), str(destination_path))
            logger.info(f"Moved {file_path} to {destination_path}")
        else:
            shutil.copy2(str(file_path), str(destination_path))
            logger.info(f"Copied {file_path} to {destination_path}")
        
        return True
    except Exception as e:
        logger.error(f"Error moving/copying {file_path}: {str(e)}")
        return False


def process_files(config: Dict, logger: logging.Logger) -> Tuple[int, int]:
    """
    Process files according to the configuration.
    
    Args:
        config: Configuration dictionary
        logger: Logger instance
        
    Returns:
        Tuple of (files_processed, files_failed)
    """
    # Merge config with extensions from Google Drive config
    merged_config = merge_config_with_gdrive_extensions(config)
    
    # Log the extensions being used
    logger.info(f"Using audio extensions: {merged_config['audio_file_types']['extensions']}")
    logger.info(f"Using image extensions: {merged_config['image_file_types']['extensions']}")
    logger.info(f"Using video extensions: {merged_config['video_file_types']['extensions']}")
    
    # Get source and target directories from config
    source_dir = Path(merged_config['source_directory']['source_dir'])
    audio_dir = Path(merged_config['target_directories']['audio_files_dir'])
    image_dir = Path(merged_config['target_directories']['image_files_dir'])
    video_dir = Path(merged_config['target_directories']['video_files_dir'])
    
    # Create directories if needed
    if merged_config['processing'].get('create_directories_if_not_exist', True):
        ensure_directories_exist([source_dir, audio_dir, image_dir, video_dir])
    
    # Get delete_source setting
    delete_source = merged_config['processing'].get('delete_source_after_move', False)
    
    # Track statistics
    files_processed = 0
    files_failed = 0
    
    # Process each file in the source directory
    if source_dir.exists() and source_dir.is_dir():
        for file_path in source_dir.iterdir():
            if file_path.is_file():
                file_type = get_file_type(file_path, merged_config)
                
                if file_type == 'audio':
                    success = move_file(file_path, audio_dir, logger, delete_source)
                elif file_type == 'image':
                    success = move_file(file_path, image_dir, logger, delete_source)
                elif file_type == 'video':
                    success = move_file(file_path, video_dir, logger, delete_source)
                else:
                    logger.info(f"Skipping {file_path} - not a recognized file type")
                    success = True  # Not a failure, just not processed
                
                if success and file_type is not None:
                    files_processed += 1
                elif not success:
                    files_failed += 1
    else:
        logger.error(f"Source directory {source_dir} does not exist or is not a directory")
    
    return files_processed, files_failed


def main():
    """
    Main function to execute when the script is run directly.
    """
    # Determine the config file path relative to this script
    config_path = SCRIPT_DIR / 'file_utils_config' / 'file_utils_config.json'
    
    try:
        # Load configuration
        config = load_config(config_path)
        
        # Setup logging
        logger = setup_logging(config)
        
        logger.info("Starting file processing")
        
        # Process files
        files_processed, files_failed = process_files(config, logger)
        
        logger.info(f"Completed file processing: {files_processed} files processed, {files_failed} files failed")
        
        return 0  # Success
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1  # Failure


if __name__ == "__main__":
    exit(main())
