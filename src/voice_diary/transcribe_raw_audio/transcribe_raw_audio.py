#!/usr/bin/env python3
"""
OpenAI Whisper API Transcription

This script transcribes audio files using OpenAI's API:
- whisper-1 API endpoint 


It processes audio files in the downloads directory, supporting both
individual files and batch processing based on the configuration.
"""

import os
import sys
import json
import argparse
import logging
import time
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import asyncio
import concurrent.futures
import traceback
import platform
import subprocess
import logging.handlers
from openai import OpenAI



# Get the package directory path
SCRIPT_DIR = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"

# Make sure the log directory exists
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Initialize logger
def setup_logging(logs_dir, log_filename="transcribe_raw_audio.log", to_file=True, log_level=logging.INFO):
    """Set up logging with file rotation."""
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    handlers = [logging.StreamHandler()]
    
    if to_file:
        log_file = logs_dir / log_filename
        max_size = 1 * 1024 * 1024
        backup_count = 3
        
        rotating_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        handlers.append(rotating_handler)
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    
    logger = logging.getLogger()
    
    if to_file:
        logger.info(f"Logging to file: {log_file}")
        logger.info(f"Maximum log size: {max_size/1024/1024:.1f} MB")
        logger.info(f"Number of backup files: {backup_count}")
    
    return logger

# Initialize logger after function definition
logger = setup_logging(LOGS_DIR)

def get_openai_client():
    """Get an instance of the OpenAI client."""
    try:
        # Get the API key from environment variable
        api_key = os.environ.get("OPENAI_API_KEY")
        
        if not api_key:
            logger.error("OPENAI_API_KEY environment variable not set")
            logger.error("Please set the OPENAI_API_KEY environment variable with your OpenAI API key")
            sys.exit(1)
            
        # Create OpenAI client
        client = OpenAI(api_key=api_key)
        return client
        
    except Exception as e:
        logger.error(f"Error creating OpenAI client: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

def calculate_duration(file_path):
    """Calculate estimated duration of an audio file in seconds."""
    try:
        # Use ffprobe with platform-agnostic command construction
        ffprobe_cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        
        # Use subprocess.run with shell=False for better cross-platform compatibility
        result = subprocess.run(
            ffprobe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False
        )
        return float(result.stdout.strip())
    except Exception:
        # Fallback: use file size as a very rough estimate (3MB ≈ 1 minute)
        file_size = os.path.getsize(file_path)
        return (file_size / (3 * 1024 * 1024)) * 60  # Convert to seconds

def load_config():
    """Load configuration from transcribe_config.json."""
    try:
        config_path = SCRIPT_DIR / "transcribe_raw_audio_config" / "transcribe_config.json"

        if not config_path.exists():
            logger.error(f"Configuration file not found at {config_path}")
            sys.exit(1)
            
        with open(config_path, 'r') as f:
            config = json.load(f)

        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

def get_audio_files(directory):
    """Get all audio files from the specified directory."""
    directory = Path(directory)
    
    if not directory.exists():
        logger.error(f"Directory {directory} does not exist")
        return []
        
    # Common audio file extensions
    audio_extensions = ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg']
    
    # Get all files with audio extensions
    audio_files = []
    for ext in audio_extensions:
        audio_files.extend(directory.glob(f"*{ext}"))
    
    return audio_files

def transcribe_audio_file(client, file_path):
    """Transcribe a single audio file using OpenAI's Whisper API."""
    try:
        logger.info(f"Transcribing file: {file_path}")
        
        # Calculate estimated duration to log progress
        duration = calculate_duration(file_path)
        logger.info(f"Estimated duration: {duration:.2f} seconds")
        
        start_time = time.time()
        
        # Open the audio file
        with open(file_path, "rb") as audio_file:
            # Call the OpenAI API
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
        
        end_time = time.time()
        transcription_time = end_time - start_time
        
        logger.info(f"Transcription completed in {transcription_time:.2f} seconds")
        logger.info(f"Transcription speed: {duration/transcription_time:.2f}x real-time")
        
        return transcription.text
        
    except Exception as e:
        logger.error(f"Error transcribing file {file_path}: {str(e)}")
        traceback.print_exc()
        return None

def save_transcription(text, output_path, file_name):
    """Save the transcription to the output file."""
    if not text:
        logger.warning("No transcription text to save")
        return False
        
    try:
        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_path / f"{timestamp}_{file_name}"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(text)
            
        logger.info(f"Transcription saved to {output_file}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving transcription: {str(e)}")
        traceback.print_exc()
        return False

def process_audio_files(client, audio_files, output_path, output_file):
    """Process all audio files and save their transcriptions."""
    if not audio_files:
        logger.warning("No audio files found")
        return False
        
    logger.info(f"Found {len(audio_files)} audio file(s) to process")
    
    all_transcriptions = []
    
    for file_path in audio_files:
        logger.info(f"Processing {file_path}")
        
        # Transcribe the audio file
        transcription = transcribe_audio_file(client, file_path)
        
        if transcription:
            # Add file name and timestamp to the transcription
            file_name = file_path.name
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_transcription = f"File: {file_name}\nTimestamp: {timestamp}\n\n{transcription}\n\n"
            
            all_transcriptions.append(formatted_transcription)
    
    # Combine all transcriptions and save them
    if all_transcriptions:
        combined_text = "\n".join(all_transcriptions)
        save_transcription(combined_text, output_path, output_file)
        return True
    
    return False

def run_transcribe():
    """Main function to run the transcription process."""
    try:
        # Load configuration
        config = load_config()
        
        # Get downloads directory path
        downloads_dir = Path(SCRIPT_DIR) / config.get("downloads_dir", "downloads")
        
        # Get output file name
        output_file = config.get("output_file", "transcription.txt")
        
        # Get output directory (same as downloads directory)
        output_dir = Path(SCRIPT_DIR) / config.get("transcriptions_dir", "transcriptions")
        
        # Get OpenAI client
        client = get_openai_client()
        
        # Get audio files
        audio_files = get_audio_files(downloads_dir)
        
        # Process audio files
        success = process_audio_files(client, audio_files, output_dir, output_file)
        
        if success:
            logger.info("Transcription process completed successfully")
        else:
            logger.warning("Transcription process completed with warnings")
            
    except Exception as e:
        logger.error(f"Error running transcription process: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

def main():
    """Entry point for the script when run directly."""
    parser = argparse.ArgumentParser(description="Transcribe audio files using OpenAI's Whisper API")
    parser.add_argument("--config", help="Path to custom config file")
    args = parser.parse_args()
    
    run_transcribe()

if __name__ == "__main__":
    main()




