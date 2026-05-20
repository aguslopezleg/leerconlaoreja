from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any
from datetime import datetime

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
    scheduler_queue_dir: str = "input/queue"
    scheduler_interval_days: int = 3
    scheduler_publish_time: str = "09:00"
    scheduler_default_publish: bool = True
    telegram_notifications_enabled: bool = False
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

    @field_validator("scheduler_publish_time")
    @classmethod
    def valid_scheduler_publish_time(cls, value: str) -> str:
        normalized = value.strip()
        parts = normalized.split(":")
        if len(parts) != 2:
            raise ValueError("Debe tener formato HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Debe tener formato HH:MM válido")
        return f"{hour:02}:{minute:02}"

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
        "scheduler_interval_days",
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
    def from_root(cls, project_root: Path, pdf: Path, output_root: Path | None = None) -> "Paths":
        output = output_root or project_root / "output"
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


class ScheduledJobStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ScheduledJob(BaseModel):
    job_id: str
    pdf: str
    title: str
    duration: int = 20
    scheduled_for: datetime | None = None
    pdf_fingerprint: str | None = None
    output_root: str | None = None
    publish: bool = True
    youtube_dry_run: bool = False
    force: bool = False
    privacy_status: str | None = None
    youtube_title: str | None = None
    youtube_description: str | None = None
    youtube_tags: str | None = None
    status: ScheduledJobStatus = ScheduledJobStatus.pending
    attempts: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    youtube_url: str | None = None


class SchedulerState(BaseModel):
    jobs: list[ScheduledJob] = Field(default_factory=list)
