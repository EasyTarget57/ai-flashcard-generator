import argparse
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import genanki

from lib.db import init_database
from lib.decks import default_deck_name, ensure_deck_schema, get_deck_by_id, get_deck_by_name
from lib.flashcards import delete_flashcards
from lib.language_config import load_language_configurations
from lib.paths import AUDIO_ROOT, DB_FILE, OUTPUT_ROOT, ensure_data_dirs


FIELDS = ["Audio", "Front", "Back", "Pronunciation", "Notes"]

QUESTION_FORMAT = """
{{Audio}}

<div class="target">
{{Front}}
</div>
"""

ANSWER_FORMAT = """
{{FrontSide}}

<hr id="answer">

<div class="translations">
<div class="back">{{Back}}</div>
{{#Pronunciation}}<div class="pronunciation">{{Pronunciation}}</div>{{/Pronunciation}}
{{#Notes}}<div class="notes">{{Notes}}</div>{{/Notes}}
</div>
"""

CARD_CSS = """
.card {
    font-family: Arial;
    font-size: 24px;
    text-align: center;
    background-color: #ffffff;
    color: #111827;
}

.target {
    font-size: 40px;
    margin: 20px 0;
    color: #111827;
}

hr {
    border: 0;
    border-top: 1px solid #6b7280;
}

.translations {
    font-size: 28px;
    margin-top: 20px;
    color: #1f2937;
}

.translations > div {
    margin: 10px 0;
}

.back {
    font-weight: bold;
    color: #1f2937;
}

.pronunciation {
    color: #6b7280;
    font-size: 18px;
}

.notes {
    margin-top: 20px;
    font-size: 16px;
    color: #4b5563;
}

.nightMode.card,
.nightMode .card,
.night_mode.card,
.night_mode .card {
    background-color: #1f1f1f;
    color: #f3f4f6;
}

.nightMode .target,
.night_mode .target {
    color: #f9fafb;
}

.nightMode hr,
.night_mode hr {
    border-top-color: #737373;
}

.nightMode .translations,
.night_mode .translations {
    color: #f3f4f6;
}

.nightMode .back,
.night_mode .back {
    color: #f3f4f6;
}

.nightMode .pronunciation,
.night_mode .pronunciation {
    color: #d1d5db;
}

.nightMode .notes,
.night_mode .notes {
    color: #d1d5db;
}

@media (prefers-color-scheme: dark) {
    .card {
        background-color: #1f1f1f;
        color: #f3f4f6;
    }

    .target {
        color: #f9fafb;
    }

    hr {
        border-top-color: #737373;
    }

    .translations,
    .back {
        color: #f3f4f6;
    }

    .pronunciation,
    .notes {
        color: #d1d5db;
    }
}
"""


def stable_numeric_id(kind, language):
    value = f"flashcard-generator:{kind}:{language}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest()[:4], "big") & ((1 << 30) - 1)


def safe_filename(name):
    filename = re.sub(r'[<>:"/\\|?*]+', "_", name).strip()
    return filename or "deck"


def source_to_tag(source):
    tag = re.sub(r"\s+", "_", (source or "").strip())
    return tag or None


def anki_deck_id(language, language_config, deck_row):
    if deck_row["name"].casefold() == default_deck_name(language_config).casefold():
        return stable_numeric_id("deck", language)
    return stable_numeric_id("deck", f"{language}:{deck_row['id']}")


def build_model(language, language_config):
    return genanki.Model(
        stable_numeric_id("model", language),
        language_config["model_name"],
        fields=[{"name": field} for field in FIELDS],
        templates=[
            {
                "name": "Listening",
                "qfmt": QUESTION_FORMAT,
                "afmt": ANSWER_FORMAT,
            }
        ],
        css=CARD_CSS,
    )


def add_flashcard_from_db(row, *, model, deck, audio_dir, media_files, language, log=print):
    field_values = []
    for field in FIELDS:
        if field == "Audio":
            audio_filename = row["audio_filename"]
            if audio_filename:
                media_path = audio_dir / audio_filename
                if media_path.exists():
                    media_files.append(str(media_path))
                    field_values.append(f"[sound:{audio_filename}]")
                else:
                    log(f"WARNING: Audio file not found: {media_path}")
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

    tags = []
    source_tag = source_to_tag(row["source"])
    if source_tag:
        tags.append(source_tag)

    note = genanki.Note(
        model=model,
        fields=field_values,
        tags=tags,
        guid=genanki.guid_for("flashcard-generator", language, str(row["id"])),
    )
    deck.add_note(note)


def resolve_deck(cursor, language, language_config, deck_id=None, deck_name=None):
    if deck_id is not None:
        deck_row = get_deck_by_id(cursor, language, deck_id)
        if deck_row is None:
            raise ValueError(f"Deck ID '{deck_id}' not found for language '{language}'")
        return deck_row

    name = deck_name.strip() if deck_name else default_deck_name(language_config)
    deck_row = get_deck_by_name(cursor, language, name)
    if deck_row is None:
        raise ValueError(f"Deck '{name}' not found for language '{language}'")
    return deck_row


def export_deck(
    *,
    language: str,
    deck_id: int | None = None,
    deck_name: str | None = None,
    test_mode: bool = False,
    delete_test_entries: bool = False,
    log=print,
) -> Path:
    ensure_data_dirs()
    init_database(verbose=False)

    language = language.lower()
    languages_config = load_language_configurations(DB_FILE)
    if language not in languages_config:
        raise ValueError(f"Language '{language}' not found in language_configuration")

    language_config = languages_config[language]
    output_dir = OUTPUT_ROOT / language
    audio_dir = AUDIO_ROOT / language
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    ensure_deck_schema(cursor)
    deck_row = resolve_deck(cursor, language, language_config, deck_id=deck_id, deck_name=deck_name)
    conn.commit()

    base_deck_name = deck_row["name"]
    anki_name = f"{base_deck_name}-test" if test_mode else base_deck_name
    model = build_model(language, language_config)
    deck = genanki.Deck(anki_deck_id(language, language_config, deck_row), anki_name)
    media_files = []

    log(f"Creating Anki deck for {language_config['name']} / {base_deck_name}...\n")

    cursor.execute(
        """
        SELECT *
        FROM flashcards
        WHERE language = ? AND deck_id = ? AND test = ?
        ORDER BY type, id
        """,
        (language, deck_row["id"], 1 if test_mode else 0),
    )
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        raise ValueError(f"No flashcards found for language: {language}, deck: {base_deck_name}")

    current_type = None
    for row in rows:
        if row["type"] != current_type:
            log(f"Adding {row['type']}...")
            current_type = row["type"]

        add_flashcard_from_db(
            row,
            model=model,
            deck=deck,
            audio_dir=audio_dir,
            media_files=media_files,
            language=language,
            log=log,
        )

    package = genanki.Package(deck)
    package.media_files = media_files
    output = output_dir / f"{safe_filename(anki_name)}.apkg"
    package.write_to_file(str(output))

    log("")
    log(f"Created {output}")
    log(f"{len(rows)} cards")
    log(f"{len(media_files)} audio files")

    test_card_ids = []
    if test_mode and delete_test_entries:
        cursor.execute(
            "SELECT id FROM flashcards WHERE language = ? AND deck_id = ? AND test = 1",
            (language, deck_row["id"]),
        )
        test_card_ids = [row["id"] for row in cursor.fetchall()]

    conn.close()
    if test_card_ids:
        delete_flashcards(language=language, card_ids=test_card_ids, log=log)
    return output


def main():
    languages_config = load_language_configurations(DB_FILE)
    parser = argparse.ArgumentParser(description="Generate Anki deck from database")
    parser.add_argument(
        "--language",
        required=True,
        help=f"Language to generate deck for. Available: {', '.join(languages_config.keys())}",
    )
    parser.add_argument("--test", action="store_true", help="Generate test deck")
    parser.add_argument("--deck", help="Deck name to export. If omitted, the language name is used.")
    parser.add_argument("--deck-id", type=int, help="Deck ID to export.")
    args = parser.parse_args()

    delete_test_entries = False
    if args.test:
        response = input("Delete test entries after export? (y/n): ").strip().lower()
        delete_test_entries = response == "y"

    export_deck(
        language=args.language,
        deck_id=args.deck_id,
        deck_name=args.deck,
        test_mode=args.test,
        delete_test_entries=delete_test_entries,
    )


if __name__ == "__main__":
    main()
