"""Safely regenerate audio for existing flashcards."""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from lib.tts_providers import get_tts_audio_extension, get_tts_provider


DB_FILE = Path("flashcards.db")
CONFIG_FILE = Path("languages.json")


def configure_console():
    """Allow non-ASCII text in redirected and legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Regenerate audio for existing flashcards"
    )
    parser.add_argument(
        "--language",
        default="vietnamese",
        help="Language to regenerate from languages.json (default: vietnamese)",
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
    args = parser.parse_args()

    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    args.language = args.language.lower()
    return args


def load_config(language):
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Configuration not found: {CONFIG_FILE}")

    with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
        languages = json.load(config_file)

    if language not in languages:
        available = ", ".join(languages.keys())
        raise ValueError(
            f"Language not configured: {language}. Available: {available}"
        )
    return languages[language]


def is_current_audio(audio_dir, card_id, audio_filename, audio_extension):
    expected_filename = f"{card_id}{audio_extension}"
    expected_path = audio_dir / expected_filename
    return (
        audio_filename == expected_filename
        and expected_path.is_file()
        and expected_path.stat().st_size > 0
    )


def generate_with_retries(provider, text, card_id, staging_dir, retries):
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
            print(f"       retrying in {delay}s ({attempt}/{retries})")
            time.sleep(delay)


def main():
    configure_console()
    args = parse_args()

    if not DB_FILE.exists():
        print(f"Error: Database not found: {DB_FILE}", file=sys.stderr)
        return 1

    try:
        language_config = load_config(args.language)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    audio_dir = Path("audio") / args.language

    connection = sqlite3.connect(str(DB_FILE))
    connection.row_factory = sqlite3.Row
    cards = connection.execute(
        """
        SELECT id, target_language_text, audio_filename
        FROM flashcards
        WHERE language = ?
        ORDER BY id
        """,
        (args.language,),
    ).fetchall()

    provider_name = language_config.get("tts_provider", "openai")
    try:
        audio_extension = get_tts_audio_extension(provider_name)
    except ValueError as error:
        connection.close()
        print(f"Error: {error}", file=sys.stderr)
        return 1

    pending = [
        card for card in cards
        if args.force
        or not is_current_audio(
            audio_dir,
            card["id"],
            card["audio_filename"],
            audio_extension,
        )
    ]
    skipped = len(cards) - len(pending)
    if args.limit is not None:
        pending = pending[:args.limit]

    language_name = language_config.get("name", args.language)
    print(f"{language_name} cards: {len(cards)}")
    print(f"To regenerate: {len(pending)}")
    print(f"Already current: {skipped}")

    if args.dry_run:
        for card in pending:
            print(f"  WOULD GENERATE ID:{card['id']}  {card['target_language_text']}")
        connection.close()
        return 0

    if not pending:
        connection.close()
        print("Nothing to regenerate.")
        return 0

    try:
        provider = get_tts_provider(provider_name, language_config)
    except Exception as error:
        connection.close()
        print(f"Error: Failed to initialize TTS provider: {error}", file=sys.stderr)
        return 1

    audio_dir.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    failed = 0

    with tempfile.TemporaryDirectory(prefix=f"regenerate-{args.language}-") as temp_dir:
        staging_dir = Path(temp_dir)

        for card in pending:
            card_id = card["id"]
            old_filename = card["audio_filename"]
            print(f"  GEN  ID:{card_id}  {card['target_language_text']}")

            try:
                generated_path, new_filename = generate_with_retries(
                    provider,
                    card["target_language_text"],
                    card_id,
                    staging_dir,
                    args.retries,
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
                        (new_filename, card_id, args.language),
                    )

                if old_filename and old_filename != new_filename:
                    old_path = audio_dir / old_filename
                    if old_path.is_file():
                        old_path.unlink()

                succeeded += 1
            except Exception as error:
                failed += 1
                print(f"  ERROR ID:{card_id}: {error}", file=sys.stderr)

    connection.close()
    print(f"\nRegenerated: {succeeded}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
