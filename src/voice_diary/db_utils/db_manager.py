import logging
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import json

from voice_diary.db_utils.db_config import get_db_url

# Ensure logging is configured
logger = logging.getLogger(__name__)

# Connection pool for reusing database connections
connection_pool = None

def initialize_db():
    """Initialize database and create necessary tables if they don't exist"""
    global connection_pool

    try:
        # Initialize connection pool
        db_url = get_db_url()
        connection_pool = pool.SimpleConnectionPool(1, 10, db_url)
        
        # Create tables
        create_tables()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        return False

def get_connection():
    """Get a connection from the pool"""
    global connection_pool
    
    if connection_pool is None:
        initialize_db()
    
    return connection_pool.getconn()

def return_connection(conn):
    """Return a connection to the pool"""
    global connection_pool
    
    if connection_pool is not None:
        connection_pool.putconn(conn)

def create_tables():
    """Create necessary tables if they don't exist"""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Create transcriptions table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            filename TEXT,
            audio_path TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            duration_seconds FLOAT,
            metadata JSONB
        )
        """)
        
        # Create index on transcriptions.created_at for faster date-based queries
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcriptions_created_at ON transcriptions(created_at)
        """)
        
        conn.commit()
        logger.info("Database tables created successfully")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error creating tables: {str(e)}")
        raise
    finally:
        if conn:
            return_connection(conn)

def save_transcription(content, filename=None, audio_path=None, model_type=None, 
                      duration_seconds=None, category=None, metadata=None):
    """
    Save a transcription to the database
    
    Args:
        content (str): The transcription text
        filename (str, optional): Original audio filename
        audio_path (str, optional): Path to the original audio file
        duration_seconds (float, optional): Duration of the audio in seconds
        category (str, optional): Category name for the transcription
        metadata (dict, optional): Additional metadata for the transcription
        
    Returns:
        int: ID of the inserted record or None if error
    """
    conn = None
    category_id = None
    transcription_id = None
    
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Convert metadata to JSONB if provided
        metadata_json = json.dumps(metadata) if metadata else None
        
        # Insert transcription
        cur.execute("""
        INSERT INTO transcriptions 
        (content, filename, audio_path, duration_seconds, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """, (content, filename, audio_path, duration_seconds, metadata_json))
        
        transcription_id = cur.fetchone()[0]
        
        conn.commit()
        logger.info(f"Saved transcription with ID: {transcription_id}")
        return transcription_id
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error saving transcription: {str(e)}")
        return None
    finally:
        if conn:
            return_connection(conn)

def get_transcription(transcription_id):
    """Retrieve a transcription by ID"""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
        SELECT t.*, c.name as category_name
        FROM transcriptions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.id = %s
        """, (transcription_id,))
        
        result = cur.fetchone()
        return result
    except Exception as e:
        logger.error(f"Error retrieving transcription: {str(e)}")
        return None
    finally:
        if conn:
            return_connection(conn)

def get_latest_transcriptions(limit=10):
    """Retrieve the latest transcriptions"""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
        SELECT t.*, c.name as category_name
        FROM transcriptions t
        LEFT JOIN categories c ON t.category_id = c.id
        ORDER BY t.created_at DESC
        LIMIT %s
        """, (limit,))
        
        results = cur.fetchall()
        return results
    except Exception as e:
        logger.error(f"Error retrieving latest transcriptions: {str(e)}")
        return []
    finally:
        if conn:
            return_connection(conn)

def get_transcriptions_by_date_range(start_date, end_date):
    """Retrieve transcriptions within a date range"""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
        SELECT t.*, c.name as category_name
        FROM transcriptions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.created_at BETWEEN %s AND %s
        ORDER BY t.created_at DESC
        """, (start_date, end_date))
        
        results = cur.fetchall()
        return results
    except Exception as e:
        logger.error(f"Error retrieving transcriptions by date range: {str(e)}")
        return []
    finally:
        if conn:
            return_connection(conn)

def close_all_connections():
    """Close all database connections"""
    global connection_pool
    
    if connection_pool:
        connection_pool.closeall()
        connection_pool = None
        logger.info("All database connections closed")
