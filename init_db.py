import json
import sqlite3

from lib.paths import DB_FILE, PROJECT_ROOT, ensure_data_dirs, migrate_repo_data_to_user_data
from lib.decks import ensure_deck_schema


LANGUAGES_FILE = PROJECT_ROOT / "languages.json"


def create_language_configuration_table(cursor):
    """Create the table that stores language-level TTS/deck configuration."""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS language_configuration (
        language TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tts_provider TEXT NOT NULL DEFAULT 'openai',
        tts_voice TEXT,
        tts_speed REAL,
        tts_rate TEXT,
        tts_volume TEXT,
        tts_pitch TEXT,
        instructions TEXT,
        model_name TEXT NOT NULL,
        csv_files TEXT NOT NULL DEFAULT '[]',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_language_configuration_updated_at
    AFTER UPDATE ON language_configuration
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE language_configuration
        SET updated_at = CURRENT_TIMESTAMP
        WHERE language = NEW.language;
    END;
    """)


def seed_language_configuration(cursor):
    """Seed language configuration from languages.json without overwriting edits."""
    if not LANGUAGES_FILE.exists():
        return 0

    with LANGUAGES_FILE.open("r", encoding="utf-8") as config_file:
        languages = json.load(config_file)

    inserted = 0
    for language, config in languages.items():
        cursor.execute(
            """
            INSERT OR IGNORE INTO language_configuration (
                language,
                name,
                tts_provider,
                tts_voice,
                tts_speed,
                tts_rate,
                tts_volume,
                tts_pitch,
                instructions,
                model_name,
                csv_files
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                language,
                config["name"],
                config.get("tts_provider", "openai"),
                config.get("tts_voice"),
                config.get("tts_speed"),
                config.get("tts_rate"),
                config.get("tts_volume"),
                config.get("tts_pitch"),
                config.get("instructions"),
                config["model_name"],
                json.dumps(config.get("csv_files", []), ensure_ascii=False),
            ),
        )
        inserted += cursor.rowcount

    return inserted

def init_database(verbose=True):
    """Initialize the flashcards database."""
    moved, skipped = migrate_repo_data_to_user_data()
    ensure_data_dirs()

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

    create_language_configuration_table(cursor)
    seeded_languages = seed_language_configuration(cursor)
    ensure_deck_schema(cursor)

    conn.commit()
    conn.close()
    if verbose:
        print(f"Database initialized: {DB_FILE}")
        for source, destination in moved:
            print(f"Moved {source} -> {destination}")
        for source, destination in skipped:
            print(f"Skipped existing user data for {source}; kept repo copy at {source}")
        if seeded_languages:
            print(f"Seeded language configuration rows: {seeded_languages}")

if __name__ == "__main__":
    init_database()
