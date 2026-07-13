"""Runtime filesystem locations for user data."""

import os
import shutil
from pathlib import Path


APP_NAME = "FlashcardGenerator"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_data_dir():
    override = os.getenv("FLASHCARD_GENERATOR_DATA_DIR")
    if override:
        return Path(override).expanduser()

    try:
        from platformdirs import user_data_path

        return user_data_path(APP_NAME, appauthor=False)
    except ImportError:
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APP_NAME
        return Path.home() / ".local" / "share" / APP_NAME


DATA_DIR = _default_data_dir()
DB_FILE = DATA_DIR / "flashcards.db"
INPUT_DIR = DATA_DIR / "input"
AUDIO_ROOT = DATA_DIR / "audio"
OUTPUT_ROOT = DATA_DIR / "output"

REPO_DB_FILE = PROJECT_ROOT / "flashcards.db"
REPO_INPUT_DIR = PROJECT_ROOT / "input"
REPO_AUDIO_ROOT = PROJECT_ROOT / "audio"
REPO_OUTPUT_ROOT = PROJECT_ROOT / "output"


def ensure_data_dirs():
    """Create runtime user-data directories."""
    for path in (DATA_DIR, INPUT_DIR, AUDIO_ROOT, OUTPUT_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def migrate_repo_data_to_user_data():
    """Move legacy repo-local user data to the user-data directory when safe."""
    ensure_data_dirs()
    moved = []
    skipped = []

    for source, destination in (
        (REPO_DB_FILE, DB_FILE),
        (REPO_INPUT_DIR, INPUT_DIR),
        (REPO_AUDIO_ROOT, AUDIO_ROOT),
        (REPO_OUTPUT_ROOT, OUTPUT_ROOT),
    ):
        if not source.exists():
            continue
        if destination.exists() and _has_content(destination):
            skipped.append((source, destination))
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_dir():
                destination.rmdir()
            else:
                destination.unlink()
        try:
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
        except PermissionError:
            if source.is_file() and destination.is_file() and _same_file_size(source, destination):
                skipped.append((source, destination))
                continue
            raise

    return moved, skipped


def _has_content(path):
    if path.is_dir():
        return any(path.iterdir())
    return path.exists() and path.stat().st_size > 0


def _same_file_size(left, right):
    return left.stat().st_size == right.stat().st_size
