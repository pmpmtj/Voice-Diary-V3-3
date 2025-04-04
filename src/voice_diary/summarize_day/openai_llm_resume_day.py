

########## THIS SCRIPT IS A TEMPLATE AND IS USED BY SUMMARIZE_DAY.PY ##########
########## THIS SCRIPT IS A TEMPLATE AND IS USED BY SUMMARIZE_DAY.PY ##########
########## THIS SCRIPT IS A TEMPLATE AND IS USED BY SUMMARIZE_DAY.PY ##########


#!/usr/bin/env python3
"""
Entries Summarizer

This script processes a list of entries and uses OpenAI to create a summarized version.
"""

import os
import sys
import json
import logging
import requests
import yaml
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Constants
SCRIPT_DIR = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "summarize_day_config" / "openai_config.json"
LOG_DIR = SCRIPT_DIR / "log"
PROMPTS_PATH = SCRIPT_DIR / "summarize_day_config" / "prompts.yaml"

# Create log directory if it doesn't exist
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Initialize logger
logger = logging.getLogger("openai_llm_resume_day")

def load_config():
    """Load configuration from JSON file"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        sys.exit(1)


def load_prompts():
    """Load prompt templates from YAML file"""
    try:
        with open(PROMPTS_PATH, 'r', encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
            return prompts
    except Exception as e:
        logger.error(f"Error loading prompt templates: {str(e)}")
        sys.exit(1)


def setup_logging(config):
    """Set up logging with rotation based on configuration."""
    log_config = config['logging']
    log_file = LOG_DIR / log_config['log_file']
    
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_config['log_level']))
    
    # Clear any existing handlers (to avoid duplicates when called multiple times)
    if logger.handlers:
        logger.handlers.clear()
    
    # Create main log handler with rotation
    main_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_config['max_size_bytes'],
        backupCount=log_config['backup_count']
    )
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    main_handler.setFormatter(formatter)
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    logger.addHandler(main_handler)
    logger.addHandler(console_handler)
    
    # Set up OpenAI usage logger with rotation if configured
    if 'openai_usage_log_file' in log_config:
        openai_logger = logging.getLogger('openai_usage')
        openai_logger.setLevel(logging.INFO)
        
        # Clear any existing handlers for the openai logger
        if openai_logger.handlers:
            openai_logger.handlers.clear()
        
        # Prevent propagation to root logger to avoid duplicate entries
        openai_logger.propagate = False
        
        openai_log_file = LOG_DIR / log_config['openai_usage_log_file']
        openai_handler = RotatingFileHandler(
            openai_log_file,
            maxBytes=log_config.get('openai_usage_max_size_bytes', 1048576),  # Default 1MB
            backupCount=log_config.get('openai_usage_backup_count', 3)        # Default 3 backups
        )
        
        # Simple formatter for OpenAI usage log (just the message)
        openai_formatter = logging.Formatter('%(message)s')
        openai_handler.setFormatter(openai_formatter)
        openai_logger.addHandler(openai_handler)
    
    return logger


def process_with_openai(journal_content, prompt_template, openai_config):
    """Process the journal content with OpenAI API using the prompt template."""
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


def read_journal_entries(file_path):
    """Read journal entries from a file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading journal entries: {e}")
        return None


def save_summarized_journal(content, output_path, date_str=None):
    """Save the summarized journal to a file"""
    # Create output directory if it doesn't exist
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if date_str:
        # Add date to filename if provided
        file_name = f"summarized_{date_str}.md"
        full_path = output_dir / file_name
    else:
        # Use timestamp if no date provided
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"summarized_{timestamp}.md"
        full_path = output_dir / file_name
    
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Summarized journal saved to {full_path}")
        return str(full_path)
    except Exception as e:
        logger.error(f"Error saving summarized journal: {e}")
        return None


def summarize_journal_entries(input_file=None, output_file=None):
    """
    Main function to summarize journal entries using OpenAI.
    
    Args:
        input_file (str, optional): Path to the input file containing journal entries.
        output_file (str, optional): Path to save the summarized journal.
    
    Returns:
        bool: True if successful, False otherwise.
    """
    # Load configuration
    config = load_config()
    
    # Setup logging
    setup_logging(config)
    
    logger.info("Starting journal summarization process")
    
    # Load prompts
    prompts = load_prompts()
    summarize_prompt_template = prompts.get('summarize_prompt')
    
    if not summarize_prompt_template:
        logger.error("Summarize prompt template not found in prompts.yaml")
        return False
    
    # Determine input file
    if not input_file:
        summarize_day_config = load_summarize_day_config()
        input_file = summarize_day_config.get('paths', {}).get('summarized_directory')
        
        if not input_file:
            logger.error("Input file not specified and not found in config")
            return False
    
    # Read journal entries
    logger.info(f"Reading journal entries from {input_file}")
    journal_content = read_journal_entries(input_file)
    
    if not journal_content:
        logger.error("No journal content found")
        return False
    
    # Process with OpenAI
    logger.info("Processing journal entries with OpenAI")
    summarized_content = process_with_openai(journal_content, summarize_prompt_template, config)
    
    if not summarized_content:
        logger.error("Failed to summarize journal entries")
        return False
    
    # Determine output file
    if not output_file:
        # Extract date from input filename or use current date
        date_match = re.search(r'(\d{8})', str(input_file))
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y%m%d")
        
        # Use summarized_entries directory
        output_dir = SCRIPT_DIR / "summarized_entries"
        output_file = output_dir / f"summarized_{date_str}.md"
    
    # Save summarized content
    saved_path = save_summarized_journal(summarized_content, output_file)
    
    if saved_path:
        logger.info(f"Journal summarization completed successfully. Output at {saved_path}")
        return True
    else:
        logger.error("Failed to save summarized journal")
        return False


def load_summarize_day_config():
    """Load summarize_day configuration from JSON file"""
    config_path = SCRIPT_DIR / "summarize_day_config" / "summarize_day_config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading summarize_day configuration: {str(e)}")
        return {}


if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
        summarize_journal_entries(input_file, output_file)
    else:
        # Use default files from config
        summarize_journal_entries()


########## THIS SCRIPT IS A TEMPLATE AND IS USED BY SUMMARIZE_DAY.PY ##########
########## THIS SCRIPT IS A TEMPLATE AND IS USED BY SUMMARIZE_DAY.PY ##########
########## THIS SCRIPT IS A TEMPLATE AND IS USED BY SUMMARIZE_DAY.PY ##########

