"""Safely regenerate audio for existing flashcards."""

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.flashcards import normalize_card_ids
from lib.language_config import load_language_configuration
from lib.paths import AUDIO_ROOT, DB_FILE, ensure_data_dirs
from lib.tts_providers import get_tts_audio_extension, get_tts_provider

ensure_data_dirs()


def configure_console():
    """Allow non-ASCII text in redirected and legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def parse_card_ids(values):
    if values is None:
        return None
    card_ids = []
    for value in values:
        card_ids.extend(part.strip() for part in value.split(",") if part.strip())
    return normalize_card_ids(card_ids)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Regenerate audio for existing flashcards"
    )
    parser.add_argument(
        "--language",
        default="vietnamese",
        help="Language to regenerate from language_configuration (default: vietnamese)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which cards would be processed without generating or changing anything",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate cards that already have the current audio filename",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of retries after a failed request (default: 2)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Process at most this many cards (useful for testing)",
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        help="Only process these card IDs",
    )
    args = parser.parse_args()

    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    try:
        args.ids = parse_card_ids(args.ids)
    except ValueError as error:
        parser.error(str(error))
    args.language = args.language.lower()
    return args


def is_current_audio(audio_dir, card_id, audio_filename, audio_extension):
    expected_filename = f"{card_id}{audio_extension}"
    expected_path = audio_dir / expected_filename
    return (
        audio_filename == expected_filename
        and expected_path.is_file()
        and expected_path.stat().st_size > 0
    )


def generate_with_retries(provider, text, card_id, staging_dir, retries, log=print):
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            filename = provider.generate_audio(text, card_id, staging_dir)
            generated_path = staging_dir / filename
            if not generated_path.is_file() or generated_path.stat().st_size == 0:
                raise RuntimeError("TTS provider returned an empty audio file")
            return generated_path, filename
        except Exception:
            if attempt == attempts:
                raise
            delay = min(2 ** (attempt - 1), 8)
            log(f"       retrying in {delay}s ({attempt}/{retries})")
            time.sleep(delay)


def regenerate_audio(
    *,
    language,
    card_ids=None,
    tts_provider=None,
    tts_config=None,
    audio_text_by_id=None,
    dry_run=False,
    force=False,
    retries=2,
    limit=None,
    db_file=DB_FILE,
    audio_root=AUDIO_ROOT,
    log=print,
):
    ensure_data_dirs()
    language = language.lower()
    card_ids = normalize_card_ids(card_ids)
    if retries < 0:
        raise ValueError("retries cannot be negative")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    if not Path(db_file).exists():
        raise FileNotFoundError(f"Database not found: {db_file}")

    language_config = load_language_configuration(language, db_file)
    if tts_config:
        language_config.update(tts_config)
    provider_name = tts_provider or language_config.get("tts_provider", "openai")
    language_config["tts_provider"] = provider_name
    audio_text_by_id = {int(card_id): text for card_id, text in (audio_text_by_id or {}).items()}
    audio_dir = Path(audio_root) / language

    connection = sqlite3.connect(str(db_file))
    connection.row_factory = sqlite3.Row
    where = "language = ?"
    params = [language]
    if card_ids is not None:
        if not card_ids:
            log("No cards selected.")
            connection.close()
            return {"regenerated": 0, "failed": 0, "skipped": 0}
        placeholders = ", ".join("?" for _ in card_ids)
        where += f" AND id IN ({placeholders})"
        params.extend(card_ids)
    cards = connection.execute(
        f"""
        SELECT id, target_language_text, audio_filename
        FROM flashcards
        WHERE {where}
        ORDER BY id
        """,
        params,
    ).fetchall()

    audio_extension = get_tts_audio_extension(provider_name)

    pending = [
        card for card in cards
        if force
        or not is_current_audio(
            audio_dir,
            card["id"],
            card["audio_filename"],
            audio_extension,
        )
    ]
    skipped = len(cards) - len(pending)
    if limit is not None:
        pending = pending[:limit]

    language_name = language_config.get("name", language)
    log(f"{language_name} cards: {len(cards)}")
    log(f"To regenerate: {len(pending)}")
    log(f"Already current: {skipped}")

    if dry_run:
        for card in pending:
            text = audio_text_by_id.get(card["id"], card["target_language_text"])
            log(f"  WOULD GENERATE ID:{card['id']}  {text}")
        connection.close()
        return {"regenerated": 0, "failed": 0, "skipped": skipped}

    if not pending:
        connection.close()
        log("Nothing to regenerate.")
        return {"regenerated": 0, "failed": 0, "skipped": skipped}

    provider = get_tts_provider(provider_name, language_config)

    audio_dir.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    failed = 0

    with tempfile.TemporaryDirectory(prefix=f"regenerate-{language}-") as temp_dir:
        staging_dir = Path(temp_dir)

        for card in pending:
            card_id = card["id"]
            old_filename = card["audio_filename"]
            audio_text = audio_text_by_id.get(card_id, card["target_language_text"])
            log(f"  GEN  ID:{card_id}  {audio_text}")

            try:
                generated_path, new_filename = generate_with_retries(
                    provider,
                    audio_text,
                    card_id,
                    staging_dir,
                    retries,
                    log=log,
                )
                final_path = audio_dir / new_filename
                os.replace(generated_path, final_path)

                with connection:
                    connection.execute(
                        """
                        UPDATE flashcards
                        SET audio_filename = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND language = ?
                        """,
                        (new_filename, card_id, language),
                    )

                if old_filename and old_filename != new_filename:
                    old_path = audio_dir / old_filename
                    if old_path.is_file():
                        old_path.unlink()

                succeeded += 1
            except Exception as error:
                failed += 1
                log(f"  ERROR ID:{card_id}: {error}")

    connection.close()
    log(f"\nRegenerated: {succeeded}")
    log(f"Failed: {failed}")
    log(f"Skipped: {skipped}")
    return {"regenerated": succeeded, "failed": failed, "skipped": skipped}


def main():
    configure_console()
    args = parse_args()

    try:
        result = regenerate_audio(
            language=args.language,
            card_ids=args.ids,
            dry_run=args.dry_run,
            force=args.force,
            retries=args.retries,
            limit=args.limit,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    failed = result.get("failed", 0)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
