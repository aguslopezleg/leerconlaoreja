from __future__ import annotations

import re
from pathlib import Path

from utils import cache_exists, file_info, log, read_text, write_text


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        paragraph_len = len(paragraph)
        if current and current_len + paragraph_len + 2 > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        if paragraph_len > max_chars:
            for start in range(0, paragraph_len, max_chars):
                part = paragraph[start : start + max_chars].strip()
                if part:
                    chunks.append(part)
            continue
        current.append(paragraph)
        current_len += paragraph_len + 2

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_text_file(text_path: Path, chunks_dir: Path, max_chars: int, force: bool = False) -> list[Path]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(chunks_dir.glob("chunk_*.txt"))
    if existing and not force:
        total_chars = sum(len(read_text(path)) for path in existing)
        log(f"Cache chunks: {len(existing)} archivos, {total_chars:,} caracteres en {chunks_dir}")
        return existing

    if force:
        log(f"--force activo: eliminando {len(existing)} chunks previos")
        for path in existing:
            path.unlink()

    text = read_text(text_path)
    log(f"Dividiendo {file_info(text_path)} con chunk_size_chars={max_chars:,}")
    chunks = split_into_chunks(text, max_chars)
    if not chunks:
        raise RuntimeError("No se pudieron generar chunks desde el texto limpio.")

    paths: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        path = chunks_dir / f"chunk_{index:03}.txt"
        write_text(path, chunk)
        paths.append(path)
    avg_chars = sum(len(chunk) for chunk in chunks) // max(1, len(chunks))
    log(f"Chunks generados: {len(paths)} archivos, promedio {avg_chars:,} caracteres")
    return paths
