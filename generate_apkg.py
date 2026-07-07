from pathlib import Path
import csv
import random

import genanki

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

INPUT_DIR = Path("input")
AUDIO_DIR = Path("audio")
OUTPUT_DIR = Path("output")

OUTPUT_DIR.mkdir(exist_ok=True)

DECK_NAME = "Japanese"

VOCAB_CSV = INPUT_DIR / "vocabulary.csv"
SENTENCE_CSV = INPUT_DIR / "sentences.csv"

# -----------------------------------------------------------------------------
# Anki model
# -----------------------------------------------------------------------------

MODEL = genanki.Model(
    random.randrange(1 << 30),

    "Japanese Model",

    fields=[
        {"name": "Japanese"},
        {"name": "English"},
        {"name": "Romaji"},
        {"name": "Audio"},
        {"name": "Notes"},
    ],

    templates=[
        {
            "name": "Listening",

            "qfmt": """
{{Audio}}

<div class="jp">
{{Japanese}}
</div>
""",

            "afmt": """
{{FrontSide}}

<hr id="answer">

<div class="en">
{{English}}
</div>

<div class="romaji">
{{Romaji}}
</div>

<div class="notes">
{{Notes}}
</div>
"""
        }
    ],

    css="""
.card {
    font-family: Arial;
    font-size:24px;
    text-align:center;
}

.jp {
    font-size:40px;
}

.en {
    font-size:32px;
    font-weight:bold;
    margin-top:20px;
}

.romaji {
    color:gray;
    margin-top:10px;
}

.notes {
    margin-top:20px;
    font-size:18px;
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

            note = genanki.Note(
                model=MODEL,

                fields=[
                    row["Japanese"],
                    row["English"],
                    row["Romaji"],
                    audio_field,
                    row.get("Notes", "")
                ]
            )

            deck.add_note(note)


print("Adding vocabulary...")
add_csv(VOCAB_CSV)

print("Adding sentences...")
add_csv(SENTENCE_CSV)

package = genanki.Package(deck)
package.media_files = media_files

output = OUTPUT_DIR / "Japanese.apkg"

package.write_to_file(str(output))

print()
print(f"Created {output}")
print(f"{len(media_files)} audio files")