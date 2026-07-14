import argparse
import csv
import sqlite3
from pathlib import Path

from lib.db import init_database
from lib.decks import default_deck_name, ensure_deck_schema, get_or_create_deck, normalized_deck_name
from lib.language_config import load_language_configurations
from lib.paths import AUDIO_ROOT, DB_FILE, INPUT_DIR, ensure_data_dirs
from lib.tts_providers import get_tts_provider


def ensure_indexes(cursor: sqlite3.Cursor) -> None:
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_flashcards_language_target_text
        ON flashcards (language, target_language_text)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_flashcards_deck_target_text
        ON flashcards (deck_id, target_language_text)
    """)


def load_existing_fronts(cursor: sqlite3.Cursor, language: str, target_texts: set[str], deck_id: int) -> set[str]:
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
              AND deck_id = ?
              AND target_language_text IN ({placeholders})
            """,
            (language, deck_id, *chunk),
        )
        existing_fronts.update(row[0] for row in cursor.fetchall())

    return existing_fronts


def import_csv(
    csv_file: Path,
    *,
    language: str,
    source: str | None,
    test_mode: bool,
    deck_id: int,
    audio_dir: Path,
    tts_provider,
    log=print,
):
    csv_type = csv_file.stem

    log(f"\nProcessing {csv_file.name}...")
    imported_count = 0
    skipped_count = 0
    failed_count = 0

    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    ensure_deck_schema(cursor)
    ensure_indexes(cursor)
    conn.commit()

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    incoming_fronts = {row.get("Front", "").strip() for row in rows}
    incoming_fronts.discard("")
    existing_fronts = load_existing_fronts(cursor, language, incoming_fronts, deck_id)

    for row in rows:
        flashcard_id = None
        try:
            target_text = row.get("Front", "").strip()
            translation = row.get("Back", "").strip()
            pronunciation = row.get("Pronunciation", "").strip() if "Pronunciation" in row else None
            notes = row.get("Notes", "").strip() if "Notes" in row else None

            if not target_text or not translation:
                log("  SKIP: Missing Front or Back")
                skipped_count += 1
                continue

            if target_text in existing_fronts:
                log(f"  SKIP: Duplicate Front for {language} / deck {deck_id}: {target_text}")
                skipped_count += 1
                continue

            cursor.execute(
                """
                INSERT INTO flashcards
                (language, type, target_language_text, translation, pronunciation, source, notes, deck_id, test)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (language, csv_type, target_text, translation, pronunciation, source, notes, deck_id, test_mode),
            )
            conn.commit()

            flashcard_id = cursor.lastrowid
            log(f"  GEN  ID:{flashcard_id}  {target_text}")
            audio_filename = tts_provider.generate_audio(target_text, flashcard_id, audio_dir)

            cursor.execute(
                "UPDATE flashcards SET audio_filename = ? WHERE id = ?",
                (audio_filename, flashcard_id),
            )
            conn.commit()

            imported_count += 1
            existing_fronts.add(target_text)

        except Exception as error:
            if flashcard_id is not None:
                cursor.execute("DELETE FROM flashcards WHERE id = ?", (flashcard_id,))
                conn.commit()
            log(f"  ERROR: {error}")
            failed_count += 1

    conn.close()

    log(f"\nImported: {imported_count} cards")
    if skipped_count > 0:
        log(f"Skipped: {skipped_count} cards")
    if failed_count > 0:
        log(f"Failed: {failed_count} cards")

    if imported_count > 0 and failed_count == 0 and not test_mode:
        csv_file.unlink()
        log(f"Deleted: {csv_file.name}")
    elif test_mode:
        log(f"Test mode: Kept {csv_file.name} for potential production import")

    return imported_count, failed_count


def import_flashcards(
    *,
    language: str,
    csv_names: list[str] | None = None,
    source: str | None = None,
    deck_name: str | None = None,
    test_mode: bool = False,
    log=print,
):
    ensure_data_dirs()
    init_database(verbose=False)

    language = language.lower()
    languages_config = load_language_configurations(DB_FILE)
    if language not in languages_config:
        raise ValueError(f"Language '{language}' not found in language_configuration")

    language_config = languages_config[language]
    audio_dir = AUDIO_ROOT / language
    audio_dir.mkdir(parents=True, exist_ok=True)

    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"Input directory not found: {INPUT_DIR}")

    csv_files = [INPUT_DIR / name for name in csv_names] if csv_names else list(INPUT_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {INPUT_DIR}")

    provider_name = language_config.get("tts_provider", "openai")
    tts_provider = get_tts_provider(provider_name, language_config)

    log(f"Importing flashcards for {language_config['name']}...\n")
    if source:
        log(f"Source: {source}\n")

    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    ensure_deck_schema(cursor)
    deck = get_or_create_deck(cursor, language, normalized_deck_name(deck_name) or default_deck_name(language_config))
    conn.commit()
    conn.close()

    deck_id = deck[0]
    log(f"Deck: {deck[2]}\n")

    total_imported = 0
    total_failed = 0
    for csv_file in csv_files:
        imported, failed = import_csv(
            csv_file,
            language=language,
            source=source,
            test_mode=test_mode,
            deck_id=deck_id,
            audio_dir=audio_dir,
            tts_provider=tts_provider,
            log=log,
        )
        total_imported += imported
        total_failed += failed

    log(f"\n{'=' * 50}")
    log(f"Total imported: {total_imported}")
    log(f"Total failed: {total_failed}")
    log(f"{'=' * 50}")

    if total_failed == 0 and total_imported > 0:
        log("\nAll cards successfully imported and audio generated!")
    elif total_failed > 0:
        raise RuntimeError(f"{total_failed} cards failed. Please check the errors above.")

    return {
        "imported": total_imported,
        "failed": total_failed,
        "deck_id": deck_id,
        "deck_name": deck[2],
    }


def main():
    languages_config = load_language_configurations(DB_FILE)
    parser = argparse.ArgumentParser(description="Import flashcards from CSV and generate audio")
    parser.add_argument(
        "--language",
        required=True,
        help=f"Language of the flashcards. Available: {', '.join(languages_config.keys())}",
    )
    parser.add_argument("--source", help="Source identifier (e.g., YouTube video ID)")
    parser.add_argument("--deck", help="Deck name. If omitted or empty, the language name is used.")
    parser.add_argument(
        "--csv",
        action="append",
        help="Specific CSV file in the user-data input folder. Repeat to import multiple files.",
    )
    parser.add_argument("--test", action="store_true", help="Mark flashcards as test entries")
    args = parser.parse_args()

    import_flashcards(
        language=args.language,
        csv_names=args.csv,
        source=args.source,
        deck_name=args.deck,
        test_mode=args.test,
    )


if __name__ == "__main__":
    main()
