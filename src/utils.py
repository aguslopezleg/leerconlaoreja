from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TypeVar

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from models import Config

T = TypeVar("T", bound=BaseModel)


def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {level:<5} {message}", flush=True)


@contextmanager
def timed(label: str) -> Iterator[None]:
    start = time.perf_counter()
    log(f"{label}...")
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log(f"{label} listo en {format_duration(elapsed)}")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(path: Path | None = None) -> Config:
    config_path = path or project_root() / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No se encontró config.yaml en {config_path}")
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return Config.model_validate(data)


def ensure_dirs(paths: list[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_model(path: Path, model: type[T]) -> T:
    return model.model_validate(read_json(path))


def cache_exists(path: Path, force: bool = False) -> bool:
    return path.exists() and not force


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def file_info(path: Path) -> str:
    if not path.exists():
        return f"{path} (no existe)"
    return f"{path} ({format_bytes(path.stat().st_size)})"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds % 60
    return f"{minutes}m {remaining:.0f}s"


def require_openai_client() -> OpenAI:
    load_dotenv(project_root() / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "Falta OPENAI_API_KEY. Copia .env.example a .env y agrega tu clave antes de usar pasos con OpenAI."
        )
    return OpenAI()


def clean_for_filename(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ -]", "", value).strip()
    value = re.sub(r"\s+", "-", value)
    return value[:80] or "video"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def word_count(value: str) -> int:
    return len(re.findall(r"\b[\wáéíóúÁÉÍÓÚñÑüÜ]+\b", value))


def seconds_to_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round((seconds - int(seconds)) * 1000))
    whole = int(seconds)
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if millis == 1000:
        secs += 1
        millis = 0
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def seconds_to_hhmmss(seconds: float) -> str:
    whole = int(max(0, seconds))
    return f"{whole // 3600:02}:{(whole % 3600) // 60:02}:{whole % 60:02}"


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?¿¡])\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def model_json_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": name,
        "schema": model.model_json_schema(),
        "strict": False,
    }


def openai_json(
    client: OpenAI,
    model: str,
    prompt: str,
    response_model: type[T],
    schema_name: str,
    system: str,
    max_output_tokens: int | None = None,
) -> T:
    try:
        kwargs: dict[str, Any] = {}
        if max_output_tokens:
            kwargs["max_output_tokens"] = max_output_tokens
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            text={"format": model_json_schema(response_model, schema_name)},
            **kwargs,
        )
        content = response.output_text
    except Exception:
        kwargs = {}
        if max_output_tokens:
            kwargs["max_completion_tokens"] = max_output_tokens
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            **kwargs,
        )
        content = response.choices[0].message.content or "{}"
    return response_model.model_validate_json(content)
