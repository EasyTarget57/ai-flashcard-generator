import argparse
import asyncio
import json


LANGUAGE_PREFIXES = {
    "dutch": "nl-",
    "english": "en",
    "french": "fr",
    "japanese": "ja-",
    "spanish": "es-",
    "vietnamese": "vi",
}


async def load_edge_voices():
    import edge_tts

    return await edge_tts.list_voices()


def list_edge_voice_names(language):
    prefix = LANGUAGE_PREFIXES.get(language)
    if not prefix:
        return []

    voices = asyncio.run(load_edge_voices())
    names = [
        voice["ShortName"]
        for voice in voices
        if voice.get("ShortName", "").startswith(prefix)
    ]
    return sorted(set(names))


def main():
    parser = argparse.ArgumentParser(description="List Microsoft Edge TTS voices for a language")
    parser.add_argument(
        "--language",
        required=True,
        choices=sorted(LANGUAGE_PREFIXES),
        help="Language key to filter voices for",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format",
    )
    args = parser.parse_args()

    voices = list_edge_voice_names(args.language)
    if args.format == "json":
        print(json.dumps(voices, ensure_ascii=False, indent=2))
    else:
        for voice in voices:
            print(voice)


if __name__ == "__main__":
    main()
