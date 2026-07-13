import sqlite3
from pathlib import Path

DB_FILE = Path("flashcards.db")

def init_database():
    """Initialize the flashcards database."""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()

    # Create flashcards table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS flashcards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        language TEXT NOT NULL,
        type TEXT NOT NULL,

        target_language_text TEXT NOT NULL,
        translation TEXT NOT NULL,
        pronunciation TEXT,

        source TEXT,
        notes TEXT,

        audio_filename TEXT,
        test BOOLEAN NOT NULL DEFAULT 0,

        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_flashcards_language_target_text
    ON flashcards (language, target_language_text);
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized: {DB_FILE}")

if __name__ == "__main__":
    init_database()
