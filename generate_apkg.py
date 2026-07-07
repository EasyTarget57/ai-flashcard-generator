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
args = parser.parse_args()

LANGUAGE = args.language.lower()
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
    cursor.execute(
        "SELECT * FROM flashcards WHERE language = ? ORDER BY type, id",
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


if __name__ == "__main__":
    main()
