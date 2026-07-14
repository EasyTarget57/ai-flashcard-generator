import sqlite3


def normalized_deck_name(name):
    """Normalize user-entered deck names while preserving display casing."""
    return (name or "").strip()


def default_deck_name(language_config):
    return language_config["name"]


def ensure_deck_schema(cursor):
    """Create deck tables/indexes and migrate existing flashcards."""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        language TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_decks_language_name_nocase
    ON decks (language, name COLLATE NOCASE);
    """)

    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_decks_updated_at
    AFTER UPDATE ON decks
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE decks
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;
    """)

    cursor.execute("PRAGMA table_info(flashcards)")
    flashcard_columns = {row[1] for row in cursor.fetchall()}
    if "deck_id" not in flashcard_columns:
        cursor.execute("ALTER TABLE flashcards ADD COLUMN deck_id INTEGER")

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_flashcards_deck_id
    ON flashcards (deck_id);
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_flashcards_deck_target_text
    ON flashcards (deck_id, target_language_text);
    """)

    seed_default_decks(cursor)
    assign_missing_flashcard_decks(cursor)


def seed_default_decks(cursor):
    cursor.execute("""
        INSERT OR IGNORE INTO decks (language, name)
        SELECT DISTINCT lc.language, lc.name
        FROM language_configuration lc
        INNER JOIN flashcards f ON f.language = lc.language
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO decks (language, name)
        SELECT DISTINCT f.language, f.language
        FROM flashcards f
        LEFT JOIN language_configuration lc ON lc.language = f.language
        WHERE lc.language IS NULL
    """)


def assign_missing_flashcard_decks(cursor):
    cursor.execute("""
        UPDATE flashcards
        SET deck_id = (
            SELECT d.id
            FROM decks d
            LEFT JOIN language_configuration lc ON lc.language = flashcards.language
            WHERE d.language = flashcards.language
              AND d.name = COALESCE(lc.name, flashcards.language) COLLATE NOCASE
            LIMIT 1
        )
        WHERE deck_id IS NULL
    """)


def get_or_create_deck(cursor, language, name):
    deck_name = normalized_deck_name(name)
    if not deck_name:
        raise ValueError("Deck name cannot be empty")

    cursor.execute(
        """
        SELECT id, language, name
        FROM decks
        WHERE language = ? AND name = ? COLLATE NOCASE
        """,
        (language, deck_name),
    )
    row = cursor.fetchone()
    if row:
        return row

    cursor.execute(
        "INSERT INTO decks (language, name) VALUES (?, ?)",
        (language, deck_name),
    )
    deck_id = cursor.lastrowid
    cursor.execute(
        "SELECT id, language, name FROM decks WHERE id = ?",
        (deck_id,),
    )
    return cursor.fetchone()


def list_decks(connection, language):
    rows = connection.execute(
        """
        SELECT id, language, name
        FROM decks
        WHERE language = ?
        ORDER BY id
        """,
        (language,),
    ).fetchall()
    return [dict(row) if isinstance(row, sqlite3.Row) else {"id": row[0], "language": row[1], "name": row[2]} for row in rows]


def get_deck_by_id(cursor, language, deck_id):
    cursor.execute(
        """
        SELECT id, language, name
        FROM decks
        WHERE language = ? AND id = ?
        """,
        (language, deck_id),
    )
    return cursor.fetchone()


def get_deck_by_name(cursor, language, name):
    deck_name = normalized_deck_name(name)
    cursor.execute(
        """
        SELECT id, language, name
        FROM decks
        WHERE language = ? AND name = ? COLLATE NOCASE
        """,
        (language, deck_name),
    )
    return cursor.fetchone()
