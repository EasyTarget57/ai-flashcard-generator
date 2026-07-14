import sqlite3
import time
from pathlib import Path

from lib.paths import AUDIO_ROOT, DB_FILE, ensure_data_dirs


def normalize_card_ids(card_ids):
    if card_ids is None:
        return None
    normalized = []
    seen = set()
    for value in card_ids:
        card_id = int(value)
        if card_id < 1:
            raise ValueError("Card IDs must be positive integers")
        if card_id not in seen:
            normalized.append(card_id)
            seen.add(card_id)
    return normalized


def delete_flashcards(*, language, card_ids, db_file=DB_FILE, audio_root=AUDIO_ROOT, log=print):
    ensure_data_dirs()
    language = language.lower()
    card_ids = normalize_card_ids(card_ids)
    if not card_ids:
        log("No cards selected.")
        return {"deleted_cards": 0, "deleted_audio": 0, "missing_audio": 0, "failed_audio": 0}

    placeholders = ", ".join("?" for _ in card_ids)
    params = [language, *card_ids]

    connection = sqlite3.connect(str(db_file))
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        f"""
        SELECT id, audio_filename
        FROM flashcards
        WHERE language = ? AND id IN ({placeholders})
        """,
        params,
    ).fetchall()

    if not rows:
        connection.close()
        log("No matching cards found.")
        return {"deleted_cards": 0, "deleted_audio": 0, "missing_audio": 0, "failed_audio": 0}

    with connection:
        connection.execute(
            f"DELETE FROM flashcards WHERE language = ? AND id IN ({placeholders})",
            params,
        )
    connection.close()

    audio_dir = Path(audio_root) / language
    deleted_audio = 0
    missing_audio = 0
    failed_audio = 0
    for row in rows:
        filename = row["audio_filename"]
        if not filename:
            continue
        audio_path = audio_dir / filename
        if audio_path.is_file():
            try:
                if unlink_with_retries(audio_path):
                    deleted_audio += 1
            except PermissionError:
                failed_audio += 1
                log(f"WARNING: Audio file is still in use and could not be deleted: {audio_path}")
        else:
            missing_audio += 1

    log(f"Deleted {len(rows)} cards")
    log(f"Deleted {deleted_audio} audio files")
    if missing_audio:
        log(f"Missing audio files: {missing_audio}")
    if failed_audio:
        log(f"Audio files still in use: {failed_audio}")
    return {
        "deleted_cards": len(rows),
        "deleted_audio": deleted_audio,
        "missing_audio": missing_audio,
        "failed_audio": failed_audio,
    }


def unlink_with_retries(path, retries=8, delay=0.15):
    for attempt in range(retries + 1):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            if attempt == retries:
                raise
            time.sleep(delay)
