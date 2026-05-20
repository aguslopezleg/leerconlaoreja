from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from utils import cache_exists, file_info, log, write_text


def _detect_repeated_lines(pages: list[list[str]], min_ratio: float = 0.35) -> set[str]:
    counter: Counter[str] = Counter()
    for page in pages:
        unique_lines = {line.strip() for line in page if line.strip()}
        counter.update(unique_lines)
    threshold = max(3, int(len(pages) * min_ratio))
    return {line for line, count in counter.items() if count >= threshold and len(line) <= 120}


def clean_extracted_text(raw_pages: list[str]) -> str:
    page_lines = [[line.strip() for line in page.splitlines()] for page in raw_pages]
    repeated = _detect_repeated_lines(page_lines)
    cleaned_pages: list[str] = []

    for lines in page_lines:
        cleaned: list[str] = []
        for line in lines:
            if not line:
                cleaned.append("")
                continue
            if line in repeated:
                continue
            if re.fullmatch(r"\d{1,4}", line):
                continue
            if re.fullmatch(r"[-–—_ ]{3,}", line):
                continue
            cleaned.append(line)
        page_text = "\n".join(cleaned)
        page_text = re.sub(r"(?<![.!?:;])\n(?!\n|CAP[IÍ]TULO|Cap[ií]tulo|CHAPTER|Chapter)", " ", page_text)
        page_text = re.sub(r"\n{3,}", "\n\n", page_text)
        cleaned_pages.append(page_text.strip())

    text = "\n\n".join(page for page in cleaned_pages if page)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(pdf_path: Path, output_path: Path, force: bool = False) -> Path:
    if cache_exists(output_path, force):
        log(f"Cache texto limpio: {file_info(output_path)}")
        return output_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"No se encontró el PDF: {pdf_path}")

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Falta PyMuPDF. Instala dependencias con: pip install -r requirements.txt") from exc

    document = fitz.open(pdf_path)
    page_count = document.page_count
    log(f"PDF abierto: {pdf_path} ({page_count} páginas)")
    pages = [page.get_text("text") for page in document]
    document.close()

    if not any(page.strip() for page in pages):
        raise RuntimeError(
            "El PDF no tiene texto extraíble. Probablemente es escaneado; corre OCR antes de usar esta pipeline."
        )

    cleaned = clean_extracted_text(pages)
    if not cleaned:
        raise RuntimeError("La limpieza dejó el texto vacío. Revisa el PDF o aplica OCR.")

    log(f"Texto extraído: {len(cleaned):,} caracteres limpios")
    write_text(output_path, cleaned)
    log(f"Texto limpio guardado: {file_info(output_path)}")
    return output_path
