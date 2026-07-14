"""Language configuration loading from SQLite."""

import json
import sqlite3

from lib.paths import DB_FILE


def _row_to_config(row):
    config = {
        "name": row["name"],
        "tts_provider": row["tts_provider"],
        "tts_voice": row["tts_voice"],
        "instructions": row["instructions"],
        "model_name": row["model_name"],
        "csv_files": json.loads(row["csv_files"] or "[]"),
    }

    optional_fields = ("tts_speed", "tts_rate", "tts_volume", "tts_pitch")
    for field in optional_fields:
        if row[field] is not None:
            config[field] = row[field]

    return config


def load_language_configurations(db_file=DB_FILE):
    """Load all language configurations keyed by language code."""
    if not db_file.exists():
        raise FileNotFoundError(f"Database not found: {db_file}")

    connection = sqlite3.connect(str(db_file))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT language, name, tts_provider, tts_voice, tts_speed, tts_rate,
                   tts_volume, tts_pitch, instructions, model_name, csv_files
            FROM language_configuration
            ORDER BY language
            """
        ).fetchall()
    except sqlite3.OperationalError as error:
        raise RuntimeError(
            "language_configuration table not found. Start the app to initialize the database."
        ) from error
    finally:
        connection.close()

    return {row["language"]: _row_to_config(row) for row in rows}


def load_language_configuration(language, db_file=DB_FILE):
    """Load one language configuration by language code."""
    configurations = load_language_configurations(db_file)
    if language not in configurations:
        available = ", ".join(configurations.keys()) or "(none)"
        raise ValueError(
            f"Language not configured: {language}. Available: {available}"
        )
    return configurations[language]
