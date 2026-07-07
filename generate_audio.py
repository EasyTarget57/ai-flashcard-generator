from pathlib import Path
import csv
import json
import sys
import argparse

from openai import OpenAI

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MODEL = "gpt-4o-mini-tts"

# Load languages configuration
with open("languages.json", "r", encoding="utf-8") as f:
    LANGUAGES_CONFIG = json.load(f)

# Parse arguments
parser = argparse.ArgumentParser(description="Generate audio for flashcards in a specific language")
parser.add_argument(
    "--language",
    required=True,
    help=f"Language to generate audio for. Available: {', '.join(LANGUAGES_CONFIG.keys())}"
)
args = parser.parse_args()

LANGUAGE = args.language.lower()
if LANGUAGE not in LANGUAGES_CONFIG:
    print(f"Error: Language '{LANGUAGE}' not found in languages.json")
    print(f"Available languages: {', '.join(LANGUAGES_CONFIG.keys())}")
    sys.exit(1)

LANG_CONFIG = LANGUAGES_CONFIG[LANGUAGE]
VOICE = LANG_CONFIG["voice"]
INSTRUCTIONS = LANG_CONFIG["instructions"]

INPUT_DIR = Path("input") / LANGUAGE
OUTPUT_DIR = Path("audio") / LANGUAGE

CSV_FILES = [
    INPUT_DIR / csv_file for csv_file in LANG_CONFIG["csv_files"]
]

# Verify input directory exists
if not INPUT_DIR.exists():
    print(f"Error: Input directory not found: {INPUT_DIR}")
    sys.exit(1)

# Verify CSV files exist
missing_files = [f for f in CSV_FILES if not f.exists()]
if missing_files:
    print(f"Error: Missing CSV files:")
    for f in missing_files:
        print(f"  - {f}")
    sys.exit(1)

# -----------------------------------------------------------------------------

client = OpenAI()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# The first field is the one to generate audio for
TARGET_FIELD = LANG_CONFIG["fields"][0]


def generate_audio(text: str, output_file: Path):
    """Generate one MP3 file."""

    with client.audio.speech.with_streaming_response.create(
        model=MODEL,
        voice=VOICE,
        input=text,
        instructions=INSTRUCTIONS,
    ) as response:
        response.stream_to_file(output_file)


def process_csv(csv_file: Path):
    print(f"\nProcessing {csv_file.name}")

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            id = row["ID"]
            target_text = row[TARGET_FIELD]

            output_file = OUTPUT_DIR / f"{id}.mp3"

            if output_file.exists():
                print(f"  SKIP {id}")
                continue

            print(f"  GEN  {id}  {target_text}")

            try:
                generate_audio(target_text, output_file)
            except Exception as e:
                print(f"  ERROR {id}: {e}")


def main():
    print(f"\nGenerating audio for {LANG_CONFIG['name']}...\n")
    for csv_file in CSV_FILES:
        process_csv(csv_file)

    print("\nDone!")


if __name__ == "__main__":
    main()