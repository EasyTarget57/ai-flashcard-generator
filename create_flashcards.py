import sqlite3
import csv
import sys
import argparse
from pathlib import Path
from lib.language_config import load_language_configurations
from lib.paths import AUDIO_ROOT, DB_FILE, INPUT_DIR, ensure_data_dirs
from lib.tts_providers import get_tts_provider


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)


ensure_data_dirs()

try:
    LANGUAGES_CONFIG = load_language_configurations(DB_FILE)
except Exception as e:
    print(f"Error: Failed to load language configuration: {e}")
    sys.exit(1)

# Parse arguments
parser = argparse.ArgumentParser(description="Import flashcards from CSV and generate audio")
parser.add_argument(
    "--language",
    required=True,
    help=f"Language of the flashcards. Available: {', '.join(LANGUAGES_CONFIG.keys())}"
)
parser.add_argument(
    "--source",
    help="Source identifier (e.g., YouTube video ID)"
)
parser.add_argument(
    "--csv",
    action="append",
    help="Specific CSV file in the user-data input folder. Repeat to import multiple files. If not provided, imports all CSVs there."
)
parser.add_argument(
    "--test",
    action="store_true",
    help="Mark flashcards as test entries (creates test deck for dry-run)"
)
args = parser.parse_args()

LANGUAGE = args.language.lower()
SOURCE = args.source
CUSTOM_CSVS = args.csv or []
TEST_MODE = args.test

# Validate language
if LANGUAGE not in LANGUAGES_CONFIG:
    print(f"Error: Language '{LANGUAGE}' not found in language_configuration")
    print(f"Available languages: {', '.join(LANGUAGES_CONFIG.keys())}")
    sys.exit(1)

LANG_CONFIG = LANGUAGES_CONFIG[LANGUAGE]
AUDIO_DIR = AUDIO_ROOT / LANGUAGE

# Create directories
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Verify input directory exists
if not INPUT_DIR.exists():
    print(f"Error: Input directory not found: {INPUT_DIR}")
    sys.exit(1)

# Verify database exists
if not DB_FILE.exists():
    print(f"Error: Database not found: {DB_FILE}")
    print("Please run: python init_db.py")
    sys.exit(1)

# Get CSV files to process
if CUSTOM_CSVS:
    csv_files = [INPUT_DIR / csv_name for csv_name in CUSTOM_CSVS]
else:
    csv_files = list(INPUT_DIR.glob("*.csv"))

if not csv_files:
    print(f"Error: No CSV files found in {INPUT_DIR}")
    sys.exit(1)

# Initialize TTS provider
provider_name = LANG_CONFIG.get("tts_provider", "openai")
try:
    tts_provider = get_tts_provider(provider_name, LANG_CONFIG)
except Exception as e:
    print(f"Error: Failed to initialize TTS provider: {e}")
    sys.exit(1)


def generate_audio(text: str, audio_id: int) -> str:
    """Generate MP3 file for a flashcard and return filename."""
    try:
        return tts_provider.generate_audio(text, audio_id, AUDIO_DIR)
    except Exception as e:
        raise Exception(f"Audio generation failed: {e}")


def ensure_indexes(cursor: sqlite3.Cursor) -> None:
    """Create indexes needed by import-time lookups."""
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_flashcards_language_target_text
        ON flashcards (language, target_language_text)
    """)


def load_existing_fronts(cursor: sqlite3.Cursor, target_texts: set[str]) -> set[str]:
    """Load existing front text matching incoming rows for the selected language."""
    if not target_texts:
        return set()

    existing_fronts = set()
    text_list = list(target_texts)
    chunk_size = 900

    for i in range(0, len(text_list), chunk_size):
        chunk = text_list[i:i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(
            f"""
            SELECT target_language_text
            FROM flashcards
            WHERE language = ?
              AND target_language_text IN ({placeholders})
            """,
            (LANGUAGE, *chunk)
        )
        existing_fronts.update(row[0] for row in cursor.fetchall())

    return existing_fronts


def import_csv(csv_file: Path):
    """Import CSV file into database and generate audio."""
    csv_type = csv_file.stem  # filename without extension

    print(f"\nProcessing {csv_file.name}...")
    imported_count = 0
    skipped_count = 0
    failed_count = 0

    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    ensure_indexes(cursor)
    conn.commit()

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    incoming_fronts = {row.get("Front", "").strip() for row in rows}
    incoming_fronts.discard("")
    existing_fronts = load_existing_fronts(cursor, incoming_fronts)

    for row in rows:
        flashcard_id = None
        try:
            # Use standardized column names
            target_text = row.get("Front", "").strip()
            translation = row.get("Back", "").strip()
            pronunciation = row.get("Pronunciation", "").strip() if "Pronunciation" in row else None
            notes = row.get("Notes", "").strip() if "Notes" in row else None

            if not target_text or not translation:
                print(f"  SKIP: Missing Front or Back")
                skipped_count += 1
                continue

            if target_text in existing_fronts:
                print(f"  SKIP: Duplicate Front for {LANGUAGE}: {target_text}")
                skipped_count += 1
                continue

            # Insert into database
            cursor.execute("""
                INSERT INTO flashcards
                (language, type, target_language_text, translation, pronunciation, source, notes, test)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (LANGUAGE, csv_type, target_text, translation, pronunciation, SOURCE, notes, TEST_MODE))

            conn.commit()

            # Get the auto-generated ID
            flashcard_id = cursor.lastrowid

            # Generate audio
            print(f"  GEN  ID:{flashcard_id}  {target_text}")
            audio_filename = generate_audio(target_text, flashcard_id)

            # Update database with audio filename
            cursor.execute(
                "UPDATE flashcards SET audio_filename = ? WHERE id = ?",
                (audio_filename, flashcard_id)
            )
            conn.commit()

            imported_count += 1
            existing_fronts.add(target_text)

        except Exception as e:
            if flashcard_id is not None:
                cursor.execute("DELETE FROM flashcards WHERE id = ?", (flashcard_id,))
                conn.commit()
            print(f"  ERROR: {e}")
            failed_count += 1
            continue

    conn.close()

    print(f"\nImported: {imported_count} cards")
    if skipped_count > 0:
        print(f"Skipped: {skipped_count} cards")
    if failed_count > 0:
        print(f"Failed: {failed_count} cards")

    # Delete CSV file if import was successful (skip in test mode)
    if imported_count > 0 and failed_count == 0 and not TEST_MODE:
        csv_file.unlink()
        print(f"Deleted: {csv_file.name}")
    elif TEST_MODE:
        print(f"Test mode: Kept {csv_file.name} for potential production import")

    return imported_count, failed_count


def main():
    print(f"Importing flashcards for {LANG_CONFIG['name']}...\n")
    if SOURCE:
        print(f"Source: {SOURCE}\n")

    total_imported = 0
    total_failed = 0

    for csv_file in csv_files:
        imported, failed = import_csv(csv_file)
        total_imported += imported
        total_failed += failed

    print(f"\n{'='*50}")
    print(f"Total imported: {total_imported}")
    print(f"Total failed: {total_failed}")
    print(f"{'='*50}")

    if total_failed == 0 and total_imported > 0:
        print("\n✓ All cards successfully imported and audio generated!")
    elif total_failed > 0:
        print(f"\n⚠ {total_failed} cards failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
