from __future__ import annotations

import math
import re
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from generate_subtitles import get_audio_duration
from models import Config, VisualProduction
from utils import cache_exists, file_info, format_duration, load_model, log, timed

try:
    from moviepy.editor import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoClip, concatenate_audioclips, concatenate_videoclips
except Exception:
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoClip, concatenate_audioclips, concatenate_videoclips


def _with_duration(clip, duration: float):
    return clip.with_duration(duration) if hasattr(clip, "with_duration") else clip.set_duration(duration)


def _with_start(clip, start: float):
    return clip.with_start(start) if hasattr(clip, "with_start") else clip.set_start(start)


def _with_position(clip, position):
    return clip.with_position(position) if hasattr(clip, "with_position") else clip.set_position(position)


def _with_audio(clip, audio):
    return clip.with_audio(audio) if hasattr(clip, "with_audio") else clip.set_audio(audio)


def _with_opacity(clip, opacity: float):
    return clip.with_opacity(opacity) if hasattr(clip, "with_opacity") else clip.set_opacity(opacity)


def _with_volume_scaled(clip, factor: float):
    return clip.with_volume_scaled(factor) if hasattr(clip, "with_volume_scaled") else clip.volumex(factor)


def _subclip(clip, start: float, end: float):
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    return clip.subclip(start, end)


def _apply_audio_fades(clip, fade_seconds: float):
    if fade_seconds <= 0:
        return clip
    try:
        from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

        fade = min(fade_seconds, max(0.0, (clip.duration or 0) / 2))
        return clip.with_effects([AudioFadeIn(fade), AudioFadeOut(fade)])
    except Exception:
        return clip


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf" if bold else "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.ImageFont,
    y: int,
    fill: tuple[int, int, int],
    width: int,
    line_gap: int,
) -> int:
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += bbox[3] - bbox[1] + line_gap
    return y


def _make_background(width: int, height: int, accent: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (width, height), (14, 18, 24))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            glow = int(34 * (x / width) * (1 - y / height))
            pixels[x, y] = (14 + glow // 3, 18 + glow // 4, 24 + glow // 2)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, width, height), fill=(7, 10, 14, 80))
    draw.line((120, 160, width - 120, 160), fill=(*accent, 90), width=2)
    draw.line((120, height - 340, width - 120, height - 340), fill=(*accent, 45), width=2)
    return image


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _looks_duplicate(left: str, right: str) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    if SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.74:
        return True
    left_words = set(left_norm.split())
    right_words = set(right_norm.split())
    overlap = len(left_words & right_words) / max(1, min(len(left_words), len(right_words)))
    return overlap >= 0.7


def _is_internal_title(value: str) -> bool:
    normalized = _normalize_text(value)
    internal_titles = {
        "hook",
        "intro",
        "introduccion",
        "introduccion al libro",
        "cierre",
        "conclusion",
        "conclusiones",
        "outro",
    }
    return normalized in internal_titles


def _section_image(path: Path, section, config: Config, episode_title: str) -> Path:
    accents = {
        "title_card": (110, 199, 190),
        "key_phrase": (236, 185, 90),
        "quote_card": (151, 184, 255),
        "recap": (132, 220, 145),
        "neutral": (185, 196, 210),
    }
    accent = accents.get(str(section.visual_type.value if hasattr(section.visual_type, "value") else section.visual_type), (185, 196, 210))
    image = _make_background(config.video_width, config.video_height, accent)
    draw = ImageDraw.Draw(image, "RGBA")

    brand_font = _font(34, bold=True)
    small_font = _font(30)
    title_font = _font(42, bold=True)
    phrase_font = _font(82, bold=True)

    draw.text((120, 78), config.brand_name, font=brand_font, fill=(245, 248, 252))
    episode = episode_title[:110]
    draw.text((120, 122), episode, font=small_font, fill=(168, 178, 192))

    phrase = section.screen_text.strip() or section.title
    show_section_title = (
        bool(section.title.strip())
        and not _is_internal_title(section.title)
        and not _looks_duplicate(section.title, phrase)
    )
    if show_section_title:
        title_lines = _wrap_text(draw, section.title, title_font, config.video_width - 360)
        _draw_centered_lines(draw, title_lines[:2], title_font, 290, (210, 218, 228), config.video_width, 12)

    phrase_lines = _wrap_text(draw, phrase, phrase_font, config.video_width - 360)
    if show_section_title:
        y = 440 if len(phrase_lines) <= 2 else 405
    else:
        y = 360 if len(phrase_lines) <= 2 else 320
    _draw_centered_lines(draw, phrase_lines[:3], phrase_font, y, accent, config.video_width, 20)

    image.save(path)
    return path


def _parse_srt(path: Path) -> list[tuple[float, float, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip())
    entries: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        match = re.search(r"(\d\d:\d\d:\d\d,\d\d\d)\s+-->\s+(\d\d:\d\d:\d\d,\d\d\d)", block)
        if not match:
            continue
        start = _srt_to_seconds(match.group(1))
        end = _srt_to_seconds(match.group(2))
        subtitle = "\n".join(lines[2:])
        entries.append((start, end, subtitle))
    return entries


def _srt_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _subtitle_image(path: Path, text: str, config: Config) -> Path:
    width, height = config.video_width, 150
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    font = _font(44, bold=True)
    lines = text.splitlines()[:2]
    text_height = sum(draw.textbbox((0, 0), line, font=font)[3] for line in lines) + 10 * max(0, len(lines) - 1)
    box_y = max(0, (height - text_height) // 2 - 18)
    draw.rounded_rectangle((250, box_y, width - 250, height - 14), radius=8, fill=(0, 0, 0, 180))
    y = box_y + 20
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, y), line, font=font, fill=(255, 255, 255, 245))
        y += bbox[3] - bbox[1] + 10
    image.save(path)
    return path


def _waveform_clip(duration: float, config: Config):
    width = config.video_width
    height = 92
    bars = 96

    def make_frame(t: float):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :, :] = (11, 15, 21)
        center = height // 2
        for index in range(bars):
            phase = t * 2.8 + index * 0.27
            value = 0.35 + 0.65 * abs(math.sin(phase) * math.cos(phase * 0.37))
            bar_height = int(16 + value * 74)
            x0 = int(index * width / bars)
            x1 = int((index + 0.55) * width / bars)
            color = (70 + int(value * 110), 170 + int(value * 55), 190 + int(value * 35))
            frame[center - bar_height // 2 : center + bar_height // 2, x0:x1, :] = color
        return frame

    try:
        clip = VideoClip(frame_function=make_frame, duration=duration)
    except TypeError:
        clip = VideoClip(make_frame=make_frame, duration=duration)
    return _with_opacity(_with_position(clip, ("center", config.video_height - 312)), 0.72)


def _resolve_project_path(path_value: str, base_path: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return base_path / path


def _loop_audio_to_duration(audio_clip, duration: float):
    if audio_clip.duration >= duration:
        return _subclip(audio_clip, 0, duration)
    loops = math.ceil(duration / audio_clip.duration)
    looped = concatenate_audioclips([audio_clip] * loops)
    return _subclip(looped, 0, duration)


def _build_mixed_audio(narration, config: Config, duration: float, project_root: Path):
    if not config.enable_background_music:
        log("Música de fondo desactivada")
        return narration, []

    music_path = _resolve_project_path(config.background_music_path, project_root)
    if not music_path.exists():
        log(f"Música activada, pero no existe: {music_path}. Se renderiza solo con narración.", level="WARN")
        return narration, []

    music = AudioFileClip(str(music_path))
    volume_factor = 10 ** (config.background_music_volume_db / 20)
    music_loop = _loop_audio_to_duration(music, duration)
    music_loop = _with_volume_scaled(music_loop, volume_factor)
    music_loop = _apply_audio_fades(music_loop, config.music_fade_seconds)
    log(
        f"Música de fondo: {file_info(music_path)}, volumen={config.background_music_volume_db} dB, "
        f"fade={config.music_fade_seconds}s"
    )
    mixed = CompositeAudioClip([narration, music_loop])
    return mixed, [music, music_loop]


def render_video(
    visual_json_path: Path,
    audio_path: Path,
    subtitles_path: Path,
    output_path: Path,
    config: Config,
    episode_title: str,
    force: bool = False,
    preview_seconds: float | None = None,
) -> Path:
    if not audio_path.exists():
        raise FileNotFoundError(f"No se encontró el audio: {audio_path}")

    production = load_model(visual_json_path, VisualProduction)
    if not production.sections:
        raise RuntimeError("La estructura visual no contiene secciones.")

    full_duration = get_audio_duration(audio_path)
    render_duration = min(full_duration, preview_seconds) if preview_seconds else full_duration
    log(f"Audio para render: {file_info(audio_path)}, duración {format_duration(full_duration)}")
    if preview_seconds:
        log(f"Modo preview activo: renderizando {format_duration(render_duration)} en {output_path.name}")
    min_seconds = config.min_video_duration_minutes * 60
    max_seconds = config.max_video_duration_minutes * 60
    if not preview_seconds and full_duration < min_seconds:
        raise RuntimeError(
            f"El audio dura {full_duration / 60:.1f} minutos, bajo el mínimo de "
            f"{config.min_video_duration_minutes}. Regenera el guion y el TTS con --force."
        )
    if not preview_seconds and full_duration > max_seconds:
        raise RuntimeError(
            f"El audio dura {full_duration / 60:.1f} minutos, sobre el máximo de "
            f"{config.max_video_duration_minutes}. Reduce el guion antes de renderizar."
        )
    if cache_exists(output_path, force):
        music_path = _resolve_project_path(config.background_music_path, visual_json_path.parents[2])
        newest_dependency = max(
            audio_path.stat().st_mtime,
            subtitles_path.stat().st_mtime if subtitles_path.exists() else 0,
            visual_json_path.stat().st_mtime if visual_json_path.exists() else 0,
            music_path.stat().st_mtime if config.enable_background_music and music_path.exists() else 0,
        )
        if output_path.stat().st_mtime >= newest_dependency:
            log(f"Cache video final válido: {file_info(output_path)}")
            return output_path
        log("Cache video stale: audio/subtítulos/estructura visual son más recientes; renderizando de nuevo", level="WARN")
    planned = sum(max(1, section.estimated_duration_seconds) for section in production.sections)
    scale = full_duration / planned if planned else 1.0
    subtitles = [(start, end, text) for start, end, text in _parse_srt(subtitles_path) if start < render_duration]
    log(
        f"Render plan: {len(production.sections)} secciones visuales, {len(subtitles)} subtítulos, "
        f"duración planificada {format_duration(planned)}, escala={scale:.2f}"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="notebook_video_") as tmp:
        tmp_dir = Path(tmp)
        clips = []
        for index, section in enumerate(production.sections, start=1):
            log(f"Generando placa visual {index}/{len(production.sections)}: {section.title}")
            image_path = _section_image(tmp_dir / f"section_{index:03}.png", section, config, episode_title)
            section_duration = max(2.0, section.estimated_duration_seconds * scale)
            clips.append(_with_duration(ImageClip(str(image_path)), section_duration))

        with timed("Concatenando placas visuales"):
            base = concatenate_videoclips(clips, method="compose")
            base = _with_duration(base, render_duration)

        overlays = [base, _waveform_clip(render_duration, config)]
        for index, (start, end, text) in enumerate(subtitles, start=1):
            if end <= start:
                continue
            end = min(end, render_duration)
            subtitle_path = _subtitle_image(tmp_dir / f"subtitle_{index:04}.png", text, config)
            subtitle_clip = _with_position(ImageClip(str(subtitle_path)), ("center", config.video_height - 158))
            overlays.append(_with_start(_with_duration(subtitle_clip, end - start), start))
        log(f"Overlays listos: {len(overlays)} clips totales")

        narration_source = AudioFileClip(str(audio_path))
        audio = _subclip(narration_source, 0, render_duration)
        mixed_audio, extra_audio_clips = _build_mixed_audio(audio, config, render_duration, visual_json_path.parents[2])
        final = _with_audio(CompositeVideoClip(overlays, size=(config.video_width, config.video_height)), mixed_audio)
        with timed(f"Escribiendo MP4 {config.video_width}x{config.video_height}@{config.fps}"):
            final.write_videofile(
                str(output_path),
                fps=config.fps,
                codec="libx264",
                audio_codec="aac",
                preset="medium",
                threads=4,
            )
        final.close()
        mixed_audio.close()
        audio.close()
        narration_source.close()
        for clip in extra_audio_clips:
            clip.close()
    log(f"Video guardado: {file_info(output_path)}")
    return output_path
