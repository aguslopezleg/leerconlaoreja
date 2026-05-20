from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Config(BaseModel):
    openai_model_summary: str = "gpt-4o-mini"
    openai_model_script: str = "gpt-4o"
    openai_model_visual: str = "gpt-4o-mini"
    openai_model_youtube_metadata: str = "gpt-4o-mini"
    openai_max_output_tokens_script: int = 12000
    tts_provider: str = "openai"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    tts_instructions: str = "Leé este texto con estilo de audiolibro: voz cálida, ritmo pausado y natural, buena dicción, pausas expresivas y tono envolvente. Narrá como si estuvieras contando una historia íntima, con emoción sutil y sin sobreactuar."
    target_duration_minutes: int = 20
    min_video_duration_minutes: int = 10
    max_video_duration_minutes: int = 20
    words_per_minute: int = 150
    chunk_size_chars: int = 32000
    rolling_context_max_chars: int = 6000
    use_whisper_subtitles: bool = False
    subtitle_alignment_mode: str = "approximate"
    whisper_model: str = "small"
    whisperx_model: str = "small"
    whisperx_device: str = "cpu"
    whisperx_compute_type: str = "int8"
    whisperx_batch_size: int = 8
    subtitle_max_chars: int = 58
    subtitle_max_duration_seconds: float = 5.5
    enable_ai_images: bool = False
    enable_background_music: bool = False
    background_music_path: str = "input/music.mp3"
    background_music_volume_db: float = -34
    music_fade_seconds: float = 4
    video_width: int = 1920
    video_height: int = 1080
    fps: int = 30
    brand_name: str = "Leer con la Oreja"
    output_language: str = "español neutro"
    youtube_privacy_status: str = "unlisted"
    youtube_category_id: str = "27"
    youtube_default_language: str = "es"
    youtube_made_for_kids: bool = False
    youtube_contains_synthetic_media: bool = False
    youtube_license: str = "youtube"
    thumbnail_path: str = "output/video/thumbnail.jpg"
    thumbnail_subject_path: str = "input/thumbnail_subject.jpg"
    thumbnail_use_ai: bool = True
    thumbnail_image_model: str = "gpt-image-1.5"
    thumbnail_image_quality: str = "medium"
    thumbnail_image_size: str = "1536x1024"
    thumbnail_text_source: str = "thumbnail_text"
    thumbnail_width: int = 1280
    thumbnail_height: int = 720
    youtube_tags: list[str] = Field(
        default_factory=lambda: [
            "libros",
            "audiolibro",
            "resumen de libros",
            "desarrollo personal",
            "Leer con la Oreja",
        ]
    )

    @field_validator("subtitle_alignment_mode")
    @classmethod
    def valid_subtitle_alignment_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"approximate", "faster_whisper", "whisperx"}
        if normalized not in allowed:
            raise ValueError(f"Debe ser uno de: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("youtube_privacy_status")
    @classmethod
    def valid_youtube_privacy_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"private", "public", "unlisted"}
        if normalized not in allowed:
            raise ValueError(f"Debe ser uno de: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("thumbnail_image_quality")
    @classmethod
    def valid_thumbnail_image_quality(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"low", "medium", "high", "auto", "standard", "hd"}
        if normalized not in allowed:
            raise ValueError(f"Debe ser uno de: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("thumbnail_text_source")
    @classmethod
    def valid_thumbnail_text_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"video_title", "thumbnail_text"}
        if normalized not in allowed:
            raise ValueError(f"Debe ser uno de: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator(
        "target_duration_minutes",
        "min_video_duration_minutes",
        "max_video_duration_minutes",
        "words_per_minute",
        "chunk_size_chars",
        "rolling_context_max_chars",
        "whisperx_batch_size",
        "subtitle_max_chars",
        "video_width",
        "video_height",
        "thumbnail_width",
        "thumbnail_height",
        "fps",
        "openai_max_output_tokens_script",
    )
    @classmethod
    def must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Debe ser mayor que cero")
        return value

    @field_validator("subtitle_max_duration_seconds", "music_fade_seconds")
    @classmethod
    def duration_must_be_positive(cls, value: float) -> float:
        if value < 0:
            raise ValueError("No puede ser negativo")
        return value

    @model_validator(mode="after")
    def valid_duration_window(self) -> "Config":
        if self.max_video_duration_minutes < self.min_video_duration_minutes:
            raise ValueError("max_video_duration_minutes debe ser mayor o igual a min_video_duration_minutes")
        if self.target_duration_minutes < self.min_video_duration_minutes:
            raise ValueError("target_duration_minutes no puede ser menor que min_video_duration_minutes")
        if self.target_duration_minutes > self.max_video_duration_minutes:
            raise ValueError("target_duration_minutes no puede ser mayor que max_video_duration_minutes")
        return self


class ChunkSummary(BaseModel):
    chunk_id: int
    ideas_principales: list[str] = Field(default_factory=list)
    conceptos_importantes: list[str] = Field(default_factory=list)
    ejemplos_utiles: list[str] = Field(default_factory=list)
    aplicaciones_practicas: list[str] = Field(default_factory=list)
    citas_o_frases_relevantes: list[str] = Field(default_factory=list)
    conexiones_con_contexto: list[str] = Field(default_factory=list)
    dudas_o_referencias_pendientes: list[str] = Field(default_factory=list)


class ChunkSummaries(BaseModel):
    summaries: list[ChunkSummary]
    rolling_context: str = ""


class MasterSummary(BaseModel):
    tesis_central: str
    ideas_principales: list[str] = Field(min_length=5, max_length=10)
    estructura_recomendada_video: list[str]
    tono_sugerido: str
    ejemplos_practicos: list[str] = Field(default_factory=list)
    advertencias_o_matices: list[str] = Field(default_factory=list)


class YouTubeMetadata(BaseModel):
    title: str = Field(max_length=100)
    description: str = Field(max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    category_id: str = "27"
    default_language: str = "es"
    thumbnail_text: str = Field(default="", max_length=80)
    thumbnail_badge: str = Field(default="RESUMEN NARRADO", max_length=40)


class ScriptSection(BaseModel):
    section_id: int
    title: str
    voiceover: str


class ExpandedScriptSection(BaseModel):
    section_id: int
    title: str
    voiceover: str


class FinalScript(BaseModel):
    title: str
    estimated_words: int
    target_duration_minutes: int
    sections: list[ScriptSection]

    @property
    def text(self) -> str:
        return "\n\n".join(section.voiceover.strip() for section in self.sections if section.voiceover.strip())


class VisualType(str, Enum):
    title_card = "title_card"
    key_phrase = "key_phrase"
    quote_card = "quote_card"
    recap = "recap"
    neutral = "neutral"


class VisualSection(BaseModel):
    section_id: int
    title: str
    voiceover: str
    screen_text: str
    visual_type: VisualType = VisualType.neutral
    estimated_start: str = "00:00:00"
    estimated_duration_seconds: int = 60


class VisualProduction(BaseModel):
    sections: list[VisualSection]


class Paths(BaseModel):
    project_root: Path
    pdf: Path
    output_text: Path
    chunks_dir: Path
    summaries_dir: Path
    scripts_dir: Path
    audio_dir: Path
    subtitles_dir: Path
    video_dir: Path

    @classmethod
    def from_root(cls, project_root: Path, pdf: Path) -> "Paths":
        output = project_root / "output"
        return cls(
            project_root=project_root,
            pdf=pdf,
            output_text=output / "text" / "book_clean.txt",
            chunks_dir=output / "text" / "chunks",
            summaries_dir=output / "summaries",
            scripts_dir=output / "scripts",
            audio_dir=output / "audio",
            subtitles_dir=output / "subtitles",
            video_dir=output / "video",
        )


JsonDict = dict[str, Any]
