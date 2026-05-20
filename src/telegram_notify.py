from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from models import Config
from utils import log, project_root


def telegram_enabled(config: Config) -> bool:
    load_dotenv(project_root() / ".env")
    return bool(
        config.telegram_notifications_enabled
        and os.getenv("TELEGRAM_BOT_TOKEN")
        and os.getenv("TELEGRAM_CHAT_ID")
    )


def send_telegram(message: str, config: Config, silent: bool = False) -> bool:
    if not telegram_enabled(config):
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "false",
    }
    if silent:
        payload["disable_notification"] = "true"
    body = urlencode(payload).encode("utf-8")
    request = Request(url, data=body, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        log(f"No se pudo enviar Telegram: {exc}", level="WARN")
        return False
    if not data.get("ok"):
        log(f"Telegram devolvió error: {data}", level="WARN")
        return False
    return True
