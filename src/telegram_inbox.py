from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv

from models import Config, ScheduledJob
from scheduler import add_job, pdf_fingerprint
from telegram_notify import send_telegram
from utils import clean_for_filename, log, project_root, write_json


class TelegramInboxState:
    def __init__(self, last_update_id: int = 0) -> None:
        self.last_update_id = last_update_id

    def model_dump(self) -> dict:
        return {"last_update_id": self.last_update_id}


def _state_path() -> Path:
    return project_root() / "output" / "telegram" / "inbox_state.json"


def _load_state() -> TelegramInboxState:
    path = _state_path()
    if not path.exists():
        return TelegramInboxState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return TelegramInboxState(last_update_id=int(data.get("last_update_id", 0)))


def _save_state(state: TelegramInboxState) -> None:
    write_json(_state_path(), state.model_dump())


def _require_telegram_env() -> tuple[str, str]:
    load_dotenv(project_root() / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en .env")
    if not chat_id:
        raise RuntimeError("Falta TELEGRAM_CHAT_ID en .env")
    return token, chat_id


def _telegram_api(token: str, method: str, params: dict | None = None) -> dict:
    query = f"?{urlencode(params or {})}" if params else ""
    with urlopen(f"https://api.telegram.org/bot{token}/{method}{query}", timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error en {method}: {data}")
    return data


def _download_file(token: str, file_id: str, output_path: Path) -> None:
    file_data = _telegram_api(token, "getFile", {"file_id": file_id})
    file_path = file_data["result"]["file_path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(f"https://api.telegram.org/file/bot{token}/{file_path}", timeout=300) as response:
        output_path.write_bytes(response.read())


def _message_from_update(update: dict) -> dict | None:
    return update.get("message") or update.get("channel_post")


def _title_from_message(message: dict, filename: str) -> str:
    caption = (message.get("caption") or "").strip()
    if caption:
        return caption.splitlines()[0].strip()
    return Path(filename).stem.replace("-", " ").replace("_", " ").title()


def poll_telegram_pdfs(
    config: Config,
    publish: bool = True,
    youtube_dry_run: bool = False,
    force: bool = False,
) -> list[ScheduledJob]:
    token, allowed_chat_id = _require_telegram_env()
    state = _load_state()
    params = {
        "offset": state.last_update_id + 1,
        "timeout": 0,
        "allowed_updates": json.dumps(["message", "channel_post"]),
    }
    try:
        updates = _telegram_api(token, "getUpdates", params).get("result", [])
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo consultar Telegram: {exc}") from exc

    jobs: list[ScheduledJob] = []
    inbox_dir = Path(config.telegram_pdf_inbox_dir)
    if not inbox_dir.is_absolute():
        inbox_dir = project_root() / inbox_dir
    inbox_dir.mkdir(parents=True, exist_ok=True)

    for update in updates:
        state.last_update_id = max(state.last_update_id, int(update["update_id"]))
        message = _message_from_update(update)
        if not message:
            continue
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != str(allowed_chat_id):
            log(f"Telegram: mensaje ignorado de chat no autorizado {chat_id}", level="WARN")
            continue
        document = message.get("document")
        if not document:
            continue
        filename = document.get("file_name") or f"telegram_{update['update_id']}.pdf"
        if not filename.lower().endswith(".pdf") and document.get("mime_type") != "application/pdf":
            send_telegram(f"Leer con la Oreja\nArchivo ignorado porque no parece PDF: {filename}", config)
            continue

        safe_name = clean_for_filename(Path(filename).stem)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = inbox_dir / f"{timestamp}-{safe_name}.pdf"
        _download_file(token, document["file_id"], output_path)
        relative_pdf = str(output_path.relative_to(project_root())) if output_path.is_relative_to(project_root()) else str(output_path)
        title = _title_from_message(message, filename)
        job = add_job(
            pdf=relative_pdf,
            title=title,
            duration=config.target_duration_minutes,
            publish=publish,
            youtube_dry_run=youtube_dry_run,
            force=force,
            scheduled_for=datetime.now(),
            pdf_fingerprint=pdf_fingerprint(output_path),
        )
        jobs.append(job)
        send_telegram(
            f"Leer con la Oreja\nPDF recibido y agregado a la cola.\nTitulo: {job.title}\nID: {job.job_id}",
            config,
            silent=True,
        )
    _save_state(state)
    if not jobs:
        log("Telegram: no llegaron PDFs nuevos.")
    return jobs
