from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from models import Config
from utils import cache_exists, file_info, format_duration, log, read_text, seconds_to_srt_time, split_sentences, timed, write_text


class AlignedWord(TypedDict):
    word: str
    start: float
    end: float


def get_audio_duration(audio_path: Path) -> float:
    try:
        from moviepy.editor import AudioFileClip
    except Exception:
        from moviepy import AudioFileClip

    clip = AudioFileClip(str(audio_path))
    try:
        return float(clip.duration)
    finally:
        clip.close()


def _wrap_subtitle(text: str, max_chars: int = 58) -> str:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        if current and current_len + len(word) + 1 > max_chars:
            lines.append(" ".join(current))
            current = []
            current_len = 0
        current.append(word)
        current_len += len(word) + 1
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines[:2])


def _write_approximate_srt(script_text: str, audio_duration: float) -> str:
    sentences = split_sentences(script_text)
    if not sentences:
        raise RuntimeError("No se detectaron frases para generar subtítulos aproximados.")

    log(f"Subtítulos aproximados: {len(sentences)} frases distribuidas en {format_duration(audio_duration)}")
    weights = [max(1, len(re.findall(r"\w+", sentence))) for sentence in sentences]
    total_weight = sum(weights)
    cursor = 0.0
    blocks: list[str] = []

    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        duration = max(1.2, audio_duration * weight / total_weight)
        start = cursor
        end = min(audio_duration, cursor + duration)
        cursor = end
        blocks.append(
            f"{index}\n{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n{_wrap_subtitle(sentence)}\n"
        )
    return "\n".join(blocks)


def _write_faster_whisper_srt(audio_path: Path, config: Config) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("subtitle_alignment_mode=faster_whisper requiere instalar faster-whisper.") from exc

    log(f"Transcribiendo con faster-whisper: modelo={config.whisper_model}, device=cpu, compute_type=int8")
    with timed("Cargando modelo/transcribiendo audio con faster-whisper"):
        model = WhisperModel(config.whisper_model, device="cpu", compute_type="int8")
        segments_iter, _ = model.transcribe(str(audio_path), beam_size=5)
        segments = list(segments_iter)
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{seconds_to_srt_time(segment.start)} --> {seconds_to_srt_time(segment.end)}\n"
            f"{_wrap_subtitle(segment.text.strip(), config.subtitle_max_chars)}\n"
        )
    log(f"faster-whisper generó {len(blocks)} bloques SRT")
    return "\n".join(blocks)


def _clean_word(value: str) -> str:
    return value.strip()


def _words_from_whisperx_result(result: dict) -> list[AlignedWord]:
    raw_words = result.get("word_segments") or []
    if not raw_words:
        for segment in result.get("segments", []):
            raw_words.extend(segment.get("words", []))

    words: list[AlignedWord] = []
    for raw in raw_words:
        text = _clean_word(str(raw.get("word", "")))
        start = raw.get("start")
        end = raw.get("end")
        if not text or start is None or end is None:
            continue
        words.append({"word": text, "start": float(start), "end": float(end)})
    return words


def _words_to_srt(words: list[AlignedWord], config: Config) -> str:
    if not words:
        raise RuntimeError("La alineación no devolvió timestamps por palabra.")

    blocks: list[str] = []
    current: list[AlignedWord] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(word["word"] for word in current)
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{seconds_to_srt_time(current[0]['start'])} --> {seconds_to_srt_time(current[-1]['end'])}\n"
            f"{_wrap_subtitle(text, config.subtitle_max_chars)}\n"
        )
        current.clear()

    for word in words:
        candidate_text = " ".join([*(item["word"] for item in current), word["word"]])
        candidate_duration = word["end"] - (current[0]["start"] if current else word["start"])
        ends_sentence = bool(re.search(r"[.!?…]$", word["word"]))
        too_wide = len(candidate_text) > config.subtitle_max_chars * 2
        too_long = candidate_duration > config.subtitle_max_duration_seconds

        if current and (too_wide or too_long):
            flush()

        current.append(word)
        if ends_sentence and len(" ".join(item["word"] for item in current)) >= config.subtitle_max_chars:
            flush()

    flush()
    return "\n".join(blocks)


def _write_whisperx_srt(audio_path: Path, config: Config) -> str:
    try:
        import whisperx
    except ImportError as exc:
        raise RuntimeError(
            "subtitle_alignment_mode=whisperx requiere WhisperX. Instálalo aparte con: pip install whisperx"
        ) from exc

    log(
        f"Transcribiendo/alineando con WhisperX: modelo={config.whisperx_model}, "
        f"device={config.whisperx_device}, compute_type={config.whisperx_compute_type}"
    )
    with timed("Cargando audio WhisperX"):
        audio = whisperx.load_audio(str(audio_path))
    with timed("Transcripción WhisperX"):
        model = whisperx.load_model(
            config.whisperx_model,
            config.whisperx_device,
            compute_type=config.whisperx_compute_type,
        )
        result = model.transcribe(audio, batch_size=config.whisperx_batch_size)
    language = result.get("language")
    if not language:
        raise RuntimeError("WhisperX no detectó idioma para cargar el modelo de alineación.")

    log(f"WhisperX detectó idioma: {language}; segmentos={len(result.get('segments', []))}")

    with timed("Alineación word-level WhisperX"):
        align_model, metadata = whisperx.load_align_model(language_code=language, device=config.whisperx_device)
        aligned = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            config.whisperx_device,
            return_char_alignments=False,
        )
    words = _words_from_whisperx_result(aligned)
    log(f"WhisperX alineó {len(words)} palabras")
    return _words_to_srt(words, config)


def generate_subtitles(
    script_path: Path,
    audio_path: Path,
    output_path: Path,
    config: Config,
    force: bool = False,
) -> Path:
    if not audio_path.exists():
        raise FileNotFoundError(f"No se encontró el audio: {audio_path}")
    if script_path.exists() and script_path.stat().st_mtime > audio_path.stat().st_mtime:
        raise RuntimeError(
            "El audio es más antiguo que el guion. Regenera primero la narración con: python src/main.py tts --force"
        )
    if cache_exists(output_path, force):
        newest_dependency = max(audio_path.stat().st_mtime, script_path.stat().st_mtime if script_path.exists() else 0)
        if output_path.stat().st_mtime >= newest_dependency:
            log(f"Cache subtítulos válido: {file_info(output_path)}")
            return output_path
        log("Cache subtítulos stale: audio o guion son más recientes; regenerando SRT", level="WARN")

    mode = "faster_whisper" if config.use_whisper_subtitles else config.subtitle_alignment_mode
    log(f"Generando subtítulos: modo={mode}, audio={file_info(audio_path)}")
    if mode == "whisperx":
        srt = _write_whisperx_srt(audio_path, config)
    elif mode == "faster_whisper":
        srt = _write_faster_whisper_srt(audio_path, config)
    else:
        script_text = read_text(script_path)
        duration = get_audio_duration(audio_path)
        srt = _write_approximate_srt(script_text, duration)

    write_text(output_path, srt)
    blocks = len(re.findall(r"^\d+\s*$", srt, flags=re.MULTILINE))
    log(f"Subtítulos guardados: {file_info(output_path)} ({blocks} bloques)")
    return output_path
