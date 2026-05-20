from __future__ import annotations

import base64
from io import BytesIO
import re
import unicodedata
from pathlib import Path
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from models import Config, MasterSummary, YouTubeMetadata
from prompts import THUMBNAIL_IMAGE_PROMPT
from utils import cache_exists, file_info, load_model, log, project_root, require_openai_client, timed, write_json


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return project_root() / path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _clean_title(value: str) -> str:
    value = re.sub(r"\s*\|\s*audio overview.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\|\s*resumen.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip() or "Audio overview"


def _load_metadata(metadata_path: Path) -> YouTubeMetadata | None:
    if metadata_path.exists():
        return load_model(metadata_path, YouTubeMetadata)
    return None


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(" ".join(current))
            current = [word]
            if len(lines) >= max_lines:
                break
        else:
            current.append(word)
    if current and len(lines) < max_lines:
        lines.append(" ".join(current))
    return lines


def _line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), "Áy", font=font)
    return bbox[3] - bbox[1]


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.ImageFont,
    xy: tuple[int, int],
    fill,
    gap: int,
    stroke_width: int = 0,
    stroke_fill=None,
) -> int:
    x, y = xy
    line_h = _line_height(draw, font)
    for line in lines:
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        y += line_h + gap
    return y


def _load_ai_title(metadata_path: Path, fallback: str) -> str:
    metadata = _load_metadata(metadata_path)
    if metadata and metadata.thumbnail_text:
        return metadata.thumbnail_text
    if metadata:
        return metadata.title
    return fallback


def _load_badge(metadata_path: Path) -> str:
    metadata = _load_metadata(metadata_path)
    if metadata and metadata.thumbnail_badge:
        return metadata.thumbnail_badge.upper()
    return "RESUMEN NARRADO"


def _local_clickbait_hook(master_summary_path: Path, fallback_title: str) -> str:
    fallback = _clean_title(fallback_title)
    if not master_summary_path.exists():
        return fallback
    master = load_model(master_summary_path, MasterSummary)
    source = " ".join([master.tesis_central, *master.ideas_principales]).lower()
    normalized = _normalize(source)
    if "orden" in normalized and "caos" in normalized:
        return "ORDEN EN TU CAOS"
    if "responsabilidad" in normalized:
        return "HAZTE CARGO"
    if "sufrim" in normalized or "sacrificio" in normalized:
        return "LA REGLA QUE DUELE"
    if "verdad" in normalized or "mentira" in normalized:
        return "NO TE MIENTAS"
    if "significado" in normalized or "sentido" in normalized:
        return "VIVE CON SENTIDO"
    return fallback


def _shorten_thumbnail_text(value: str, fallback: str) -> str:
    text = _clean_title(value)
    text = re.sub(r"^(por que|por qué|como|cómo)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(resumen|audiolibro|narrado|completo|libro)\b", "", text, flags=re.IGNORECASE)
    words = [word for word in text.strip(" .,:;!¡?¿").split() if word]
    if len(words) > 7:
        words = words[:7]
    if len(words) < 2:
        words = fallback.split()[:5]
    return " ".join(words).strip() or fallback


def _load_tagline(master_summary_path: Path) -> str:
    if not master_summary_path.exists():
        return "Una lectura narrada para escuchar con calma"
    master = load_model(master_summary_path, MasterSummary)
    if master.ideas_principales:
        return master.ideas_principales[0]
    return master.tesis_central


def _load_master(master_summary_path: Path) -> MasterSummary | None:
    if not master_summary_path.exists():
        return None
    return load_model(master_summary_path, MasterSummary)


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    max_lines: int,
    start_size: int,
    min_size: int = 54,
):
    size = start_size
    while size >= min_size:
        font = _font(size, bold=True)
        lines = _wrap_text(draw, text, font, max_width, max_lines)
        total_height = len(lines) * _line_height(draw, font) + max(0, len(lines) - 1) * 2
        if (
            lines
            and total_height <= max_height
            and all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines)
        ):
            return font, lines
        size -= 6
    font = _font(min_size, bold=True)
    return font, _wrap_text(draw, text, font, max_width, max_lines)


def _fit_font_for_text_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    max_lines: int,
    start_size: int,
    min_size: int,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    size = start_size
    while size >= min_size:
        font = _font(size, bold=True)
        lines = _wrap_text(draw, text, font, max_width, max_lines)
        line_h = _line_height(draw, font)
        gap = max(0, int(size * 0.02))
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * gap
        if lines and total_h <= max_height and all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines):
            return font, lines, gap
        size -= 6
    font = _font(min_size, bold=True)
    return font, _wrap_text(draw, text, font, max_width, max_lines), 0


def _cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    image = image.convert("RGB")
    ratio = image.width / image.height
    target_ratio = width / height
    if ratio > target_ratio:
        new_h = height
        new_w = int(new_h * ratio)
    else:
        new_w = width
        new_h = int(new_w / ratio)
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _thumbnail_title(title: str, metadata_path: Path, config: Config) -> str:
    metadata = _load_metadata(metadata_path)
    if config.thumbnail_text_source == "thumbnail_text":
        if metadata and metadata.thumbnail_text:
            return metadata.thumbnail_text
        return title
    if metadata and metadata.title:
        return metadata.title
    return title


def _visual_direction(master: MasterSummary | None) -> str:
    if not master:
        return (
            "Una escena editorial con libros, luz cálida, contraste entre sombra y claridad, "
            "y una metáfora visual de transformación personal."
        )
    source = _normalize(" ".join([master.tesis_central, *master.ideas_principales]))
    if "orden" in source and "caos" in source:
        return (
            "Una composición dividida entre orden y caos cotidiano: a la izquierda una zona limpia y oscura para texto; "
            "a la derecha una persona pequeña en una biblioteca o estudio cálido, frente a una puerta entreabierta que muestra "
            "una ciudad nocturna intacta o un escritorio desordenado. El caos debe sentirse mental, moral o doméstico, no físico. "
            "Sin destrucción, sin fuego, sin humo, sin ruinas, sin paredes rotas, sin escombros, sin criaturas, sin horror."
        )
    if "responsabilidad" in source:
        return (
            "Una persona frente a una mesa con libros, una escalera o camino iluminado, y una atmósfera de decisión adulta; "
            "visual de responsabilidad, claridad y peso emocional, sin fantasía ni terror."
        )
    if "verdad" in source or "mentira" in source:
        return (
            "Un escritorio con espejo, luz lateral y libros, simbolizando verdad personal y autoexamen; "
            "composición cinematográfica, sobria, con espacio vacío para texto."
        )
    if "sentido" in source or "significado" in source:
        return (
            "Una silueta humana mirando una luz al final de un camino interior, con libros y papeles sin texto legible; "
            "tono reflexivo, cálido y profundo, sin elementos fantásticos."
        )
    return (
        "Una escena conceptual de lectura y transformación personal, con libros, luz cálida, sombras profundas, "
        "un personaje humano anónimo y símbolos simples relacionados con el tema central."
    )


def _book_context(master: MasterSummary | None) -> str:
    if not master:
        return "Resumen narrado de un libro con ideas prácticas para la vida diaria."
    examples = "; ".join(master.ejemplos_practicos[:3]) or "aplicaciones prácticas en la vida cotidiana"
    nuances = "; ".join(master.advertencias_o_matices[:3]) or "matices y advertencias del libro"
    structure = "; ".join(master.estructura_recomendada_video[:5])
    return (
        f"Tono sugerido: {master.tono_sugerido}\n"
        f"Ejemplos prácticos: {examples}\n"
        f"Matices: {nuances}\n"
        f"Estructura del video: {structure}"
    )


def _build_ai_thumbnail_prompt(title: str, metadata_path: Path, master_summary_path: Path, config: Config) -> str:
    metadata = _load_metadata(metadata_path)
    master = _load_master(master_summary_path)
    video_title = metadata.title if metadata and metadata.title else title
    thumbnail_title = _thumbnail_title(title, metadata_path, config)
    thesis = master.tesis_central if master else "Resumen narrado de un libro con ideas prácticas y reflexión personal."
    ideas = master.ideas_principales[:5] if master else []
    visual_ideas = "\n".join(f"- {idea}" for idea in ideas) or "- Fondo conceptual relacionado con el tema del libro."
    return THUMBNAIL_IMAGE_PROMPT.format(
        video_title=video_title,
        thumbnail_title=thumbnail_title,
        central_thesis=thesis,
        book_context=_book_context(master),
        visual_direction=_visual_direction(master),
        visual_ideas=visual_ideas,
        brand_name=config.brand_name,
    )


def _image_from_openai_response(response) -> Image.Image:
    data = response.data[0]
    b64 = getattr(data, "b64_json", None)
    if b64:
        return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
    url = getattr(data, "url", None)
    if url:
        with urlopen(url, timeout=120) as result:
            return Image.open(BytesIO(result.read())).convert("RGB")
    raise RuntimeError("La Image API no devolvió b64_json ni url.")


def _generate_ai_background(title: str, config: Config, metadata_path: Path, master_summary_path: Path, output_dir: Path) -> Image.Image:
    prompt = _build_ai_thumbnail_prompt(title, metadata_path, master_summary_path, config)
    prompt_path = output_dir / "thumbnail_prompt.json"
    write_json(
        prompt_path,
        {
            "model": config.thumbnail_image_model,
            "quality": config.thumbnail_image_quality,
            "size": config.thumbnail_image_size,
            "prompt": prompt,
        },
    )
    log(f"Prompt miniatura IA guardado: {file_info(prompt_path)}")
    client = require_openai_client()
    kwargs = {
        "model": config.thumbnail_image_model,
        "prompt": prompt,
        "size": config.thumbnail_image_size,
        "quality": config.thumbnail_image_quality,
        "n": 1,
    }
    try:
        response = client.images.generate(**kwargs)
    except TypeError:
        minimal_kwargs = {
            "model": config.thumbnail_image_model,
            "prompt": prompt,
            "size": config.thumbnail_image_size,
            "n": 1,
        }
        response = client.images.generate(**minimal_kwargs)
    return _image_from_openai_response(response)


def _add_readability_overlay(image: Image.Image) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for x in range(width):
        alpha = int(185 * (1 - min(1, x / (width * 0.68))))
        draw.line((x, 0, x, height), fill=(0, 0, 0, alpha))
    draw.rectangle((0, 0, width, height), outline=(14, 14, 14, 255), width=16)
    image.alpha_composite(overlay)


def _draw_ai_thumbnail_text(image: Image.Image, title: str, config: Config, metadata_path: Path) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    metadata = _load_metadata(metadata_path)
    badge = (metadata.thumbnail_badge if metadata and metadata.thumbnail_badge else "RESUMEN NARRADO").upper()
    title_text = _thumbnail_title(title, metadata_path, config)
    title_text = _clean_title(title_text).upper()
    title_text = re.sub(r"\s+", " ", title_text)

    badge_font = _font(34, bold=True)
    badge_bbox = draw.textbbox((0, 0), badge, font=badge_font)
    badge_w = badge_bbox[2] - badge_bbox[0]
    draw.rounded_rectangle((56, 44, 108 + badge_w, 96), radius=12, fill=(255, 221, 46, 245))
    draw.text((82, 53), badge, font=badge_font, fill=(20, 20, 20))

    font, lines, gap = _fit_font_for_text_box(draw, title_text, 765, 430, 4, 104, 48)
    _draw_lines(
        draw,
        lines,
        font,
        (58, 132),
        (255, 247, 216),
        gap,
        stroke_width=5,
        stroke_fill=(7, 7, 7),
    )

    brand = config.brand_name.upper()
    brand_font = _font(30, bold=True)
    brand_bbox = draw.textbbox((0, 0), brand, font=brand_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    draw.rounded_rectangle((56, height - 82, 104 + brand_w, height - 36), radius=10, fill=(16, 16, 16, 220))
    draw.text((78, height - 76), brand, font=brand_font, fill=(255, 245, 214))


def _generate_ai_thumbnail(
    title: str,
    config: Config,
    metadata_path: Path,
    master_summary_path: Path,
    output_path: Path,
) -> Path:
    log(
        f"Generando fondo de miniatura con IA: modelo={config.thumbnail_image_model}, "
        f"size={config.thumbnail_image_size}, quality={config.thumbnail_image_quality}"
    )
    with timed("Llamada OpenAI imagen miniatura"):
        background = _generate_ai_background(title, config, metadata_path, master_summary_path, output_path.parent)
    raw_path = output_path.with_name(output_path.stem + "_ai_background.png")
    background.save(raw_path, "PNG")
    log(f"Fondo IA guardado: {file_info(raw_path)}")
    image = _cover_resize(background, config.thumbnail_width, config.thumbnail_height).convert("RGBA")
    _add_readability_overlay(image)
    _draw_ai_thumbnail_text(image, title, config, metadata_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, "JPEG", quality=94, optimize=True)
    log(f"Miniatura IA generada: {file_info(output_path)}")
    return output_path


def _soft_shadow(size: tuple[int, int], radius: int = 28) -> Image.Image:
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rectangle((0, 0, size[0], size[1]), fill=(0, 0, 0, 150))
    return shadow.filter(ImageFilter.GaussianBlur(radius))


def _paste_subject(image: Image.Image, config: Config, width: int, height: int) -> None:
    subject_path = _resolve_path(config.thumbnail_subject_path)
    subject_w = int(width * 0.38)
    subject_x = width - subject_w
    if not subject_path.exists():
        draw = ImageDraw.Draw(image, "RGBA")
        draw.polygon(
            [(subject_x - 60, 0), (width, 0), (width, height), (subject_x + 35, height)],
            fill=(247, 213, 72, 190),
        )
        draw.ellipse((width - 365, 82, width - 92, 355), fill=(22, 22, 22, 235))
        draw.ellipse((width - 335, 112, width - 122, 325), fill=(245, 203, 80, 255))
        draw.rounded_rectangle((width - 410, 330, width - 70, 750), radius=150, fill=(22, 22, 22, 235))
        return

    subject = Image.open(subject_path).convert("RGBA")
    subject = ImageOps.grayscale(subject).convert("RGB")
    subject = ImageEnhance.Contrast(subject).enhance(1.35)
    subject = ImageEnhance.Brightness(subject).enhance(1.05)
    target_w = subject_w
    target_h = height
    subject_ratio = subject.width / subject.height
    target_ratio = target_w / target_h
    if subject_ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * subject_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / subject_ratio)
    subject = subject.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    subject = subject.crop((left, top, left + target_w, top + target_h)).convert("RGBA")

    color_layer = Image.new("RGBA", (target_w, target_h), (251, 180, 34, 75))
    subject = Image.alpha_composite(subject, color_layer)

    fade = Image.new("L", (target_w, target_h), 255)
    fade_draw = ImageDraw.Draw(fade)
    for x in range(target_w):
        alpha = int(255 * min(1, max(0, (x - 35) / 180)))
        fade_draw.line((x, 0, x, target_h), fill=alpha)

    shadow = _soft_shadow((target_w, target_h), 34)
    image.paste(shadow, (subject_x - 18, 0), fade)
    image.paste(subject, (subject_x, 0), fade)


def _draw_burst(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, rays: int = 22) -> None:
    cx, cy = center
    for idx in range(rays):
        angle = idx * 360 / rays
        # Pillow's regular polygon support is enough here if we rotate through simple points.
        import math

        a1 = math.radians(angle - 3)
        a2 = math.radians(angle + 3)
        p1 = (cx + int(radius * 0.35 * math.cos(a1)), cy + int(radius * 0.35 * math.sin(a1)))
        p2 = (cx + int(radius * math.cos(math.radians(angle))), cy + int(radius * math.sin(math.radians(angle))))
        p3 = (cx + int(radius * 0.35 * math.cos(a2)), cy + int(radius * 0.35 * math.sin(a2)))
        draw.polygon([p1, p2, p3], fill=(255, 239, 122, 95))


def generate_thumbnail(
    title: str,
    config: Config,
    metadata_path: Path,
    master_summary_path: Path,
    output_path: Path | None = None,
    force: bool = False,
) -> Path:
    output_path = output_path or _resolve_path(config.thumbnail_path)
    if cache_exists(output_path, force):
        log(f"Cache miniatura: {file_info(output_path)}")
        return output_path

    if config.thumbnail_use_ai:
        try:
            return _generate_ai_thumbnail(title, config, metadata_path, master_summary_path, output_path)
        except Exception as exc:
            log(f"No se pudo generar miniatura con IA ({exc}). Uso plantilla local fallback.", level="WARN")

    width, height = config.thumbnail_width, config.thumbnail_height
    image = Image.new("RGB", (width, height), (245, 168, 36))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            warm = int(82 * (1 - x / width) + 62 * (1 - y / height))
            pixels[x, y] = (
                min(255, 232 + warm // 2),
                min(226, 132 + warm),
                max(14, 20 - warm // 10),
            )

    draw = ImageDraw.Draw(image, "RGBA")
    _draw_burst(draw, (720, 165), 680)
    draw.polygon([(780, 0), (width, 0), (width, height), (850, height)], fill=(255, 221, 86, 130))
    _paste_subject(image, config, width, height)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, width, height), outline=(15, 15, 15, 255), width=16)
    draw.rectangle((18, 18, width - 18, height - 18), outline=(255, 248, 210, 95), width=3)

    brand_font = _font(34, bold=True)
    eyebrow_font = _font(36, bold=True)
    tagline_font = _font(29, bold=True)
    small_font = _font(24, bold=True)

    label = _load_badge(metadata_path)
    label_bbox = draw.textbbox((0, 0), label, font=eyebrow_font)
    label_width = label_bbox[2] - label_bbox[0]
    draw.rounded_rectangle((54, 42, 112 + label_width, 98), radius=12, fill=(18, 18, 18, 245))
    draw.text((82, 51), label, font=eyebrow_font, fill=(255, 239, 116))

    fallback = "ESTO CAMBIA TODO"
    metadata = _load_metadata(metadata_path)
    title_source = metadata.thumbnail_text if metadata and metadata.thumbnail_text else ""
    if not title_source and metadata:
        title_source = metadata.title
    if not title_source:
        title_source = _local_clickbait_hook(master_summary_path, title)
    ai_title = _shorten_thumbnail_text(title_source, fallback)
    font, title_lines = _fit_font(draw, ai_title.upper(), 755, 390, 4, 126, 58)
    title_bottom = _draw_lines(
        draw,
        title_lines,
        font,
        (54, 126),
        (17, 18, 18),
        0,
        stroke_width=2,
        stroke_fill=(255, 232, 94),
    )

    underline_y = min(536, title_bottom + 18)
    draw.line((58, underline_y, 788, underline_y - 2), fill=(22, 22, 22, 255), width=12)
    draw.line((62, underline_y + 20, 724, underline_y + 12), fill=(22, 22, 22, 225), width=7)

    tagline = _load_tagline(master_summary_path)
    tagline = re.sub(r"\s+", " ", tagline).strip()
    tagline_lines = _wrap_text(draw, tagline, tagline_font, 710, 2)
    _draw_lines(draw, tagline_lines, tagline_font, (60, 590), (29, 28, 24), 5)

    brand = config.brand_name.upper()
    brand_bbox = draw.textbbox((0, 0), brand, font=brand_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    draw.rounded_rectangle((width - brand_w - 76, height - 84, width - 42, height - 36), radius=10, fill=(20, 20, 20, 218))
    draw.text((width - brand_w - 58, height - 78), brand, font=brand_font, fill=(245, 245, 245))
    draw.text((64, height - 48), "VIDEO PODCAST DE LIBROS", font=small_font, fill=(23, 23, 23, 220))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "JPEG", quality=92, optimize=True)
    log(f"Miniatura generada: {file_info(output_path)}")
    return output_path
