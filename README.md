# AI Flashcard Generator

Generate Anki flashcards with high-quality AI-generated audio for multiple languages.

Currently supports:
- Vocabulary flashcards
- Sentence flashcards
- OpenAI Text-to-Speech
- Anki `.apkg` generation
- **Multi-language support** (Japanese, Spanish, French, and more)

---

# Requirements

## 1. OpenAI API Key

Create an OpenAI API key and set it as an environment variable:

```
OPENAI_API_KEY
```

On Windows:

```
OPENAI_API_KEY=sk-proj-...
```

---

## 2. Python

Python 3.11+ is recommended.

---

## 3. Install dependencies

```
pip install openai genanki
```

or

```
pip install -r requirements.txt
```

---

# Project Structure

```
languages.json                    (language configuration)

input/
  japanese/
    vocabulary.csv
    sentences.csv
  spanish/
    vocabulary.csv
    sentences.csv

audio/
  japanese/
  spanish/

output/
  japanese/
  spanish/

generate_audio.py
generate_apkg.py
```

---

# Configuration

Edit `languages.json` to add new languages or modify existing ones:

```json
{
  "japanese": {
    "name": "Japanese",
    "voice": "coral",
    "instructions": "Speak naturally in standard Japanese...",
    "model_name": "Japanese Model",
    "fields": ["Japanese", "English", "Romaji", "Audio", "Notes"],
    "csv_files": ["vocabulary.csv", "sentences.csv"]
  },
  "spanish": {
    "name": "Spanish",
    "voice": "nova",
    "instructions": "Speak naturally in standard Spanish...",
    "model_name": "Spanish Model",
    "fields": ["Spanish", "English", "Audio", "Notes"],
    "csv_files": ["vocabulary.csv", "sentences.csv"]
  }
}
```

### Configuration Fields:
- **name**: Display name for the deck
- **voice**: OpenAI voice to use (coral, nova, shimmer, etc.)
- **instructions**: Instructions for the text-to-speech model
- **model_name**: Name of the Anki model
- **fields**: List of card fields (order matters!)
- **csv_files**: CSV files to process for this language

---

# Usage

## Step 1 - Set up language folders

Create language-specific input folders:

```
mkdir input\japanese
mkdir input\spanish
```

---

## Step 2 - Download subtitles

Download subtitles from a YouTube video.

For example:

https://subtitle.to/

Download them as **TXT**.

---

## Step 3 - Generate the CSV files

Use ChatGPT (or another LLM) with the following prompt.

---

### Prompt for Japanese

You are creating flashcards for a complete beginner learning Japanese.

Given the following transcript:

1. Extract the most useful beginner vocabulary.
2. Ignore filler words and excessive repetition.
3. Create two CSV files.

The first file should be named **vocabulary.csv**.

Columns:

```
ID,Japanese,English,Romaji
```

Example:

```
JP000001,ハサミ,scissors,hasami
JP000002,紙,paper,kami
```

The second file should be named **sentences.csv**.

Columns:

```
ID,Japanese,English,Romaji
```

Example:

```
JS000001,これは何ですか。,What is this?,Kore wa nan desu ka?
JS000002,わかりません。,I don't know.,Wakarimasen.
```

Guidelines:

- Prefer useful beginner vocabulary.
- Keep approximately 15–30 vocabulary cards.
- Keep approximately 15–30 sentence cards.
- Remove duplicate sentences.
- Preserve natural Japanese.
- Use standard Hepburn romaji.
- Return valid CSV only.

---

### Prompt for Other Languages

Adapt the Japanese prompt for your target language. Ensure CSV column names match your language configuration in `languages.json`.

For example, for Spanish:

```
ID,Spanish,English,Notes
```

---

## Step 4 - Copy the CSV files

Copy

```
vocabulary.csv
sentences.csv
```

into the appropriate language folder, e.g.:

```
input\japanese\
```

or

```
input\spanish\
```

---

## Step 5 - Generate audio

Run the audio generation script with the `--language` flag:

```
python generate_audio.py --language japanese
```

This generates MP3 files in:

```
audio/japanese/
```

---

## Step 6 - Generate the Anki deck

Run the deck generation script with the `--language` flag:

```
python generate_apkg.py --language japanese
```

The generated deck will be written to:

```
output/japanese/
```

---

## Step 7 - Import into Anki

Open Anki.

Double-click the generated

```
.apkg
```

file.

The deck will automatically import with audio.

---

# Roadmap

Future improvements include:

- Automatic subtitle download
- Automatic vocabulary extraction
- Automatic translation
- Automatic romanization
- Duplicate detection
- Incremental deck updates
- Web UI for easier configuration