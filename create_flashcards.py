import sqlite3
import csv
import sys
import argparse
import json
from pathlib import Path
from lib.tts_providers import get_tts_provider

# Load languages configuration
with open("languages.json", "r", encoding="utf-8") as f:
    LANGUAGES_CONFIG = json.load(f)

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
    help="Specific CSV file to import. If not provided, imports all CSVs in input/{language}/"
)
parser.add_argument(
    "--test",
    action="store_true",
    help="Mark flashcards as test entries (creates test deck for dry-run)"
)
args = parser.parse_args()

LANGUAGE = args.language.lower()
SOURCE = args.source
CUSTOM_CSV = args.csv
TEST_MODE = args.test

# Validate language
if LANGUAGE not in LANGUAGES_CONFIG:
    print(f"Error: Language '{LANGUAGE}' not found in languages.json")
    print(f"Available languages: {', '.join(LANGUAGES_CONFIG.keys())}")
    sys.exit(1)

LANG_CONFIG = LANGUAGES_CONFIG[LANGUAGE]
INPUT_DIR = Path("input")
AUDIO_DIR = Path("audio") / LANGUAGE
DB_FILE = Path("flashcards.db")

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
if CUSTOM_CSV:
    csv_files = [INPUT_DIR / CUSTOM_CSV]
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


def import_csv(csv_file: Path):
    """Import CSV file into database and generate audio."""
    csv_type = csv_file.stem  # filename without extension

    print(f"\nProcessing {csv_file.name}...")
    imported_count = 0
    failed_count = 0

    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                # Use standardized column names
                target_text = row.get("Front", "").strip()
                translation = row.get("Back", "").strip()
                pronunciation = row.get("Pronunciation", "").strip() if "Pronunciation" in row else None
                notes = row.get("Notes", "").strip() if "Notes" in row else None

                if not target_text or not translation:
                    print(f"  SKIP: Missing Front or Back")
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

            except Exception as e:
                print(f"  ERROR: {e}")
                failed_count += 1
                continue

    conn.close()

    print(f"\nImported: {imported_count} cards")
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
