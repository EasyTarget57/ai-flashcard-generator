import sqlite3
import json
import sys
import argparse
import random
from pathlib import Path

import genanki

# Load languages configuration
with open("languages.json", "r", encoding="utf-8") as f:
    LANGUAGES_CONFIG = json.load(f)

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
args = parser.parse_args()

LANGUAGE = args.language.lower()
TEST_MODE = args.test
if LANGUAGE not in LANGUAGES_CONFIG:
    print(f"Error: Language '{LANGUAGE}' not found in languages.json")
    print(f"Available languages: {', '.join(LANGUAGES_CONFIG.keys())}")
    sys.exit(1)

LANG_CONFIG = LANGUAGES_CONFIG[LANGUAGE]

OUTPUT_DIR = Path("output") / LANGUAGE
AUDIO_DIR = Path("audio") / LANGUAGE
DB_FILE = Path("flashcards.db")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DECK_NAME = LANG_CONFIG["name"]
if TEST_MODE:
    DECK_NAME = f"{DECK_NAME}-test"
MODEL_NAME = LANG_CONFIG["model_name"]
FIELDS = LANG_CONFIG["fields"]

# Verify database exists
if not DB_FILE.exists():
    print(f"Error: Database not found: {DB_FILE}")
    print("Please run: python init_db.py && python create_flashcards.py --language {LANGUAGE}")
    sys.exit(1)

# Build model fields from config
field_list = [{"name": field} for field in FIELDS]

# Build question format - show audio and first field
qfmt = f"""
{{{{Audio}}}}

<div class="target">
{{{{{FIELDS[0]}}}}}
</div>
"""

# Build answer format - show remaining fields
afmt = """
{{FrontSide}}

<hr id="answer">

<div class="translations">
"""
for field in FIELDS[1:]:
    if field != "Audio":
        afmt += f'<div class="{field.lower().replace(" ", "_")}">\n{{{{{field}}}}}\n</div>\n'

afmt += """
</div>
"""

MODEL = genanki.Model(
    random.randrange(1 << 30),
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

.english {
    font-weight: bold;
    color: #333;
}

.romaji {
    color: gray;
    font-size: 18px;
}

.spanish {
    font-weight: bold;
    color: #333;
}

.french {
    font-weight: bold;
    color: #333;
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
    random.randrange(1 << 30),
    DECK_NAME
)

media_files = []


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
        elif field == "Notes":
            field_values.append(row["notes"] or "")
        else:
            # Map database fields to card fields
            if field == FIELDS[0]:  # Target language field
                field_values.append(row["target_language_text"] or "")
            elif field == "English":
                field_values.append(row["translation"] or "")
            elif field == "Translation":
                # Generic translation field for any target language
                field_values.append(row["translation"] or "")
            elif field in ("Romaji", "Pronunciation"):
                field_values.append(row["pronunciation"] or "")
            else:
                field_values.append("")

    # Build tags from source
    tags = []
    if row["source"]:
        tags.append(row["source"])

    note = genanki.Note(
        model=MODEL,
        fields=field_values,
        tags=tags
    )

    deck.add_note(note)


def main():
    print(f"Creating Anki deck for {LANG_CONFIG['name']}...\n")

    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query flashcards for this language, ordered by type and id
    if TEST_MODE:
        cursor.execute(
            "SELECT * FROM flashcards WHERE language = ? AND test = 1 ORDER BY type, id",
            (LANGUAGE,)
        )
    else:
        cursor.execute(
            "SELECT * FROM flashcards WHERE language = ? AND test = 0 ORDER BY type, id",
            (LANGUAGE,)
        )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"No flashcards found for language: {LANGUAGE}")
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

    output = OUTPUT_DIR / f"{DECK_NAME}.apkg"
    package.write_to_file(str(output))

    print()
    print(f"Created {output}")
    print(f"{len(rows)} cards")
    print(f"{len(media_files)} audio files")

    # Clean up test entries if in test mode
    if TEST_MODE:
        print()
        print(f"WARNING: About to delete all {len(rows)} test entries for '{LANGUAGE}' and their audio files.")
        print("This cannot be undone.")
        response = input("Continue? (y/n): ").strip().lower()
        
        if response == "y":
            conn = sqlite3.connect(str(DB_FILE))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get audio filenames before deletion
            cursor.execute(
                "SELECT audio_filename FROM flashcards WHERE language = ? AND test = 1",
                (LANGUAGE,)
            )
            audio_files = cursor.fetchall()
            
            # Delete test entries
            cursor.execute(
                "DELETE FROM flashcards WHERE language = ? AND test = 1",
                (LANGUAGE,)
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
