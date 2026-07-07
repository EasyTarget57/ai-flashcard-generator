# AI Flashcard Generator

Generate Anki flashcards with high-quality AI-generated audio.

Currently supports:
- Vocabulary flashcards
- Sentence flashcards
- OpenAI Text-to-Speech
- Anki `.apkg` generation

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
input/
    vocabulary.csv
    sentences.csv

audio/

output/

generate_audio.py
generate_apkg.py
```

---

# Usage

## Step 1 - Download subtitles

Download the subtitles from a YouTube video.

For example:

https://subtitle.to/

Download them as **TXT**.

---

## Step 2 - Generate the CSV files

Use ChatGPT (or another LLM) with the following prompt.

---

### Prompt

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

## Step 3 - Copy the CSV files

Copy

```
vocabulary.csv
sentences.csv
```

into

```
input/
```

---

## Step 4 - Generate audio

Run

```
python generate_audio.py
```

This generates MP3 files in

```
audio/
```

---

## Step 5 - Generate the Anki deck

Run

```
python generate_apkg.py
```

The generated deck will be written to

```
output/
```

---

## Step 6 - Import into Anki

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

- Multiple language support
- Automatic subtitle download
- Automatic vocabulary extraction
- Automatic translation
- Automatic romanization
- Duplicate detection
- Incremental deck updates