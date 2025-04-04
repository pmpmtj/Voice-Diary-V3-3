#!/usr/bin/env python3
"""
Voice Diary - Summarize Day

This script retrieves transcriptions from the database for a specified date range
defined in the configuration file, and saves them to a text file.
"""

import json
import logging
import logging.handlers
import os
import sys
import yaml
import requests
from datetime import datetime, date
from pathlib import Path

from voice_diary.db_utils.db_manager import get_transcriptions_by_date_range

# Constants
SCRIPT_DIR = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "summarize_day_config" / "summarize_day_config.json"
OPENAI_CONFIG_PATH = SCRIPT_DIR / "summarize_day_config" / "openai_config.json"
PROMPTS_PATH = SCRIPT_DIR / "summarize_day_config" / "prompts.yaml"
LOG_DIR = SCRIPT_DIR / "log"

# Create log directory if it doesn't exist
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Initialize logger
logger = logging.getLogger("summarize_day")

def load_config():
    """Load configuration from JSON file"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        sys.exit(1)

def load_openai_config():
    """Load OpenAI configuration from JSON file"""
    try:
        with open(OPENAI_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading OpenAI configuration: {str(e)}")
        sys.exit(1)

def load_prompts():
    """Load prompt templates from YAML file"""
    try:
        with open(PROMPTS_PATH, 'r', encoding='utf-8') as f:
            prompts_data = yaml.safe_load(f)
            return prompts_data.get('prompts', {})
    except Exception as e:
        logger.error(f"Error loading prompt templates: {str(e)}")
        sys.exit(1)

def setup_logging(config):
    """Setup logging based on configuration"""
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("log_level", "INFO"))
    
    logger.setLevel(log_level)
    
    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Set up file handler with rotation
    log_file = log_config.get("summarize_day_log_file", "summarize_day.log")
    max_bytes = log_config.get("summarize_day_max_size_bytes", 1048576)  # 1MB default
    backup_count = log_config.get("summarize_day_backup_count", 3)
    
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Set up OpenAI usage logger with rotation if configured
    openai_config = load_openai_config()
    if 'logging' in openai_config and 'openai_usage_log_file' in openai_config['logging']:
        openai_logger = logging.getLogger('openai_usage')
        openai_logger.setLevel(logging.INFO)
        
        # Clear any existing handlers for the openai logger
        if openai_logger.handlers:
            openai_logger.handlers.clear()
        
        # Prevent propagation to root logger to avoid duplicate entries
        openai_logger.propagate = False
        
        openai_log_config = openai_config['logging']
        openai_log_file = LOG_DIR / openai_log_config['openai_usage_log_file']
        openai_handler = logging.handlers.RotatingFileHandler(
            openai_log_file,
            maxBytes=openai_log_config.get('openai_usage_max_size_bytes', 1048576),  # Default 1MB
            backupCount=openai_log_config.get('openai_usage_backup_count', 3)        # Default 3 backups
        )
        
        # Simple formatter for OpenAI usage log (just the message)
        openai_formatter = logging.Formatter('%(message)s')
        openai_handler.setFormatter(openai_formatter)
        openai_logger.addHandler(openai_handler)
    
    logger.info("Logging configured successfully")

def process_with_openai(transcriptions, prompt_template, openai_config):
    """Process the transcriptions with OpenAI API using the prompt template."""
    # Format journal content from transcriptions
    journal_content = format_transcriptions_for_llm(transcriptions)
    
    # Format the prompt with the journal content
    prompt = prompt_template.format(
        journal_content=journal_content
    )
    
    # Set up the API request
    config = openai_config['openai_config']
    api_key = config['api_key'] or os.environ.get('OPENAI_API_KEY')
    
    if not api_key:
        logging.error("No OpenAI API key found. Set it in the config file or as an environment variable.")
        return None
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": config['model'],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config['temperature'],
        "max_tokens": config['max_tokens'],
        "top_p": config['top_p'],
        "frequency_penalty": config['frequency_penalty'],
        "presence_penalty": config['presence_penalty']
    }
    
    try:
        response = requests.post(
            config['api_endpoint'],
            headers=headers,
            data=json.dumps(payload)
        )
        response.raise_for_status()
        result = response.json()
        
        # Log usage if tracking is enabled
        if config['save_usage_stats']:
            usage = result.get('usage', {})
            usage_log = f"{datetime.now().isoformat()} | {config['model']} | " \
                       f"Prompt: {usage.get('prompt_tokens', 0)} | " \
                       f"Completion: {usage.get('completion_tokens', 0)} | " \
                       f"Total: {usage.get('total_tokens', 0)}"
            
            # Use the dedicated OpenAI usage logger instead of direct file writing
            openai_logger = logging.getLogger('openai_usage')
            openai_logger.info(usage_log)
        
        return result['choices'][0]['message']['content']
    except Exception as e:
        logging.error(f"Error processing with OpenAI: {e}")
        return None

def format_transcriptions_for_llm(transcriptions):
    """Format the transcriptions into a string suitable for the LLM prompt."""
    config = load_config()
    output_format = config.get("output", {})
    date_format = output_format.get("date_format", "%Y-%m-%d")
    
    journal_content = ""
    
    for entry in transcriptions:
        created_at = entry.get('created_at')
        content = entry.get('content', '')
        category = entry.get('category_name', 'Uncategorized')
        
        if created_at:
            date_str = created_at.strftime(date_format)
            time_str = created_at.strftime("%H:%M:%S")
            journal_content += f"[{date_str} {time_str}] {category}\n"
        else:
            journal_content += f"[No Date] {category}\n"
        
        journal_content += f"{content}\n\n"
        journal_content += "-" * 40 + "\n\n"
    
    return journal_content

def date_from_int(date_int):
    """Convert integer date in format YYYYMMDD to date object"""
    date_str = str(date_int)
    try:
        year = int(date_str[0:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        return datetime(year, month, day, 0, 0, 0)
    except (ValueError, IndexError) as e:
        logger.error(f"Invalid date format: {date_int}. Expected YYYYMMDD. Error: {str(e)}")
        return None

def get_date_range(config):
    """Get date range from config or use current date as fallback"""
    date_range = config.get("date_range", [])
    
    # Fallback to current date if range is empty
    if not date_range:
        today = datetime.now()
        today_int = int(today.strftime("%Y%m%d"))
        logger.info(f"No date range specified, using current date: {today_int}")
        return today, today
    
    # If only one date is specified, use it for both start and end
    if len(date_range) == 1:
        start_date_int = date_range[0]
        start_date = date_from_int(start_date_int)
        if not start_date:
            today = datetime.now()
            logger.warning(f"Invalid date format: {start_date_int}. Falling back to current date.")
            return today, today
        return start_date, start_date
    
    # Normal case: two dates specified
    if len(date_range) >= 2:
        start_date_int, end_date_int = date_range[0], date_range[1]
        
        start_date = date_from_int(start_date_int)
        end_date = date_from_int(end_date_int)
        
        if not start_date or not end_date:
            today = datetime.now()
            logger.warning("Invalid date format in range. Falling back to current date.")
            return today, today
        
        return start_date, end_date

def get_active_prompt(prompts):
    """
    Get the currently active prompt from the prompts dictionary.
    If multiple prompts are set to active, the first one is used and a warning is logged.
    """
    active_prompts = []
    
    # Find all active prompts
    for name, prompt_data in prompts.items():
        if prompt_data.get('active', False):
            active_prompts.append((name, prompt_data.get('template', '')))
    
    # Handle different cases
    if len(active_prompts) == 1:
        # Normal case - exactly one active prompt
        name, template = active_prompts[0]
        logger.info(f"Using active prompt: {name}")
        return name, template
    elif len(active_prompts) > 1:
        # Error case - multiple active prompts
        names = [name for name, _ in active_prompts]
        logger.warning(f"Multiple active prompts found: {', '.join(names)}. Using the first one: {names[0]}")
        return active_prompts[0]
    else:
        # Fallback case - no active prompts
        if prompts:
            first_prompt_name = next(iter(prompts))
            first_template = prompts[first_prompt_name].get('template', '')
            logger.warning(f"No active prompt found, using the first one: {first_prompt_name}")
            return first_prompt_name, first_template
    
    return None, None

def summarize_day():
    """
    Main function to summarize transcriptions for a specified date range.
    
    Reads date range from config, fetches transcriptions, processes them with OpenAI,
    and writes the result to file.
    """
    config = load_config()
    setup_logging(config)
    
    logger.info("Starting summarize_day process")
    
    # Get date range from config with fallback to current date
    start_date, end_date = get_date_range(config)
    
    # Adjust dates to include full days
    start_date = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    end_date = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
    
    logger.info(f"Fetching transcriptions from {start_date} to {end_date}")
    
    # Get transcriptions for the date range
    transcriptions = get_transcriptions_by_date_range(start_date, end_date)
    
    if not transcriptions:
        logger.warning(f"No transcriptions found for the date range {start_date.strftime('%Y%m%d')} to {end_date.strftime('%Y%m%d')}")
        return False
    
    logger.info(f"Found {len(transcriptions)} transcriptions")
    
    # Get output file path from config
    output_path = config.get("paths", {}).get("summarized_directory")
    if not output_path:
        logger.error("Output path not specified in config")
        return False
    
    # Create containing directory if it doesn't exist
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare output format
    output_format = config.get("output", {})
    date_format = output_format.get("date_format", "%Y-%m-%d")
    
    # Sort transcriptions by created_at in ascending order
    sorted_transcriptions = sorted(
        transcriptions, 
        key=lambda x: x['created_at'] if x.get('created_at') else datetime.min
    )
    
    # Process with OpenAI
    logger.info("Processing transcriptions with OpenAI")
    openai_config = load_openai_config()
    prompts = load_prompts()
    
    # Get the active prompt
    prompt_name, prompt_template = get_active_prompt(prompts)
    
    if not prompt_template:
        logger.error("No prompt templates found in prompts.yaml")
        return False
    
    summarized_content = process_with_openai(sorted_transcriptions, prompt_template, openai_config)
    
    if not summarized_content:
        logger.error("Failed to summarize transcriptions with OpenAI")
        return False
    
    # Write to file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            # Handle single day vs date range in header
            if start_date.date() == end_date.date():
                f.write(f"=== Diary Summary: {start_date.strftime(date_format)} ===\n\n")
            else:
                f.write(f"=== Diary Summary: {start_date.strftime(date_format)} to {end_date.strftime(date_format)} ===\n\n")
            
            # Write the summarized content
            f.write(summarized_content)
        
        logger.info(f"Successfully wrote summarized content to {output_path}")
        return True
    
    except Exception as e:
        logger.error(f"Error writing to output file: {str(e)}")
        return False

if __name__ == "__main__":
    summarize_day()
