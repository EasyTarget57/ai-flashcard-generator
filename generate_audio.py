from pathlib import Path
import csv

from openai import OpenAI

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MODEL = "gpt-4o-mini-tts"
VOICE = "coral"
INSTRUCTIONS = (
    "Speak naturally in standard Japanese. "
    "Use clear pronunciation suitable for a beginner learning Japanese."
)

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("audio")

CSV_FILES = [
    INPUT_DIR / "vocabulary.csv",
    INPUT_DIR / "sentences.csv",
]

# -----------------------------------------------------------------------------

client = OpenAI()

OUTPUT_DIR.mkdir(exist_ok=True)


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
            japanese = row["Japanese"]

            output_file = OUTPUT_DIR / f"{id}.mp3"

            if output_file.exists():
                print(f"  SKIP {id}")
                continue

            print(f"  GEN  {id}  {japanese}")

            try:
                generate_audio(japanese, output_file)
            except Exception as e:
                print(f"  ERROR {id}: {e}")


def main():
    for csv_file in CSV_FILES:
        process_csv(csv_file)

    print("\nDone!")


if __name__ == "__main__":
    main()