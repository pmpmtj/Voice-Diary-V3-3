"""
File utilities package for Voice Diary.

This package provides utilities for managing files, including moving files
based on their extension types. Extensions are fetched from the principal
config file with fallback to local config.
"""

from .mv_files import (
    load_config, 
    process_files, 
    main, 
    get_extensions_from_gdrive_config, 
    merge_config_with_gdrive_extensions
)

__all__ = [
    'load_config', 
    'process_files', 
    'main', 
    'get_extensions_from_gdrive_config', 
    'merge_config_with_gdrive_extensions'
]
