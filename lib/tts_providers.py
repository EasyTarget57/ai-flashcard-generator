"""Text-to-Speech provider implementations."""

import asyncio
import os
import time
import requests
from pathlib import Path
from openai import OpenAI


class TTSProvider:
    """Base class for TTS providers."""

    audio_extension = ""

    def generate_audio(self, text: str, audio_id: int, audio_dir: Path) -> str:
        """Generate audio file and return filename."""
        raise NotImplementedError


class OpenAIProvider(TTSProvider):
    """OpenAI TTS provider."""

    audio_extension = ".mp3"

    def __init__(self, voice: str, instructions: str):
        self.client = OpenAI()
        self.voice = voice
        self.instructions = instructions
        self.model = "gpt-4o-mini-tts"

    def generate_audio(self, text: str, audio_id: int, audio_dir: Path) -> str:
        """Generate MP3 file using OpenAI."""
        filename = f"{audio_id}.mp3"
        filepath = audio_dir / filename

        with self.client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=self.voice,
            input=text,
            instructions=self.instructions,
        ) as response:
            response.stream_to_file(str(filepath))

        return filename


class FPTAIProvider(TTSProvider):
    """FPT.AI TTS provider for Vietnamese (New API)."""

    audio_extension = ".wav"

    def __init__(self, voice: str, speed: float = 1.0, request_delay: float = 0.5):
        api_key = os.getenv("FPTAI_API_KEY")
        if not api_key:
            raise ValueError("FPTAI_API_KEY environment variable not set")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or speed <= 0:
            raise ValueError("FPT.AI speed must be a positive number")

        self.api_key = api_key
        self.voice = voice
        self.speed = speed
        self.api_url = "https://mkp-api.fptcloud.com/v1/audio/speech"
        self.request_delay = request_delay
        self.last_request_time = 0

    def generate_audio(self, text: str, audio_id: int, audio_dir: Path) -> str:
        """Generate WAV file using FPT.AI new synchronous API."""
        filename = f"{audio_id}.wav"
        filepath = audio_dir / filename

        # Check text constraints
        if len(text) < 3:
            raise ValueError("Text must be at least 3 characters")
        if len(text) > 5000:
            raise ValueError("Text cannot exceed 5000 characters")

        # Rate limiting: wait if needed
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        
        self.last_request_time = time.time()

        # Prepare request
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": "FPT.AI-VITs",
            "input": text,
            "response_format": "wav",
            "speed": str(self.speed),
            "voice": self.voice,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            if not response.ok:
                detail = response.text.strip()
                raise RuntimeError(
                    f"FPTAI API returned HTTP {response.status_code}: {detail}"
                )

            # Write audio data directly
            filepath.write_bytes(response.content)

            return filename

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"FPTAI API request failed: {e}")


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge online TTS provider."""

    audio_extension = ".mp3"

    def __init__(
        self,
        voice: str,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ):
        if not voice:
            raise ValueError("Edge TTS voice must be set")

        try:
            import edge_tts
        except ImportError as error:
            raise ValueError(
                "edge-tts is not installed. Run: pip install edge-tts"
            ) from error

        self.edge_tts = edge_tts
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

    def generate_audio(self, text: str, audio_id: int, audio_dir: Path) -> str:
        """Generate MP3 file using Microsoft Edge online TTS."""
        filename = f"{audio_id}.mp3"
        filepath = audio_dir / filename

        async def save_audio():
            communicate = self.edge_tts.Communicate(
                text,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch,
            )
            await communicate.save(str(filepath))

        asyncio.run(save_audio())
        return filename


def get_tts_provider(provider_name: str, config: dict) -> TTSProvider:
    """Factory function to get the appropriate TTS provider."""
    if provider_name == "openai":
        return OpenAIProvider(
            voice=config.get("tts_voice"),
            instructions=config.get("instructions"),
        )
    elif provider_name == "fptai":
        return FPTAIProvider(
            voice=config.get("tts_voice"),
            speed=config.get("tts_speed", 1.0),
        )
    elif provider_name == "edge":
        return EdgeTTSProvider(
            voice=config.get("tts_voice"),
            rate=config.get("tts_rate", "+0%"),
            volume=config.get("tts_volume", "+0%"),
            pitch=config.get("tts_pitch", "+0Hz"),
        )
    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")


def get_tts_audio_extension(provider_name: str) -> str:
    """Return the audio file extension generated by a TTS provider."""
    if provider_name == "openai":
        return OpenAIProvider.audio_extension
    elif provider_name == "fptai":
        return FPTAIProvider.audio_extension
    elif provider_name == "edge":
        return EdgeTTSProvider.audio_extension
    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")
