import sqlite3
import sys
import argparse
import hashlib
import re

import genanki
from init_db import init_database
from lib.decks import default_deck_name, ensure_deck_schema, get_deck_by_id, get_deck_by_name
from lib.language_config import load_language_configurations
from lib.paths import AUDIO_ROOT, DB_FILE, OUTPUT_ROOT, ensure_data_dirs

ensure_data_dirs()

try:
    LANGUAGES_CONFIG = load_language_configurations(DB_FILE)
except Exception as e:
    print(f"Error: Failed to load language configuration: {e}")
    sys.exit(1)

# Parse arguments
parser = argparse.ArgumentParser(description="Generate Anki deck from database")
parser.add_argument(
    "--language",
    required=True,
    help=f"Language to generate deck for. Available: {', '.join(LANGUAGES_CONFIG.keys())}"
)
parser.add_argument(
    "--test",
    action="store_true",
    help="Generate test deck and clean up test entries after creation"
)
parser.add_argument(
    "--deck",
    help="Deck name to export. If omitted, the language name is used."
)
parser.add_argument(
    "--deck-id",
    type=int,
    help="Deck ID to export."
)
args = parser.parse_args()

LANGUAGE = args.language.lower()
TEST_MODE = args.test
if LANGUAGE not in LANGUAGES_CONFIG:
    print(f"Error: Language '{LANGUAGE}' not found in language_configuration")
    print(f"Available languages: {', '.join(LANGUAGES_CONFIG.keys())}")
    sys.exit(1)

LANG_CONFIG = LANGUAGES_CONFIG[LANGUAGE]

OUTPUT_DIR = OUTPUT_ROOT / LANGUAGE
AUDIO_DIR = AUDIO_ROOT / LANGUAGE

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NAME = LANG_CONFIG["model_name"]

# Standardized field names
FIELDS = ["Audio", "Front", "Back", "Pronunciation", "Notes"]

# Verify database exists
if not DB_FILE.exists():
    print(f"Error: Database not found: {DB_FILE}")
    print("Please run: python init_db.py && python create_flashcards.py --language {LANGUAGE}")
    sys.exit(1)

init_database(verbose=False)

conn = sqlite3.connect(str(DB_FILE))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
ensure_deck_schema(cursor)
if args.deck_id is not None:
    DECK_ROW = get_deck_by_id(cursor, LANGUAGE, args.deck_id)
    if DECK_ROW is None:
        print(f"Error: Deck ID '{args.deck_id}' not found for language '{LANGUAGE}'")
        conn.close()
        sys.exit(1)
else:
    deck_name_arg = args.deck.strip() if args.deck else default_deck_name(LANG_CONFIG)
    DECK_ROW = get_deck_by_name(cursor, LANGUAGE, deck_name_arg)
    if DECK_ROW is None:
        print(f"Error: Deck '{deck_name_arg}' not found for language '{LANGUAGE}'")
        conn.close()
        sys.exit(1)
conn.commit()
conn.close()

DECK_ID = DECK_ROW["id"]
BASE_DECK_NAME = DECK_ROW["name"]
DECK_NAME = BASE_DECK_NAME
if TEST_MODE:
    DECK_NAME = f"{DECK_NAME}-test"

# Build model fields from config
field_list = [{"name": field} for field in FIELDS]


def stable_numeric_id(kind, language):
    """Return a stable positive ID suitable for an Anki model or deck."""
    value = f"flashcard-generator:{kind}:{language}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest()[:4], "big") & ((1 << 30) - 1)


def anki_deck_id():
    if BASE_DECK_NAME.casefold() == default_deck_name(LANG_CONFIG).casefold():
        return stable_numeric_id("deck", LANGUAGE)
    return stable_numeric_id("deck", f"{LANGUAGE}:{DECK_ID}")


def safe_filename(name):
    filename = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    return filename or "deck"

# Build question format - show audio and Front field
qfmt = """
{{Audio}}

<div class="target">
{{Front}}
</div>
"""

# Build answer format - show remaining fields
afmt = """
{{FrontSide}}

<hr id="answer">

<div class="translations">
<div class="back">{{Back}}</div>
{{#Pronunciation}}<div class="pronunciation">{{Pronunciation}}</div>{{/Pronunciation}}
{{#Notes}}<div class="notes">{{Notes}}</div>{{/Notes}}
</div>
"""

MODEL = genanki.Model(
    stable_numeric_id("model", LANGUAGE),
    MODEL_NAME,
    fields=field_list,
    templates=[
        {
            "name": "Listening",
            "qfmt": qfmt,
            "afmt": afmt
        }
    ],
    css="""
.card {
    font-family: Arial;
    font-size: 24px;
    text-align: center;
}

.target {
    font-size: 40px;
    margin: 20px 0;
}

.translations {
    font-size: 28px;
    margin-top: 20px;
}

.translations > div {
    margin: 10px 0;
}

.back {
    font-weight: bold;
    color: #333;
}

.pronunciation {
    color: gray;
    font-size: 18px;
}

.notes {
    margin-top: 20px;
    font-size: 16px;
    color: #666;
}
"""
)

# Create deck
deck = genanki.Deck(
    anki_deck_id(),
    DECK_NAME
)

media_files = []


def source_to_tag(source):
    """Convert a source label to an Anki-compatible tag."""
    tag = re.sub(r"\s+", "_", (source or "").strip())
    return tag or None


def add_flashcard_from_db(row):
    """Add a flashcard from database to deck."""
    # Build field values from database
    field_values = []
    for field in FIELDS:
        if field == "Audio":
            # Audio filename is stored in database
            audio_filename = row["audio_filename"]
            if audio_filename:
                media_path = AUDIO_DIR / audio_filename
                if media_path.exists():
                    media_files.append(str(media_path))
                    field_values.append(f"[sound:{audio_filename}]")
                else:
                    print(f"WARNING: Audio file not found: {media_path}")
                    field_values.append("")
            else:
                field_values.append("")
        elif field == "Front":
            field_values.append(row["target_language_text"] or "")
        elif field == "Back":
            field_values.append(row["translation"] or "")
        elif field == "Pronunciation":
            field_values.append(row["pronunciation"] or "")
        elif field == "Notes":
            field_values.append(row["notes"] or "")
        else:
            field_values.append("")

    # Build tags from source
    tags = []
    source_tag = source_to_tag(row["source"])
    if source_tag:
        tags.append(source_tag)

    note = genanki.Note(
        model=MODEL,
        fields=field_values,
        tags=tags,
        # The database row is the identity. Field and audio changes must not
        # create a second Anki note on later imports.
        guid=genanki.guid_for("flashcard-generator", LANGUAGE, str(row["id"])),
    )

    deck.add_note(note)


def main():
    print(f"Creating Anki deck for {LANG_CONFIG['name']} / {BASE_DECK_NAME}...\n")

    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query flashcards for this language and deck, ordered by type and id
    if TEST_MODE:
        cursor.execute(
            """
            SELECT *
            FROM flashcards
            WHERE language = ? AND deck_id = ? AND test = 1
            ORDER BY type, id
            """,
            (LANGUAGE, DECK_ID)
        )
    else:
        cursor.execute(
            """
            SELECT *
            FROM flashcards
            WHERE language = ? AND deck_id = ? AND test = 0
            ORDER BY type, id
            """,
            (LANGUAGE, DECK_ID)
        )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"No flashcards found for language: {LANGUAGE}, deck: {BASE_DECK_NAME}")
        sys.exit(1)

    # Add flashcards to deck
    current_type = None
    for row in rows:
        if row["type"] != current_type:
            print(f"Adding {row['type']}...")
            current_type = row["type"]

        add_flashcard_from_db(row)

    # Create package
    package = genanki.Package(deck)
    package.media_files = media_files

    output = OUTPUT_DIR / f"{safe_filename(DECK_NAME)}.apkg"
    package.write_to_file(str(output))

    print()
    print(f"Created {output}")
    print(f"{len(rows)} cards")
    print(f"{len(media_files)} audio files")

    # Clean up test entries if in test mode
    if TEST_MODE:
        print()
        print(f"WARNING: About to delete all {len(rows)} test entries for '{LANGUAGE}' / '{BASE_DECK_NAME}' and their audio files.")
        print("This cannot be undone.")
        response = input("Continue? (y/n): ").strip().lower()
        
        if response == "y":
            conn = sqlite3.connect(str(DB_FILE))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get audio filenames before deletion
            cursor.execute(
                "SELECT audio_filename FROM flashcards WHERE language = ? AND deck_id = ? AND test = 1",
                (LANGUAGE, DECK_ID)
            )
            audio_files = cursor.fetchall()
            
            # Delete test entries
            cursor.execute(
                "DELETE FROM flashcards WHERE language = ? AND deck_id = ? AND test = 1",
                (LANGUAGE, DECK_ID)
            )
            conn.commit()
            conn.close()
            
            # Delete audio files
            deleted_audio = 0
            for row in audio_files:
                if row["audio_filename"]:
                    audio_path = AUDIO_DIR / row["audio_filename"]
                    if audio_path.exists():
                        audio_path.unlink()
                        deleted_audio += 1
            
            print(f"Deleted {len(audio_files)} test entries")
            print(f"Deleted {deleted_audio} audio files")
        else:
            print("Cleanup cancelled. Test entries remain in database.")


if __name__ == "__main__":
    main()
