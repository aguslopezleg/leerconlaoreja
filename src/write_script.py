from __future__ import annotations

import json
import math
from pathlib import Path

from models import Config, ExpandedScriptSection, FinalScript, MasterSummary, ScriptSection, VisualProduction, VisualSection
from prompts import SECTION_EXPANSION_PROMPT, SCRIPT_EXPANSION_PROMPT, SCRIPT_PROMPT, SYSTEM_BASE, VISUAL_STRUCTURE_PROMPT
from utils import cache_exists, file_info, load_model, log, openai_json, seconds_to_hhmmss, timed, write_json, write_text, word_count


def _target_words_for_section(section: ScriptSection, total_current_words: int, target_words: int, section_count: int) -> tuple[int, int]:
    current = max(1, word_count(section.voiceover))
    proportional = int(target_words * current / max(1, total_current_words))
    baseline = math.ceil(target_words / max(1, section_count) * 0.75)
    target = max(baseline, proportional)
    return max(180, int(target * 0.9)), max(220, int(target * 1.15))


def _expand_script_by_section(
    client,
    draft: FinalScript,
    master: MasterSummary,
    title: str,
    config: Config,
    target_words: int,
) -> FinalScript:
    total_current_words = max(1, word_count(draft.text))
    outline = [
        {
            "section_id": section.section_id,
            "title": section.title,
            "current_words": word_count(section.voiceover),
        }
        for section in draft.sections
    ]
    log(
        f"Expansión sección por sección: {len(draft.sections)} secciones, "
        f"borrador={total_current_words:,} palabras, objetivo={target_words:,}"
    )

    expanded_sections: list[ScriptSection] = []
    for index, section in enumerate(draft.sections, start=1):
        min_section_words, max_section_words = _target_words_for_section(
            section,
            total_current_words=total_current_words,
            target_words=target_words,
            section_count=len(draft.sections),
        )
        log(
            f"Expandiendo sección {index}/{len(draft.sections)} "
            f"({section.title}): objetivo {min_section_words:,}-{max_section_words:,} palabras"
        )
        prompt = SECTION_EXPANSION_PROMPT.format(
            title=title,
            brand_name=config.brand_name,
            language=config.output_language,
            section_id=section.section_id,
            section_title=section.title.replace('"', "'"),
            min_words=min_section_words,
            max_words=max_section_words,
            master_summary_json=json.dumps(master.model_dump(), ensure_ascii=False, indent=2),
            script_outline_json=json.dumps(outline, ensure_ascii=False, indent=2),
            current_voiceover=section.voiceover,
        )
        with timed(f"Llamada OpenAI expansión sección {index}/{len(draft.sections)}"):
            expanded = openai_json(
                client=client,
                model=config.openai_model_script,
                prompt=prompt,
                response_model=ExpandedScriptSection,
                schema_name="expanded_script_section",
                system=SYSTEM_BASE,
                max_output_tokens=config.openai_max_output_tokens_script,
            )
        section_words = word_count(expanded.voiceover)
        log(f"Sección {index} expandida: {section_words:,} palabras")
        expanded_sections.append(
            ScriptSection(
                section_id=section.section_id,
                title=expanded.title or section.title,
                voiceover=expanded.voiceover,
            )
        )

    result = FinalScript(
        title=draft.title,
        estimated_words=0,
        target_duration_minutes=draft.target_duration_minutes,
        sections=expanded_sections,
    )
    result.estimated_words = word_count(result.text)
    log(f"Guion expandido por secciones: {result.estimated_words:,} palabras")
    return result


def write_final_script(
    master_summary_path: Path,
    script_json_path: Path,
    script_text_path: Path,
    title: str,
    config: Config,
    force: bool = False,
) -> FinalScript:
    if cache_exists(script_json_path, force) and cache_exists(script_text_path, force):
        result = load_model(script_json_path, FinalScript)
        min_words = max(
            config.min_video_duration_minutes * config.words_per_minute,
            int(config.target_duration_minutes * config.words_per_minute * 0.75),
        )
        actual_words = word_count(result.text)
        log(
            f"Cache guion final: {file_info(script_text_path)} "
            f"({actual_words:,} palabras, {len(result.sections)} secciones)"
        )
        if actual_words < min_words:
            raise RuntimeError(
                f"El guion cacheado es demasiado corto ({actual_words:,} palabras; mínimo {min_words:,}). "
                "Regenera con: python src/main.py script --force"
            )
        return result

    master = load_model(master_summary_path, MasterSummary)
    target_words = config.target_duration_minutes * config.words_per_minute
    min_words = max(config.min_video_duration_minutes * config.words_per_minute, int(target_words * 0.75))
    max_words = config.max_video_duration_minutes * config.words_per_minute
    log(
        f"Generando guion con modelo={config.openai_model_script}; objetivo={target_words:,} palabras, "
        f"mínimo={min_words:,}, máximo={max_words:,}"
    )

    prompt = SCRIPT_PROMPT.format(
        title=title,
        brand_name=config.brand_name,
        language=config.output_language,
        duration_minutes=config.target_duration_minutes,
        words_per_minute=config.words_per_minute,
        min_words=min_words,
        max_words=max_words,
        master_summary_json=json.dumps(master.model_dump(), ensure_ascii=False, indent=2),
    )
    from utils import require_openai_client

    client = require_openai_client()
    result: FinalScript | None = None
    for attempt in range(2):
        if attempt == 0:
            active_prompt = prompt
            log("Intento de guion 1/2: borrador completo")
        else:
            log(f"Intento de guion 2/2: expansión porque el borrador tuvo {result.estimated_words:,} palabras")
            active_prompt = SCRIPT_EXPANSION_PROMPT.format(
                title=title,
                brand_name=config.brand_name,
                language=config.output_language,
                duration_minutes=config.target_duration_minutes,
                words_per_minute=config.words_per_minute,
                min_words=min_words,
                max_words=max_words,
                actual_words=result.estimated_words if result else 0,
                master_summary_json=json.dumps(master.model_dump(), ensure_ascii=False, indent=2),
                previous_script_json=json.dumps(result.model_dump() if result else {}, ensure_ascii=False, indent=2),
            )

        with timed(f"Llamada OpenAI guion intento {attempt + 1}/2"):
            result = openai_json(
                client=client,
                model=config.openai_model_script,
                prompt=active_prompt,
                response_model=FinalScript,
                schema_name="final_script",
                system=SYSTEM_BASE,
                max_output_tokens=config.openai_max_output_tokens_script,
            )
        result.estimated_words = word_count(result.text)
        log(f"Guion intento {attempt + 1}: {result.estimated_words:,} palabras, {len(result.sections)} secciones")
        if result.estimated_words >= min_words:
            break

    if result is None:
        raise RuntimeError("No se pudo generar el guion.")
    result.estimated_words = word_count(result.text)
    if result.estimated_words < min_words:
        result = _expand_script_by_section(
            client=client,
            draft=result,
            master=master,
            title=title,
            config=config,
            target_words=target_words,
        )
        result.estimated_words = word_count(result.text)
    if result.estimated_words < min_words:
        raise RuntimeError(
            f"El guion quedó demasiado corto ({result.estimated_words} palabras). "
            f"Para al menos {config.min_video_duration_minutes} minutos se necesitan unas {min_words}. "
            "Vuelve a correr el paso script con --force o usa un modelo de guion más fuerte."
        )
    if result.estimated_words > max_words:
        log(
            f"Advertencia: el guion tiene {result.estimated_words} palabras y podría superar "
            f"{config.max_video_duration_minutes} minutos.",
            level="WARN",
        )

    write_json(script_json_path, result.model_dump())
    write_text(script_text_path, result.text)
    log(f"Guion JSON guardado: {file_info(script_json_path)}")
    log(f"Guion TXT guardado: {file_info(script_text_path)}")
    return result


def _fallback_visual_structure(script: FinalScript, duration_minutes: int) -> VisualProduction:
    total_seconds = duration_minutes * 60
    section_count = max(1, len(script.sections))
    base_duration = max(10, total_seconds // section_count)
    sections: list[VisualSection] = []
    elapsed = 0
    for section in script.sections:
        words = section.voiceover.split()
        screen_text = " ".join(words[:8]).strip(" .,:;") or section.title
        sections.append(
            VisualSection(
                section_id=section.section_id,
                title=section.title,
                voiceover=section.voiceover,
                screen_text=screen_text,
                visual_type="title_card" if section.section_id == 1 else "key_phrase",
                estimated_start=seconds_to_hhmmss(elapsed),
                estimated_duration_seconds=base_duration,
            )
        )
        elapsed += base_duration
    return VisualProduction(sections=sections)


def write_visual_production(
    script_json_path: Path,
    visual_json_path: Path,
    config: Config,
    force: bool = False,
) -> VisualProduction:
    if cache_exists(visual_json_path, force):
        result = load_model(visual_json_path, VisualProduction)
        log(f"Cache estructura visual: {file_info(visual_json_path)} ({len(result.sections)} secciones)")
        return result

    script = load_model(script_json_path, FinalScript)
    log(f"Generando estructura visual con modelo={config.openai_model_visual} para {len(script.sections)} secciones")
    prompt = VISUAL_STRUCTURE_PROMPT.format(
        duration_minutes=config.target_duration_minutes,
        enable_ai_images=str(config.enable_ai_images).lower(),
        script_json=json.dumps(script.model_dump(), ensure_ascii=False, indent=2),
    )
    from utils import require_openai_client

    try:
        client = require_openai_client()
        with timed("Llamada OpenAI estructura visual"):
            result = openai_json(
                client=client,
                model=config.openai_model_visual,
                prompt=prompt,
                response_model=VisualProduction,
                schema_name="visual_production",
                system=SYSTEM_BASE,
            )
    except Exception as exc:
        log(f"No se pudo generar estructura visual con OpenAI; usando fallback local. Motivo: {exc}", level="WARN")
        result = _fallback_visual_structure(script, config.target_duration_minutes)

    write_json(visual_json_path, result.model_dump())
    log(f"Estructura visual guardada: {file_info(visual_json_path)} ({len(result.sections)} secciones)")
    return result
