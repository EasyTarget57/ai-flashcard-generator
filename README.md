# AI Flashcard Generator

Generate Anki flashcards with high-quality AI-generated audio for multiple languages.

---
# Usage

Run the PySide6 desktop app (from .exe or by running):

```
python flashcard-generator.py
```
Select the language for which you want to generate flashcards in the top right corner.

## Flashcards
![Flashcards screen](assets/screenshots_README/Flashcards.png)

Here you can see your flashcards. You can search and play the sound. For now there is no other functionality here yet.

---

## Import

![Flashcards screen](assets/screenshots_README/Import.png)

This is the main screen for creating new flashcards using sentences and/or single words. You can put CSV in the vocabulary and/or sentences section then click the import button at the bottom. This creates the audio for the flashcards and saves them to the local database.

At the top you can type the deck name (so the name that will be used for the Anki export). If you leave this empty the name of the language is used. You can also input a source. This will be saved to DB so you can easily find all vocabulary for your import.

You need to make sure the first line in the textbox is the columns (examples below). You can click the "How to create CSVs" button on the top right to get some more information on how to create these CSVs using AI.

In future releases we will simplify this process.

**Vocabulary CSV** (`vocabulary.csv`):

Example for Japanese:
```
Front,Back,Pronunciation,Notes
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

Example for Japanese:
```
Front,Back,Pronunciation
これは何ですか。,What is this?,Kore wa nan desu ka?
わかりません。,I don't know.,Wakarimasen.
```

Example for Spanish (no pronunciation):
```
Front,Back
¿Qué es esto?,What is this?
No sé.,I don't know.
```

---

## Export

![Flashcards screen](assets/screenshots_README/Export.png)

This screen allows you to export your flashcards to Anki. Note that your Anki desktop app should be closed when exporting. Otherwise the generated deck will not open in Anki (for import).

You just select the deck you want to export from the list and click the "Export to Anki" button at the bottom right.

![Flashcards screen](assets/screenshots_README/Export_result.png)

When this process finished (and your Anki is not open). This will open an Anki import dialog.

![Flashcards screen](assets/screenshots_README/Export_anki_deck.png)

After import in Anki, you will have the deck. This is how it looks like. We have the audio (which auto plays) and the target language text. When you show answer you will see the translation and the pronunciation (if you added a Pronunciation column to your import).

Note: for now the translation is only clearly visible in Anki light mode.

---

## Settings

![Flashcards screen](assets/screenshots_README/Settings_edge.png)

In Settings you can configure your TTS (text to speech) provider. Note that edge is the only free option. For OpenAI or FPT.AI you need to have an API key and set it to your environment variables.

You can input some text in your target language and click "Generate Test Audio" to test your settings. If it's good you can click "Save Settings" at the bottom right.

For Edge TTS there is a dropdown with the selected voices. For OpenAI and FPT.AI you will need to check the options on google.

![Flashcards screen](assets/screenshots_README/Settings_fptai.png)

Example settings for FPT.AI (requires key).

# Requirements

## 1. Anki

This project only supports export to Anki now so make sure Anki is installed. 

https://apps.ankiweb.net/

## 2. API Keys (Optional)

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

---

# Dev information

TODO: Add information about database/audio/input/output folder location. Short description of DB schema and required python dependencies.


---

# Roadmap

Future improvements include:

- Open bug: Audio fails when output device changes
- Support for Anki dark mode.
- Regenerate Audio (implemented but not added to UI) and other deck management features
- Support for creating flashcards from youtube link
- Support for creating flashcards from documents.
