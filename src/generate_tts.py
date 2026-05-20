from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from models import Config
from utils import cache_exists, file_info, format_duration, log, read_text, require_openai_client, sha256_text, split_sentences, timed, word_count, write_json


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Path, config: Config, force: bool = False) -> Path:
        raise NotImplementedError


class OpenAITTSProvider(TTSProvider):
    max_chars_per_request = 3500

    def _split_text(self, text: str) -> list[str]:
        sentences = split_sentences(text)
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            if current and current_len + len(sentence) + 1 > self.max_chars_per_request:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            current.append(sentence)
            current_len += len(sentence) + 1
        if current:
            chunks.append(" ".join(current))
        return chunks or [text[: self.max_chars_per_request]]

    def synthesize(self, text: str, output_path: Path, config: Config, force: bool = False) -> Path:
        metadata_path = output_path.with_suffix(".json")
        text_hash = sha256_text(f"{config.tts_model}:{config.tts_voice}:{config.tts_instructions}:{text}")
        if cache_exists(output_path, force) and metadata_path.exists():
            try:
                import json

                if json.loads(metadata_path.read_text(encoding="utf-8")).get("text_hash") == text_hash:
                    log(f"Cache TTS: {file_info(output_path)}")
                    return output_path
            except Exception:
                pass

        client = require_openai_client()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        chunks = self._split_text(text)
        log(
            f"Generando TTS OpenAI: modelo={config.tts_model}, voz={config.tts_voice}, "
            f"{word_count(text):,} palabras, {len(chunks)} parte(s)"
        )
        if config.tts_instructions.strip():
            log(f"Instrucciones TTS: {config.tts_instructions}")

        if len(chunks) == 1:
            with timed("Llamada OpenAI TTS parte 1/1"):
                kwargs = {
                    "model": config.tts_model,
                    "voice": config.tts_voice,
                    "input": chunks[0],
                    "response_format": "mp3",
                }
                if config.tts_instructions.strip():
                    kwargs["instructions"] = config.tts_instructions
                response = client.audio.speech.create(**kwargs)
            response.stream_to_file(output_path)
        else:
            chunk_paths: list[Path] = []
            for index, chunk in enumerate(chunks, start=1):
                chunk_path = output_path.with_name(f"{output_path.stem}_part_{index:03}.mp3")
                log(f"TTS parte {index}/{len(chunks)}: {len(chunk):,} caracteres")
                with timed(f"Llamada OpenAI TTS parte {index}/{len(chunks)}"):
                    kwargs = {
                        "model": config.tts_model,
                        "voice": config.tts_voice,
                        "input": chunk,
                        "response_format": "mp3",
                    }
                    if config.tts_instructions.strip():
                        kwargs["instructions"] = config.tts_instructions
                    response = client.audio.speech.create(**kwargs)
                response.stream_to_file(chunk_path)
                log(f"Audio parcial guardado: {file_info(chunk_path)}")
                chunk_paths.append(chunk_path)
            concat_file = output_path.with_name("tts_concat.txt")
            concat_file.write_text(
                "\n".join(f"file '{path.resolve().as_posix()}'" for path in chunk_paths),
                encoding="utf-8",
            )
            with timed("Concatenando partes TTS con ffmpeg"):
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output_path)],
                    check=True,
                )

        write_json(
            metadata_path,
            {
                "provider": "openai",
                "model": config.tts_model,
                "voice": config.tts_voice,
                "instructions": config.tts_instructions,
                "text_hash": text_hash,
                "chunks": len(chunks),
            },
        )
        try:
            from generate_subtitles import get_audio_duration

            duration = get_audio_duration(output_path)
            log(f"Narración lista: {file_info(output_path)}, duración {format_duration(duration)}")
        except Exception:
            log(f"Narración lista: {file_info(output_path)}")
        return output_path


class ElevenLabsTTSProvider(TTSProvider):
    def synthesize(self, text: str, output_path: Path, config: Config, force: bool = False) -> Path:
        raise NotImplementedError("ElevenLabsTTSProvider está preparado como interfaz, pero aún no implementado.")


def get_tts_provider(name: str) -> TTSProvider:
    normalized = name.lower().strip()
    if normalized == "openai":
        return OpenAITTSProvider()
    if normalized == "elevenlabs":
        return ElevenLabsTTSProvider()
    raise ValueError(f"Proveedor TTS no soportado: {name}")


def generate_tts(script_path: Path, output_path: Path, config: Config, force: bool = False) -> Path:
    text = read_text(script_path)
    if not text.strip():
        raise RuntimeError("El guion está vacío; no se puede generar TTS.")
    log(f"Leyendo guion para TTS: {file_info(script_path)} ({word_count(text):,} palabras)")
    provider = get_tts_provider(config.tts_provider)
    return provider.synthesize(text, output_path, config, force=force)
