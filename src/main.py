from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chunk_text import chunk_text_file
from extract_text import extract_pdf_text
from generate_thumbnail import generate_thumbnail
from generate_subtitles import generate_subtitles
from generate_tts import generate_tts
from models import Paths
from render_video import render_video
from summarize import create_master_summary, summarize_chunks
from upload_youtube import generate_youtube_metadata_with_ai, upload_video_to_youtube
from utils import file_info, format_duration, log, ensure_dirs, load_config, project_root, timed, word_count
from write_script import write_final_script, write_visual_production


STEPS = {"all", "extract", "summarize", "script", "tts", "subtitles", "render", "thumbnail", "youtube", "publish"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pipeline local para crear videos estilo NotebookLM con una sola voz."
    )
    parser.add_argument("command", nargs="?", choices=sorted(STEPS), default="all")
    parser.add_argument("--pdf", default="input/book.pdf", help="Ruta al PDF de entrada.")
    parser.add_argument("--title", default=None, help="Título del libro o episodio.")
    parser.add_argument("--duration", type=int, default=None, help="Duración objetivo en minutos.")
    parser.add_argument("--preview-seconds", type=float, default=None, help="Renderiza solo los primeros N segundos.")
    parser.add_argument("--youtube-title", default=None, help="Título exacto para YouTube.")
    parser.add_argument("--youtube-description", default=None, help="Descripción exacta para YouTube.")
    parser.add_argument("--youtube-tags", default=None, help="Tags separados por coma para YouTube.")
    parser.add_argument("--privacy-status", choices=["private", "public", "unlisted"], default=None)
    parser.add_argument("--youtube-dry-run", action="store_true", help="Muestra metadata sin subir el video.")
    parser.add_argument("--config", default="config.yaml", help="Ruta a config.yaml.")
    parser.add_argument("--force", action="store_true", help="Regenera archivos aunque existan en cache.")
    return parser


def resolve_paths(pdf_arg: str) -> Paths:
    root = project_root()
    pdf = Path(pdf_arg)
    if not pdf.is_absolute():
        pdf = root / pdf
    return Paths.from_root(root, pdf)


def prepare(paths: Paths) -> None:
    ensure_dirs(
        [
            paths.output_text.parent,
            paths.chunks_dir,
            paths.summaries_dir,
            paths.scripts_dir,
            paths.audio_dir,
            paths.subtitles_dir,
            paths.video_dir,
        ]
    )


def run_extract(paths: Paths, chunk_size_chars: int, force: bool) -> None:
    log("1/6 Extrayendo y limpiando texto...")
    with timed("Paso extract_text"):
        extract_pdf_text(paths.pdf, paths.output_text, force=force)
    log("2/6 Dividiendo texto en chunks...")
    chunk_paths = chunk_text_file(paths.output_text, paths.chunks_dir, chunk_size_chars, force=force)
    log(f"Chunks listos: {len(chunk_paths)}")


def run_summarize(paths: Paths, config, force: bool) -> None:
    log("3/6 Resumiendo chunks...")
    chunk_summaries_path = paths.summaries_dir / "chunk_summaries.json"
    master_summary_path = paths.summaries_dir / "master_summary.json"
    with timed("Paso summarize_chunks"):
        summarize_chunks(paths.chunks_dir, chunk_summaries_path, config, force=force)
    log("Creando resumen maestro...")
    with timed("Paso master_summary"):
        create_master_summary(chunk_summaries_path, master_summary_path, config, force=force)


def run_script(paths: Paths, config, title: str, force: bool) -> None:
    log("4/6 Generando guion y estructura visual...")
    master_summary_path = paths.summaries_dir / "master_summary.json"
    script_json_path = paths.scripts_dir / "final_script.json"
    script_text_path = paths.scripts_dir / "final_script.txt"
    visual_json_path = paths.scripts_dir / "visual_production.json"
    with timed("Paso write_script"):
        script = write_final_script(master_summary_path, script_json_path, script_text_path, title, config, force=force)
    log(f"Guion listo: {word_count(script.text):,} palabras, {len(script.sections)} secciones")
    with timed("Paso visual_structure"):
        visual = write_visual_production(script_json_path, visual_json_path, config, force=force)
    log(f"Estructura visual lista: {len(visual.sections)} secciones")


def run_tts(paths: Paths, config, force: bool) -> None:
    log("5/6 Generando narración TTS...")
    with timed("Paso TTS"):
        generate_tts(paths.scripts_dir / "final_script.txt", paths.audio_dir / "narration.mp3", config, force=force)


def run_subtitles(paths: Paths, config, force: bool) -> None:
    log("Generando subtítulos...")
    with timed("Paso subtitles"):
        generate_subtitles(
            paths.scripts_dir / "final_script.txt",
            paths.audio_dir / "narration.mp3",
            paths.subtitles_dir / "subtitles.srt",
            config,
            force=force,
        )


def preview_output_path(paths: Paths, preview_seconds: float | None) -> Path:
    if not preview_seconds:
        return paths.video_dir / "final_video.mp4"
    seconds = int(preview_seconds)
    return paths.video_dir / f"preview_{seconds}s.mp4"


def thumbnail_output_path(config) -> Path:
    path = Path(config.thumbnail_path)
    if path.is_absolute():
        return path
    return project_root() / path


def run_render(paths: Paths, config, title: str, force: bool, preview_seconds: float | None = None) -> None:
    log("6/6 Renderizando video MP4...")
    with timed("Paso render"):
        render_video(
            paths.scripts_dir / "visual_production.json",
            paths.audio_dir / "narration.mp3",
            paths.subtitles_dir / "subtitles.srt",
            preview_output_path(paths, preview_seconds),
            config,
            episode_title=title,
            force=force,
            preview_seconds=preview_seconds,
        )


def run_youtube(
    paths: Paths,
    config,
    title: str,
    youtube_title: str | None,
    youtube_description: str | None,
    youtube_tags: str | None,
    privacy_status: str | None,
    dry_run: bool,
    force: bool,
) -> None:
    log("Subiendo video a YouTube...")
    upload_config = config
    if privacy_status:
        upload_config = config.model_copy(update={"youtube_privacy_status": privacy_status})
    tags = [tag.strip() for tag in youtube_tags.split(",")] if youtube_tags else None
    upload_title = youtube_title or title
    with timed("Paso youtube"):
        upload_video_to_youtube(
            video_path=paths.video_dir / "final_video.mp4",
            title=upload_title,
            config=upload_config,
            master_summary_path=paths.summaries_dir / "master_summary.json",
            script_path=paths.scripts_dir / "final_script.txt",
            description=youtube_description,
            tags=tags,
            dry_run=dry_run,
            force_metadata=force,
        )


def run_thumbnail(paths: Paths, config, title: str, force: bool) -> None:
    log("Generando miniatura...")
    with timed("Paso thumbnail"):
        metadata_path = paths.scripts_dir / "youtube_metadata.json"
        if force or not metadata_path.exists():
            log("Generando texto clickbait para título/miniatura con IA...")
            try:
                generate_youtube_metadata_with_ai(
                    title=title,
                    config=config,
                    master_summary_path=paths.summaries_dir / "master_summary.json",
                    script_path=paths.scripts_dir / "final_script.txt",
                    output_path=metadata_path,
                    force=force,
                )
            except Exception as exc:
                log(f"No se pudo generar metadata IA para miniatura ({exc}). Uso fallback local.", level="WARN")
        generate_thumbnail(
            title=title,
            config=config,
            metadata_path=metadata_path,
            master_summary_path=paths.summaries_dir / "master_summary.json",
            force=force,
        )


def log_outputs(command: str, paths: Paths, preview_seconds: float | None = None, dry_run: bool = False) -> None:
    if command == "extract":
        log(f"Salida texto: {file_info(paths.output_text)}")
        log(f"Chunks dir: {paths.chunks_dir}")
        return
    if command == "summarize":
        log(f"Resúmenes chunks: {file_info(paths.summaries_dir / 'chunk_summaries.json')}")
        log(f"Resumen maestro: {file_info(paths.summaries_dir / 'master_summary.json')}")
        return
    if command == "script":
        log(f"Guion: {file_info(paths.scripts_dir / 'final_script.txt')}")
        log(f"Estructura visual: {file_info(paths.scripts_dir / 'visual_production.json')}")
        log("Audio/subtítulos/video no se regeneran en el comando script; ejecuta tts, subtitles y render.")
        return
    if command == "tts":
        log(f"Audio: {file_info(paths.audio_dir / 'narration.mp3')}")
        log("Subtítulos/video no se regeneran en el comando tts; ejecuta subtitles y render.")
        return
    if command == "subtitles":
        log(f"Subtítulos: {file_info(paths.subtitles_dir / 'subtitles.srt')}")
        log("Video no se regenera en el comando subtitles; ejecuta render.")
        return
    if command == "render":
        log(f"Video: {file_info(preview_output_path(paths, preview_seconds))}")
        return
    if command == "thumbnail":
        log(f"Miniatura: {file_info(project_root() / 'output' / 'video' / 'thumbnail.jpg')}")
        return
    if command == "youtube":
        log(f"Video usado para YouTube: {file_info(paths.video_dir / 'final_video.mp4')}")
        return
    if command == "publish":
        label = "Video listo para YouTube" if dry_run else "Video usado para publish"
        log(f"{label}: {file_info(paths.video_dir / 'final_video.mp4')}")
        log(f"Miniatura usada: {file_info(project_root() / 'output' / 'video' / 'thumbnail.jpg')}")
        return

    log(f"Salidas principales: guion={file_info(paths.scripts_dir / 'final_script.txt')}")
    log(f"Audio={file_info(paths.audio_dir / 'narration.mp3')}")
    log(f"Subtítulos={file_info(paths.subtitles_dir / 'subtitles.srt')}")
    log(f"Video={file_info(preview_output_path(paths, preview_seconds))}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = project_root()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    try:
        if args.preview_seconds is not None and args.preview_seconds <= 0:
            raise RuntimeError("--preview-seconds debe ser mayor que cero.")
        config = load_config(config_path)
        if args.duration:
            config = config.model_copy(update={"target_duration_minutes": args.duration})
        paths = resolve_paths(args.pdf)
        prepare(paths)
        title = args.title or paths.pdf.stem.replace("-", " ").replace("_", " ").title()
        log("Iniciando pipeline Leer con la Oreja")
        log(f"Comando: {args.command}; force={args.force}")
        log(f"PDF: {file_info(paths.pdf)}")
        log(f"Título: {title}")
        log(
            f"Config: duración objetivo={config.target_duration_minutes} min "
            f"(rango {config.min_video_duration_minutes}-{config.max_video_duration_minutes}), "
            f"summary={config.openai_model_summary}, script={config.openai_model_script}, "
            f"TTS={config.tts_provider}/{config.tts_voice}, subtítulos={config.subtitle_alignment_mode}, "
            f"música={'on' if config.enable_background_music else 'off'}"
        )
        if args.preview_seconds:
            log(f"Preview solicitado: {args.preview_seconds:g} segundos")

        import time

        started = time.perf_counter()
        if args.command == "extract":
            run_extract(paths, config.chunk_size_chars, args.force)
        elif args.command == "summarize":
            run_summarize(paths, config, args.force)
        elif args.command == "script":
            run_script(paths, config, title, args.force)
        elif args.command == "tts":
            run_tts(paths, config, args.force)
        elif args.command == "subtitles":
            run_subtitles(paths, config, args.force)
        elif args.command == "render":
            run_render(paths, config, title, args.force, args.preview_seconds)
        elif args.command == "thumbnail":
            run_thumbnail(paths, config, title, args.force)
        elif args.command == "youtube":
            run_youtube(
                paths,
                config,
                title,
                args.youtube_title,
                args.youtube_description,
                args.youtube_tags,
                args.privacy_status,
                args.youtube_dry_run,
                args.force,
            )
        elif args.command == "publish":
            if args.preview_seconds:
                raise RuntimeError("publish siempre sube final_video.mp4; no uses --preview-seconds con publish.")
            run_extract(paths, config.chunk_size_chars, args.force)
            run_summarize(paths, config, args.force)
            run_script(paths, config, title, args.force)
            run_tts(paths, config, args.force)
            run_subtitles(paths, config, args.force)
            run_render(paths, config, title, args.force, None)
            run_thumbnail(paths, config, title, args.force)
            run_youtube(
                paths,
                config,
                title,
                args.youtube_title,
                args.youtube_description,
                args.youtube_tags,
                args.privacy_status,
                args.youtube_dry_run,
                args.force,
            )
        else:
            run_extract(paths, config.chunk_size_chars, args.force)
            run_summarize(paths, config, args.force)
            run_script(paths, config, title, args.force)
            run_tts(paths, config, args.force)
            run_subtitles(paths, config, args.force)
            run_render(paths, config, title, args.force, args.preview_seconds)
            run_thumbnail(paths, config, title, args.force)
        elapsed = time.perf_counter() - started
        log(f"Pipeline terminada en {format_duration(elapsed)}")
        log_outputs(args.command, paths, args.preview_seconds, args.youtube_dry_run)
        return 0
    except Exception as exc:
        log(f"Error: {exc}", level="ERROR")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
