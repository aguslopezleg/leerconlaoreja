from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from generate_thumbnail import generate_thumbnail
from models import Config, MasterSummary, YouTubeMetadata
from prompts import SYSTEM_BASE, YOUTUBE_METADATA_PROMPT
from utils import cache_exists, file_info, load_model, log, openai_json, project_root, read_text, require_openai_client, timed, write_json

YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]


def _resolve_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root() / path


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        clean = tag.strip()
        clean = _truncate(clean, 60)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def build_youtube_metadata(
    title: str,
    config: Config,
    master_summary_path: Path,
    script_path: Path,
    override_description: str | None = None,
    override_tags: list[str] | None = None,
    ai_metadata_path: Path | None = None,
    force: bool = False,
) -> dict:
    master: MasterSummary | None = None
    if master_summary_path.exists():
        master = load_model(master_summary_path, MasterSummary)

    ai_metadata = generate_youtube_metadata_with_ai(
        title=title,
        config=config,
        master_summary_path=master_summary_path,
        script_path=script_path,
        output_path=ai_metadata_path,
        force=force,
    )

    video_title = _truncate(ai_metadata.title, 100)
    if override_description:
        description = override_description
    elif ai_metadata.description:
        description = ai_metadata.description
    else:
        ideas = master.ideas_principales[:5] if master else []
        thesis = master.tesis_central if master else "Una lectura guiada en formato audio overview."
        bullets = "\n".join(f"- {idea}" for idea in ideas)
        if not bullets:
            bullets = "- Ideas principales del libro\n- Aplicaciones prácticas\n- Reflexiones para la vida diaria"
        description = f"""Un recorrido narrado por {title}, en formato audio overview de una sola voz.

En este episodio de {config.brand_name}, exploramos:
{bullets}

Tesis central:
{thesis}

Este video está pensado para escuchar con calma: una síntesis clara, cálida y conversacional para acompañarte mientras caminas, trabajas o descansas.

Canal: {config.brand_name}

#libros #audiolibro #resumendelibros #desarrollopersonal"""

    tags = override_tags or []
    if not tags:
        tags = [*ai_metadata.tags, *config.youtube_tags, title]

    if script_path.exists():
        word_count = len(read_text(script_path).split())
        log(f"Metadata YouTube: guion detectado con {word_count:,} palabras")

    return {
        "snippet": {
            "title": video_title,
            "description": _truncate(description, 5000),
            "tags": _dedupe_tags(tags)[:30],
            "categoryId": ai_metadata.category_id or config.youtube_category_id,
            "defaultLanguage": ai_metadata.default_language or config.youtube_default_language,
            "defaultAudioLanguage": ai_metadata.default_language or config.youtube_default_language,
        },
        "status": {
            "privacyStatus": config.youtube_privacy_status,
            "selfDeclaredMadeForKids": config.youtube_made_for_kids,
            "license": config.youtube_license,
        },
    }


def generate_youtube_metadata_with_ai(
    title: str,
    config: Config,
    master_summary_path: Path,
    script_path: Path,
    output_path: Path | None = None,
    force: bool = False,
) -> YouTubeMetadata:
    output_path = output_path or project_root() / "output" / "scripts" / "youtube_metadata.json"
    if cache_exists(output_path, force):
        result = load_model(output_path, YouTubeMetadata)
        log(f"Cache metadata YouTube IA: {file_info(output_path)}")
        return result

    master: MasterSummary | None = None
    if master_summary_path.exists():
        master = load_model(master_summary_path, MasterSummary)
    script_excerpt = ""
    if script_path.exists():
        script_text = read_text(script_path)
        script_excerpt = script_text[:8000]

    prompt = YOUTUBE_METADATA_PROMPT.format(
        title=title,
        brand_name=config.brand_name,
        master_summary_json=json.dumps(master.model_dump() if master else {}, ensure_ascii=False, indent=2),
        script_excerpt=script_excerpt,
    )
    client = require_openai_client()
    log(f"Generando metadata YouTube con IA: modelo={config.openai_model_youtube_metadata}")
    with timed("Llamada OpenAI metadata YouTube"):
        result = openai_json(
            client=client,
            model=config.openai_model_youtube_metadata,
            prompt=prompt,
            response_model=YouTubeMetadata,
            schema_name="youtube_metadata",
            system=SYSTEM_BASE,
            max_output_tokens=2500,
        )
    result.title = _truncate(result.title, 100)
    result.description = _truncate(result.description, 5000)
    result.tags = _dedupe_tags(result.tags)[:30]
    if not result.category_id:
        result.category_id = config.youtube_category_id
    if not result.default_language:
        result.default_language = config.youtube_default_language
    write_json(output_path, result.model_dump())
    log(f"Metadata YouTube IA guardada: {file_info(output_path)}")
    return result


def _load_credentials(client_secrets_file: Path, token_file: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Faltan dependencias de YouTube. Instala con: pip install -r requirements.txt"
        ) from exc

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), YOUTUBE_UPLOAD_SCOPE)
    if creds and creds.expired and creds.refresh_token:
        log("Refrescando token OAuth de YouTube...")
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not client_secrets_file.exists():
            raise RuntimeError(
                f"No existe {client_secrets_file}. Descarga el OAuth client JSON desde Google Cloud "
                "y guarda la ruta en YOUTUBE_CLIENT_SECRETS_FILE."
            )
        log("Abriendo flujo OAuth local para YouTube...")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), YOUTUBE_UPLOAD_SCOPE)
        creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload_video_to_youtube(
    video_path: Path,
    title: str,
    config: Config,
    master_summary_path: Path,
    script_path: Path,
    description: str | None = None,
    tags: list[str] | None = None,
    dry_run: bool = False,
    force_metadata: bool = False,
    thumbnail_path: Path | None = None,
) -> dict:
    load_dotenv(project_root() / ".env")
    if not video_path.exists():
        raise FileNotFoundError(f"No se encontró el video para subir: {video_path}")

    metadata_path = script_path.parent / "youtube_metadata.json"
    metadata = build_youtube_metadata(
        title=title,
        config=config,
        master_summary_path=master_summary_path,
        script_path=script_path,
        override_description=description,
        override_tags=tags,
        ai_metadata_path=metadata_path,
        force=force_metadata,
    )
    log(f"Video para YouTube: {file_info(video_path)}")
    log(f"YouTube título: {metadata['snippet']['title']}")
    log(f"YouTube privacidad: {metadata['status']['privacyStatus']}; categoría={metadata['snippet']['categoryId']}")
    log(f"YouTube tags: {', '.join(metadata['snippet']['tags'])}")
    thumbnail_path = generate_thumbnail(
        title=metadata["snippet"]["title"],
        config=config,
        metadata_path=metadata_path,
        master_summary_path=master_summary_path,
        output_path=thumbnail_path,
        force=force_metadata,
    )
    log(f"YouTube miniatura: {file_info(thumbnail_path)}")

    if dry_run:
        log("Dry run activo: no se sube el video.")
        return {"dry_run": True, "metadata": metadata, "thumbnail": str(thumbnail_path)}

    client_secrets_file = _resolve_path(
        os.getenv("YOUTUBE_CLIENT_SECRETS_FILE"),
        project_root() / "input" / "youtube_client_secret.json",
    )
    token_file = _resolve_path(
        os.getenv("YOUTUBE_TOKEN_FILE"),
        project_root() / "output" / "youtube_token.json",
    )
    creds = _load_credentials(client_secrets_file, token_file)

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "Faltan dependencias de YouTube. Instala con: pip install -r requirements.txt"
        ) from exc

    youtube = build("youtube", "v3", credentials=creds)
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=metadata,
        media_body=media,
    )

    response = None
    with timed("Subiendo video a YouTube"):
        while response is None:
            status, response = request.next_chunk()
            if status:
                log(f"Upload YouTube: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"YouTube no devolvió video id. Respuesta: {json.dumps(response, ensure_ascii=False)}")
    log(f"Video subido: https://www.youtube.com/watch?v={video_id}")
    if thumbnail_path.exists():
        with timed("Subiendo miniatura a YouTube"):
            thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg", resumable=False)
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        log("Miniatura aplicada en YouTube")
    return response
