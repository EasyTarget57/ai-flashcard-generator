from pathlib import Path
import csv
import json
import sys
import argparse
import random

import genanki

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Load languages configuration
with open("languages.json", "r", encoding="utf-8") as f:
    LANGUAGES_CONFIG = json.load(f)

# Parse arguments
parser = argparse.ArgumentParser(description="Generate Anki deck for a specific language")
parser.add_argument(
    "--language",
    required=True,
    help=f"Language to generate deck for. Available: {', '.join(LANGUAGES_CONFIG.keys())}"
)
args = parser.parse_args()

LANGUAGE = args.language.lower()
if LANGUAGE not in LANGUAGES_CONFIG:
    print(f"Error: Language '{LANGUAGE}' not found in languages.json")
    print(f"Available languages: {', '.join(LANGUAGES_CONFIG.keys())}")
    sys.exit(1)

LANG_CONFIG = LANGUAGES_CONFIG[LANGUAGE]

INPUT_DIR = Path("input") / LANGUAGE
AUDIO_DIR = Path("audio") / LANGUAGE
OUTPUT_DIR = Path("output") / LANGUAGE

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DECK_NAME = LANG_CONFIG["name"]
MODEL_NAME = LANG_CONFIG["model_name"]
FIELDS = LANG_CONFIG["fields"]

# Verify input directory exists
if not INPUT_DIR.exists():
    print(f"Error: Input directory not found: {INPUT_DIR}")
    sys.exit(1)

# Build CSV paths from config
CSV_FILES = [INPUT_DIR / csv_file for csv_file in LANG_CONFIG["csv_files"]]

# Verify CSV files exist
missing_files = [f for f in CSV_FILES if not f.exists()]
if missing_files:
    print(f"Error: Missing CSV files:")
    for f in missing_files:
        print(f"  - {f}")
    sys.exit(1)

# Verify audio directory exists
if not AUDIO_DIR.exists():
    print(f"Error: Audio directory not found: {AUDIO_DIR}")
    print(f"Please run: python generate_audio.py --language {LANGUAGE}")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Anki model
# -----------------------------------------------------------------------------

# Build model fields from config
field_list = [{"name": field} for field in FIELDS]

# Build question format - show audio and first field
qfmt = f"""
{{{{Audio}}}}

<div class="target">
{{{{{FIELDS[0]}}}}}
</div>
"""

# Build answer format - show remaining fields
afmt = """
{{FrontSide}}

<hr id="answer">

<div class="translations">
"""
for field in FIELDS[1:]:
    if field != "Audio":
        afmt += f'<div class="{field.lower().replace(" ", "_")}">\n{{{{{field}}}}}\n</div>\n'

afmt += """
</div>
"""

MODEL = genanki.Model(
    random.randrange(1 << 30),

    MODEL_NAME,

    fields=field_list,

    templates=[
        {
            "name": "Listening",

            "qfmt": qfmt,

            "afmt": afmt
        }
    ],

    css="""
.card {
    font-family: Arial;
    font-size: 24px;
    text-align: center;
}

.target {
    font-size: 40px;
    margin: 20px 0;
}

.translations {
    font-size: 28px;
    margin-top: 20px;
}

.translations > div {
    margin: 10px 0;
}

.english {
    font-weight: bold;
    color: #333;
}

.romaji {
    color: gray;
    font-size: 18px;
}

.spanish {
    font-weight: bold;
    color: #333;
}

.french {
    font-weight: bold;
    color: #333;
}

.notes {
    margin-top: 20px;
    font-size: 16px;
    color: #666;
}
"""
)

# -----------------------------------------------------------------------------

deck = genanki.Deck(
    random.randrange(1 << 30),
    DECK_NAME
)

media_files = []


def add_csv(csv_file: Path):
    with csv_file.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            audio_filename = f"{row['ID']}.mp3"
            audio_path = AUDIO_DIR / audio_filename

            if audio_path.exists():
                media_files.append(str(audio_path))
                audio_field = f"[sound:{audio_filename}]"
            else:
                print(f"WARNING: Missing {audio_filename}")
                audio_field = ""

            # Build fields based on configuration
            field_values = []
            for field in FIELDS:
                if field == "Audio":
                    field_values.append(audio_field)
                else:
                    field_values.append(row.get(field, ""))

            # Extract source as tag
            tags = []
            if "Source" in row and row["Source"]:
                tags.append(row["Source"])

            note = genanki.Note(
                model=MODEL,
                fields=field_values,
                tags=tags
            )

            deck.add_note(note)


print(f"Creating Anki deck for {LANG_CONFIG['name']}...\n")

for csv_file in CSV_FILES:
    print(f"Adding {csv_file.name}...")
    add_csv(csv_file)

package = genanki.Package(deck)
package.media_files = media_files

output = OUTPUT_DIR / f"{DECK_NAME}.apkg"

package.write_to_file(str(output))

print()
print(f"Created {output}")
print(f"{len(media_files)} audio files")