# AI Flashcard Generator

Generate Anki flashcards with high-quality AI-generated audio for multiple languages using SQLite for persistent storage.

Currently supports:
- Vocabulary flashcards
- Sentence flashcards
- OpenAI, FPT.AI, and Microsoft Edge Text-to-Speech
- Anki `.apkg` generation
- **Multi-language support** (Japanese, Spanish, French, and more)
- **Database storage** (SQLite with auto-generated card IDs)
- **Test mode** (dry-run imports before production)

---

# Requirements

## 1. API Keys

### OpenAI

OpenAI-backed languages require an OpenAI API key in the following environment variable:

```
OPENAI_API_KEY
```

### Vietnamese (FPT.AI)

Vietnamese audio uses FPT.AI. Copy your API key from the
[FPT Marketplace API Keys page](https://marketplace.fptcloud.com/en/my-account?tab=my-api-key)
and set it as the following environment variable:

```
FPTAI_API_KEY
```

### Japanese (Edge TTS)

Japanese audio uses the `edge-tts` Python package by default. It does not require
an API key, but it does require internet access to Microsoft's Edge online TTS
service.

---

## 2. Python

Python 3.11+ is recommended.

---

## 3. Install dependencies

```
pip install openai genanki requests edge-tts platformdirs
```

or

```
pip install -r requirements.txt
```

---

# Usage

## Desktop UI

Run the PySide6 desktop app:

```
python app.py
```

The UI uses the same user-data directory and scripts as the CLI workflow. It can
browse flashcards, paste/import `vocabulary.csv` and `sentences.csv`, export
Anki decks, and edit non-secret TTS settings. API keys are still read from
environment variables.

---

## Step 0 - Initialize Database (First Time Only)

```
python init_db.py
```

This creates `flashcards.db` with the schema.
Runtime data is stored outside the repository in the OS user-data directory.

Default locations:

```
Windows: C:\Users\<you>\AppData\Local\FlashcardGenerator\
macOS:   ~/Library/Application Support/FlashcardGenerator/
Linux:   ~/.local/share/FlashcardGenerator/
```

Set `FLASHCARD_GENERATOR_DATA_DIR` to override this location.

---

## Step 1 - Prepare input folder

`init_db.py` creates the user-data `input/` folder automatically. This folder is
temporary for the current CLI workflow and will be phased out once the app UI
accepts pasted CSV directly.

---

## Step 2 - Download subtitles

Download subtitles from a YouTube video.

For example: https://subtitle.to/

Download them as **TXT**.

---

## Step 3 - Generate the CSV files

Use ChatGPT (or another LLM) with the following prompt.

---

### Prompt Template

You are creating flashcards for a complete beginner learning [Language].

Given the following transcript:

1. Extract the most useful beginner vocabulary.
2. Ignore filler words and excessive repetition.
3. Create two CSV files with standardized columns.

**Vocabulary CSV** (`vocabulary.csv`):

Columns:
```
Front,Back,Pronunciation,Notes
```

Example for Japanese:
```
ハサミ,scissors,hasami,noun
紙,paper,kami,noun
```

Example for Vietnamese (no pronunciation):
```
Front,Back,Notes
cái kéo,scissors,noun
tờ giấy,paper,noun
```

**Sentences CSV** (`sentences.csv`):

Columns:
```
Front,Back,Pronunciation
```

Example for Japanese:
```
これは何ですか。,What is this?,Kore wa nan desu ka?
わかりません。,I don't know.,Wakarimasen.
```

Example for Spanish (no pronunciation):
```
¿Qué es esto?,What is this?
No sé.,I don't know.
```

Guidelines:

- Front: text in the language being learned.
- Back: English translation.
- Pronunciation is optional. Use romaji for Japanese. Leave it empty if not needed.
- Notes is optional and may contain useful context such as noun, verb, grammar, or usage notes.
- Extract useful vocabulary from the source material.
- Prefer the base/dictionary form of verbs for vocabulary cards.
- Ignore filler words and unnecessary repetition.
- Remove duplicate cards.
- Preserve natural sentences from the source material when useful.
- You may also create natural example sentences that demonstrate vocabulary in different contexts.
- Prefer useful, natural flashcards over trying to reach a specific number of cards.
- Return valid CSV.

---

### Notes:
- **Front** column is used for audio generation
- **Back**, **Pronunciation**, and **Notes** columns are stored as-is in the database
- **Pronunciation** and **Notes** are optional columns (omit if not applicable)

---

## Step 4 - Copy CSV files to input folder

Copy your CSV files to:

```
<user-data-dir>/input/
```

Example:
```
C:\Users\<you>\AppData\Local\FlashcardGenerator\input\vocabulary.csv
C:\Users\<you>\AppData\Local\FlashcardGenerator\input\sentences.csv
```

---

## Step 5 - Import flashcards and generate audio

### Test mode (recommended first step)

Test your CSV and audio generation before importing into production:

```
python create_flashcards.py --language japanese --csv sentences.csv --test
```

This will:
1. Import cards and generate audio marked as test entries
2. Keep the CSV file for later production import
3. Allow you to verify quality before committing

---

### Production import

Once you're satisfied with the test deck, run the same import without `--test`:

```
python create_flashcards.py --language japanese --csv sentences.csv --source WV6BmI6d_HU
```

This will:
1. Read CSV files from the user-data `input/` folder
2. Skip rows whose **Front** exactly matches an existing card in the same language
3. Save each new card to the user-data `flashcards.db` (auto-generates ID)
4. Generate MP3 audio for each new card
5. Delete CSV files (only if all imports succeeded)
6. Store audio files in the user-data `audio/japanese/` folder

**Arguments:**
- `--language` (required): Language to import (japanese, spanish, french, etc.)
- `--source` (optional): Source identifier (e.g., YouTube video ID) - appears as tag in Anki
- `--csv` (optional): Specific CSV file to import (if not provided, imports all CSVs)
- `--test` (optional): Mark entries as test for dry-run verification

**Examples:**

```bash
# Test import first
python create_flashcards.py --language japanese --csv sentences.csv --test

# Generate test deck to verify
python generate_apkg.py --language japanese --test

# Once satisfied, import for production
python create_flashcards.py --language japanese --source WV6BmI6d_HU

# Import all CSVs in the user-data input folder
python create_flashcards.py --language japanese --source WV6BmI6d_HU

# Import specific CSV
python create_flashcards.py --language spanish --csv vocabulary.csv --source abc123

# Import without source tag
python create_flashcards.py --language french
```

---

## Optional - Regenerate existing audio

To regenerate audio for existing cards after changing a language's TTS provider
or voice:

```bash
python regenerate_audio.py --language japanese --force
```

Use `--dry-run` first to preview the affected cards:

```bash
python regenerate_audio.py --language japanese --force --dry-run
```

---

## Step 6 - Generate the Anki deck

Run the deck generation script:

```
python generate_apkg.py --language japanese
```

This will:
1. Query all flashcards for Japanese from the database
2. Build the Anki deck with audio files
3. Create the `.apkg` file in the user-data `output/japanese/` folder

The generated deck will be at:

```
<user-data-dir>/output/japanese/Japanese.apkg
```

**Arguments:**
- `--language` (required): Language to generate deck for
- `--test` (optional): Generate test deck and clean up test entries after creation

When using `--test`, the deck name will have a `-test` suffix (e.g., `Japanese-test.apkg`). After generation, you'll be prompted to confirm deletion of all test entries and their audio files.

---

## Step 7 - Import into Anki

Open Anki.

Double-click the generated `.apkg` file.

The deck will automatically import with audio and source tags.

---

# Project Structure

```
languages.json                    (seed data for language configuration)

init_db.py                        (initialize database)
create_flashcards.py              (import CSVs and generate audio)
generate_apkg.py                  (create Anki deck from database)
```

User data lives outside the repository:

```
FlashcardGenerator/
  flashcards.db
  input/
    *.csv
  audio/
    japanese/
    spanish/
  output/
    japanese/
    spanish/
```

---

# Configuration

Language configuration is stored in the `language_configuration` table in
`flashcards.db`. `init_db.py` seeds missing rows from `languages.json` without
overwriting rows that already exist, so future UI edits can safely write to the
database.

Example row:

```sql
SELECT language, name, tts_provider, tts_voice, tts_rate, tts_volume, tts_pitch
FROM language_configuration
WHERE language = 'japanese';
```

### Configuration Fields:
- **language**: Language key used by CLI commands, audio folders, and deck IDs
- **name**: Display name for the deck
- **tts_provider**: TTS backend to use (`openai`, `fptai`, or `edge`)
- **tts_voice**: Voice name for the selected provider
- **tts_speed**: FPT.AI speech speed, such as `0.85` or `1.0`
- **tts_rate**: Edge TTS speech rate, such as `+0%`, `-10%`, or `+15%`
- **tts_volume**: Edge TTS volume, such as `+0%`, `-10%`, or `+15%`
- **tts_pitch**: Edge TTS pitch, such as `+0Hz`, `-20Hz`, or `+20Hz`
- **instructions**: Instructions for the text-to-speech model
- **model_name**: Name of the Anki model
- **csv_files**: JSON array of CSV file names for this language

For Edge TTS, list available voices with:

```bash
edge-tts --list-voices
```

Common Japanese Edge voices include `ja-JP-NanamiNeural` and
`ja-JP-KeitaNeural`.

### CSV Format:
All CSV files use standardized columns:
- **Front** (required): Text in target language
- **Back** (required): English translation
- **Pronunciation** (optional): Romanization or IPA
- **Notes** (optional): Additional information

---

# Database Schema

The `flashcards` table stores all flashcards:

```sql
CREATE TABLE flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    type TEXT NOT NULL,
    target_language_text TEXT NOT NULL,
    translation TEXT NOT NULL,
    pronunciation TEXT,
    source TEXT,
    notes TEXT,
    audio_filename TEXT,
    test BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- **id**: Auto-generated unique ID for each card
- **language**: Language code (japanese, spanish, etc.)
- **type**: Card type from CSV filename (vocabulary, sentences, etc.)
- **target_language_text**: Text in the target language (Japanese, Spanish, etc.)
- **translation**: English translation
- **pronunciation**: Pronunciation (Romaji, etc.)
- **source**: Source identifier (YouTube ID, etc.) - becomes Anki tag
- **notes**: Additional notes
- **audio_filename**: Generated MP3 filename
- **test**: Boolean flag (0 = production, 1 = test entry)

---

# Workflow Summary

```
CSV → create_flashcards.py (--test) → flashcards.db + MP3s → generate_apkg.py (--test) → .apkg → Anki (verify)
         ↓ (if satisfied)
CSV → create_flashcards.py → flashcards.db + MP3s → generate_apkg.py → .apkg → Anki
```

**Recommended workflow:**
1. Create CSV with target language, translation, and optional fields
2. Run `create_flashcards.py --test` to generate test entries with audio
3. Run `generate_apkg.py --test` to create test deck and verify quality
4. If satisfied, run `create_flashcards.py` (without --test) to import for production
5. Run `generate_apkg.py` to create production deck
6. Import `.apkg` into Anki

---

# Roadmap

Future improvements include:

- Integrate with FPT AI for southern vietnamese voice: https://docs.fpt.ai/docs/en/speech/api/text-to-speech.html
- Web UI for CSV creation and management
- Automatic subtitle download
- Automatic vocabulary extraction
- Automatic translation
- Duplicate detection
- Incremental deck updates
- Card review tracking
- Multi-field language support (e.g., multiple pronunciation styles)
