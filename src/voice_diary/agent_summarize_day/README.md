# Voice Diary - Summarize Day with OpenAI Assistants API

This module summarizes voice diary transcriptions for a specified date range using the OpenAI Assistants API.

## How It Works

1. The script retrieves transcriptions from the database for a specified date range.
2. It formats the transcriptions and sends them to an OpenAI Assistant.
3. The OpenAI Assistant processes the content and generates a summarized version.
4. The summarized content is saved to a text file.

## Configuration

Configuration is managed through JSON files in the `summarize_day_config` directory:

### summarize_day_config.json

Contains settings for:
- Output paths for summarized content
- Logging configuration
- Date range to process (in YYYYMMDD format)

### openai_config.json

Contains settings for OpenAI API:
- API key (leave empty to use environment variable)
- Model to use (default: gpt-4o)
- Temperature and other generation parameters
- Assistant ID (will be auto-populated after first run)
- Thread ID (will be auto-populated after first run)
- Thread creation date (will be auto-populated after first run)
- Thread retention days (default: 30, controls how often new threads are created)

### prompts.yaml

Contains prompt templates used for summarizing the content. You can define multiple prompts and set one as active.

## Using the Assistant API

This script uses the OpenAI Assistants API, which:
- Creates a persistent assistant that can be reused across multiple runs
- Maintains conversation context in a persistent thread
- Provides more consistent formatting and structure in responses

On first run, the script will:
1. Create a new Assistant with the appropriate instructions
2. Save the Assistant ID in the config file for future use
3. Create a new thread for summarization tasks
4. Save the Thread ID and creation date in the config file

On subsequent runs, it will:
1. Reuse the existing Assistant (with the saved ID)
2. Use the existing thread to maintain conversation context
3. Create a new thread if the existing one exceeds the retention period

## Thread Retention

The script includes thread retention management:
- `thread_retention_days` in the config file controls how long a thread is used before creating a new one
- The script checks the thread creation date on each run
- When a thread exceeds the retention period, a new thread is created
- This prevents threads from growing too large and maintains performance

## Requirements

- Python 3.8+
- openai>=1.14.0
- Access to OpenAI API with permissions for Assistants API

## Environment Variables

You can set the following environment variables:
- `OPENAI_API_KEY`: Your OpenAI API key (alternative to setting in config file) 