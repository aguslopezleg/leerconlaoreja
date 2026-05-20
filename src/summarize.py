from __future__ import annotations

import json
from pathlib import Path

from models import ChunkSummaries, ChunkSummary, Config, MasterSummary
from prompts import CHUNK_SUMMARY_PROMPT, MASTER_SUMMARY_PROMPT, SYSTEM_BASE
from utils import cache_exists, file_info, load_model, log, openai_json, read_text, require_openai_client, timed, write_json


def _compact_items(items: list[str], limit: int = 4) -> str:
    return "; ".join(item.strip() for item in items[:limit] if item.strip())


def build_rolling_context(summaries: list[ChunkSummary], max_chars: int) -> str:
    if not summaries:
        return "Aún no hay contexto previo; este es el primer fragmento."

    lines: list[str] = []
    for summary in summaries:
        parts = [
            f"Chunk {summary.chunk_id}",
            f"ideas: {_compact_items(summary.ideas_principales)}",
        ]
        concepts = _compact_items(summary.conceptos_importantes, limit=3)
        if concepts:
            parts.append(f"conceptos: {concepts}")
        connections = _compact_items(summary.conexiones_con_contexto, limit=2)
        if connections:
            parts.append(f"conexiones: {connections}")
        pending = _compact_items(summary.dudas_o_referencias_pendientes, limit=2)
        if pending:
            parts.append(f"pendiente: {pending}")
        lines.append(" | ".join(parts))

    context = "\n".join(lines)
    if len(context) <= max_chars:
        return context
    return context[-max_chars:]


def summarize_chunks(chunks_dir: Path, output_path: Path, config: Config, force: bool = False) -> ChunkSummaries:
    if cache_exists(output_path, force):
        result = load_model(output_path, ChunkSummaries)
        log(f"Cache resúmenes de chunks: {file_info(output_path)} ({len(result.summaries)} resúmenes)")
        return result

    chunk_paths = sorted(chunks_dir.glob("chunk_*.txt"))
    if not chunk_paths:
        raise RuntimeError(f"No hay chunks en {chunks_dir}. Ejecuta primero el paso extract.")

    client = require_openai_client()
    log(
        f"Resumiendo {len(chunk_paths)} chunks con modelo={config.openai_model_summary}, "
        f"memoria={config.rolling_context_max_chars:,} caracteres"
    )
    summaries: list[ChunkSummary] = []
    for index, chunk_path in enumerate(chunk_paths, start=1):
        chunk_text = read_text(chunk_path)
        rolling_context = build_rolling_context(summaries, config.rolling_context_max_chars)
        log(
            f"Chunk {index}/{len(chunk_paths)}: {chunk_path.name}, "
            f"{len(chunk_text):,} caracteres, contexto {len(rolling_context):,} caracteres"
        )
        prompt = CHUNK_SUMMARY_PROMPT.format(
            chunk_id=index,
            rolling_context=rolling_context,
            chunk_text=chunk_text,
        )
        with timed(f"Llamada OpenAI resumen chunk {index}/{len(chunk_paths)}"):
            summary = openai_json(
                client=client,
                model=config.openai_model_summary,
                prompt=prompt,
                response_model=ChunkSummary,
                schema_name="chunk_summary",
                system=SYSTEM_BASE,
            )
        summaries.append(summary)
        log(
            f"Chunk {index} resumido: {len(summary.ideas_principales)} ideas, "
            f"{len(summary.conceptos_importantes)} conceptos, {len(summary.conexiones_con_contexto)} conexiones"
        )

    result = ChunkSummaries(
        summaries=summaries,
        rolling_context=build_rolling_context(summaries, config.rolling_context_max_chars),
    )
    write_json(output_path, result.model_dump())
    log(f"Resúmenes guardados: {file_info(output_path)}")
    return result


def create_master_summary(
    chunk_summaries_path: Path,
    output_path: Path,
    config: Config,
    force: bool = False,
) -> MasterSummary:
    if cache_exists(output_path, force):
        log(f"Cache resumen maestro: {file_info(output_path)}")
        return load_model(output_path, MasterSummary)

    chunk_summaries = load_model(chunk_summaries_path, ChunkSummaries)
    client = require_openai_client()
    log(
        f"Creando resumen maestro desde {len(chunk_summaries.summaries)} chunks "
        f"con modelo={config.openai_model_script}"
    )
    prompt = MASTER_SUMMARY_PROMPT.format(
        chunk_summaries_json=json.dumps(chunk_summaries.model_dump(), ensure_ascii=False, indent=2)
    )
    with timed("Llamada OpenAI resumen maestro"):
        result = openai_json(
            client=client,
            model=config.openai_model_script,
            prompt=prompt,
            response_model=MasterSummary,
            schema_name="master_summary",
            system=SYSTEM_BASE,
        )
    write_json(output_path, result.model_dump())
    log(f"Resumen maestro guardado: {file_info(output_path)}")
    return result
