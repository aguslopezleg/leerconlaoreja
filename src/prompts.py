SYSTEM_BASE = """Eres un editor senior de audiolibros, divulgación y guiones para YouTube.
Trabajas en español neutro, con claridad, precisión y calidez.
Nunca inventes datos que no estén apoyados por el material proporcionado.
Si el texto viene de un libro, resume y transforma; no copies grandes fragmentos."""


CHUNK_SUMMARY_PROMPT = """Resume el siguiente fragmento de un libro para una pipeline de video tipo audio overview.

Contexto acumulado de chunks anteriores:
\"\"\"
{rolling_context}
\"\"\"

Devuelve JSON válido con esta forma:
{{
  "chunk_id": {chunk_id},
  "ideas_principales": ["..."],
  "conceptos_importantes": ["..."],
  "ejemplos_utiles": ["..."],
  "aplicaciones_practicas": ["..."],
  "citas_o_frases_relevantes": ["..."],
  "conexiones_con_contexto": ["cómo este fragmento continúa, matiza o contradice ideas anteriores"],
  "dudas_o_referencias_pendientes": ["ideas que parecen incompletas y podrían resolverse más adelante"]
}}

Prioridades:
- Extrae ideas con suficiente contexto para poder escribir un guion más tarde.
- Usa el contexto acumulado para detectar continuidad, desarrollo de una tesis y referencias a ideas anteriores.
- No repitas todo el contexto acumulado; solo menciona conexiones útiles.
- Conserva ejemplos concretos cuando existan.
- Evita relleno y frases genéricas.
- Si hay citas, mantenlas breves.

Fragmento:
\"\"\"
{chunk_text}
\"\"\""""


MASTER_SUMMARY_PROMPT = """A partir de estos resúmenes de chunks, crea un resumen maestro del libro.

Devuelve JSON válido con esta forma:
{{
  "tesis_central": "...",
  "ideas_principales": ["5 a 10 ideas"],
  "estructura_recomendada_video": ["secciones sugeridas en orden"],
  "tono_sugerido": "...",
  "ejemplos_practicos": ["..."],
  "advertencias_o_matices": ["..."]
}}

Debe servir como mapa editorial para un video de YouTube de una sola voz, marca "Leer con la Oreja".

Resúmenes:
{chunk_summaries_json}"""


SCRIPT_PROMPT = """Escribe el guion narrativo final para un video de YouTube estilo "audio overview", con un solo narrador.

Datos:
- Título del episodio/libro: {title}
- Marca/canal: {brand_name}
- Idioma: {language}
- Duración objetivo: {duration_minutes} minutos
- Ritmo estimado: {words_per_minute} palabras por minuto
- Objetivo de palabras: entre {min_words} y {max_words}

Requisitos:
- Hook inicial fuerte.
- Introducción clara del libro.
- Explicación ordenada de ideas principales.
- Ejemplos cotidianos.
- Aplicaciones prácticas.
- Mini recapitulaciones.
- Cierre con reflexión final.
- Tono conversacional, claro y cálido.
- Sin diálogos entre varias voces.
- No uses indicaciones técnicas entre corchetes en el texto narrado.
- La duración es importante: escribe un guion desarrollado, no un resumen breve.
- Cada sección debe tener suficiente narración para audio continuo; evita párrafos demasiado cortos.

Devuelve JSON válido con esta forma:
{{
  "title": "...",
  "estimated_words": 3000,
  "target_duration_minutes": {duration_minutes},
  "sections": [
    {{
      "section_id": 1,
      "title": "Hook",
      "voiceover": "Texto narrado..."
    }}
  ]
}}

Resumen maestro:
{master_summary_json}"""


SCRIPT_EXPANSION_PROMPT = """El guion anterior quedó demasiado corto para el video.

Necesito que lo reescribas y lo expandas manteniendo el mismo enfoque editorial.

Datos:
- Título del episodio/libro: {title}
- Marca/canal: {brand_name}
- Idioma: {language}
- Duración objetivo: {duration_minutes} minutos
- Ritmo estimado: {words_per_minute} palabras por minuto
- Mínimo obligatorio: {min_words} palabras
- Máximo recomendado: {max_words} palabras
- El borrador anterior tenía solo {actual_words} palabras.

Expande con:
- ejemplos cotidianos
- transiciones entre ideas
- recapitulaciones breves
- aplicaciones prácticas
- matices y advertencias
- cierre más reflexivo

Devuelve JSON válido con la misma forma:
{{
  "title": "...",
  "estimated_words": 3000,
  "target_duration_minutes": {duration_minutes},
  "sections": [
    {{
      "section_id": 1,
      "title": "Hook",
      "voiceover": "Texto narrado..."
    }}
  ]
}}

Resumen maestro:
{master_summary_json}

Borrador anterior:
{previous_script_json}"""


SECTION_EXPANSION_PROMPT = """Expande una sección del guion para un video de YouTube estilo audio overview, con un solo narrador.

Datos:
- Título del episodio/libro: {title}
- Marca/canal: {brand_name}
- Idioma: {language}
- Sección {section_id}: {section_title}
- Objetivo de palabras para esta sección: entre {min_words} y {max_words}

Requisitos:
- Escribe narración continua, lista para TTS.
- Mantén tono conversacional, claro y cálido.
- Usa ejemplos cotidianos y transiciones naturales.
- No uses bullets, encabezados internos, marcas de escena ni texto entre corchetes.
- No copies frases largas del libro; transforma y explica.
- Esta sección debe sostenerse por sí sola, pero encajar con el resto del guion.

Devuelve JSON válido con esta forma:
{{
  "section_id": {section_id},
  "title": "{section_title}",
  "voiceover": "Texto narrado extenso..."
}}

Resumen maestro:
{master_summary_json}

Outline completo del guion:
{script_outline_json}

Borrador actual de esta sección:
\"\"\"
{current_voiceover}
\"\"\""""


VISUAL_STRUCTURE_PROMPT = """Convierte este guion en una estructura de producción visual simple.

Devuelve JSON válido con esta forma:
{{
  "sections": [
    {{
      "section_id": 1,
      "title": "Idea central",
      "voiceover": "...",
      "screen_text": "Pequeños hábitos, grandes resultados",
      "visual_type": "title_card",
      "estimated_start": "00:00:00",
      "estimated_duration_seconds": 60
    }}
  ]
}}

Reglas:
- Usa exactamente una sección visual por sección del guion.
- screen_text debe ser corto, potente y legible en pantalla.
- visual_type solo puede ser: title_card, key_phrase, quote_card, recap, neutral.
- No generes prompts de imagen.
- No sugieras imágenes IA salvo que se indique explícitamente que están habilitadas.
- Mantén el foco en títulos, frases clave y recapitulaciones.
- La suma aproximada de duraciones debe acercarse a {duration_minutes} minutos.

Imágenes IA habilitadas: {enable_ai_images}

Guion:
{script_json}"""


KEY_PHRASES_PROMPT = """Extrae frases breves para pantalla a partir del guion.
Devuelve solo frases en español neutro, claras y memorables, sin comillas, una por línea.

Guion:
{script_text}"""


YOUTUBE_METADATA_PROMPT = """Genera metadata editorial optimizada para YouTube para este video.

Datos:
- Título base del libro/episodio: {title}
- Canal/marca: {brand_name}
- Idioma: español
- Formato: audio overview narrado con una sola voz

Objetivo:
- El título debe ser atractivo, claro y buscable. Puede usar clickbait inteligente, pero sin mentir.
- Debe despertar curiosidad o urgencia: "la regla que cambia...", "por qué...", "esto explica...".
- La descripción debe sonar humana, cálida y profesional.
- Incluir una breve promesa del video, puntos principales y llamado suave a suscribirse.
- No inventes datos bibliográficos que no estén en el resumen.
- Tags útiles para descubrimiento, no frases larguísimas.
- thumbnail_text debe ser MUY corto, visual y poderoso: 3 a 7 palabras, en estilo miniatura viral.
- thumbnail_text debe funcionar como texto enorme sobre fondo amarillo/naranja, no como título académico.
- Enfoca thumbnail_text en curiosidad, tensión o beneficio: una idea difícil, una revelación, un error común, una regla que incomoda o una promesa concreta.
- Evita frases genéricas como "resumen del libro", "audio overview" o repetir simplemente el título del libro.
- thumbnail_badge debe ser una etiqueta corta tipo "AUDIOLIBRO", "RESUMEN NARRADO" o "IDEA CLAVE".

Devuelve JSON válido con esta forma:
{{
  "title": "máximo 100 caracteres",
  "description": "máximo 5000 caracteres",
  "tags": ["máximo 30 tags, cada uno breve"],
  "category_id": "27",
  "default_language": "es",
  "thumbnail_text": "frase grande para miniatura",
  "thumbnail_badge": "etiqueta corta"
}}

Resumen maestro:
{master_summary_json}

Extracto del guion:
\"\"\"
{script_excerpt}
\"\"\""""


THUMBNAIL_IMAGE_PROMPT = """Crea el FONDO visual de una miniatura de YouTube para un video de libros/audio overview.

Importante:
- NO escribas texto, letras, números, logotipos ni marcas de agua. El título se agregará después con tipografía real.
- Composición horizontal 16:9, alto contraste, estilo editorial/cinemático para YouTube.
- Debe estar basada en el contexto real del libro y del guion, no en fantasía genérica.
- Reserva el 55% izquierdo con espacio visual limpio, oscuro o degradado, para texto grande.
- Usa el lado derecho y el fondo para símbolos, atmósfera y metáforas visuales relacionadas con el libro.
- Estética llamativa, clara en tamaño pequeño, con colores cálidos, sobria/editorial y apta para un canal de libros.
- Evita imágenes de celebridades, autores reales o portadas de libros con copyright.
- Evita monstruos, dragones, demonios, calaveras, gore, horror, fantasía épica, armas y escenas de videojuego.
- Evita destrucción física: nada de ruinas, edificios destruidos, explosiones, fuego, humo denso, ciudades apocalípticas, paredes rotas, escombros o catástrofes.
- Si el concepto menciona "caos", represéntalo como desorden cotidiano o mental: escritorio desordenado, papeles sin texto, sombras, caminos bifurcados, reloj, puerta entreabierta, lluvia suave o ciudad nocturna intacta.
- Evita fondos saturados de demasiados objetos. Máximo 2 o 3 elementos simbólicos principales.
- No uses páginas con texto legible. Si aparecen libros o papeles, que no tengan letras reconocibles.

Título del video:
{video_title}

Texto grande que irá encima:
{thumbnail_title}

Tesis/tema central:
{central_thesis}

Contexto editorial del libro:
{book_context}

Dirección visual recomendada:
{visual_direction}

Ideas principales que deben inspirar el fondo:
{visual_ideas}

Marca/canal: {brand_name}
"""
