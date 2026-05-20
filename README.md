# Notebook Style Video

MVP local en Python para convertir un PDF de un libro en un video MP4 tipo audio overview / video podcast visualizado, con una sola voz, subtítulos, fondo visual simple y frases clave en pantalla.

El foco del proyecto es bajo costo, automatización y claridad narrativa. Por defecto no genera imágenes IA.

## Instalación

```bash
cd notebook_style_video
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

También necesitas `ffmpeg` instalado para concatenar audio y renderizar video:

```bash
brew install ffmpeg
```

## Configuración

```bash
cp .env.example .env
```

Edita `.env`:

```bash
OPENAI_API_KEY=tu_clave
ELEVENLABS_API_KEY=
```

Revisa `config.yaml` para cambiar modelos, voz, duración objetivo, FPS, resolución, proveedor TTS y subtítulos.

Para música de fondo, coloca un archivo autorizado en `input/music.mp3` y activa:

```yaml
enable_background_music: true
background_music_path: input/music.mp3
background_music_volume_db: -34
music_fade_seconds: 4
```

El estilo de narración TTS se controla con:

```yaml
tts_instructions: "Leé este texto con estilo de audiolibro: voz cálida, ritmo pausado y natural..."
```

Por defecto el video debe quedar entre 10 y 20 minutos:

```yaml
min_video_duration_minutes: 10
target_duration_minutes: 20
max_video_duration_minutes: 20
openai_max_output_tokens_script: 12000
```

## Uso rápido

Coloca un PDF en `input/book.pdf` y ejecuta:

```bash
python src/main.py --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Para generar todo desde el PDF y subirlo a YouTube en una sola orden:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Para probar ese flujo completo sin publicar:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20 --youtube-dry-run
```

Para generar solo un preview de 1 minuto:

```bash
python src/main.py render --title "Nombre del libro" --preview-seconds 60 --force
```

Ese comando guarda `output/video/preview_60s.mp4` y no pisa el video final.

Salida esperada:

- `output/text/book_clean.txt`
- `output/text/chunks/chunk_001.txt`
- `output/summaries/chunk_summaries.json`
- `output/summaries/master_summary.json`
- `output/scripts/final_script.txt`
- `output/scripts/final_script.json`
- `output/scripts/visual_production.json`
- `output/audio/narration.mp3`
- `output/subtitles/subtitles.srt`
- `output/video/final_video.mp4`

## Subir a YouTube

Primero instala las dependencias nuevas:

```bash
pip install -r requirements.txt
```

Configura OAuth de YouTube:

1. Crea un proyecto en Google Cloud.
2. Habilita YouTube Data API v3.
3. Crea credenciales OAuth de tipo Desktop app.
4. Descarga el JSON y guárdalo como `input/youtube_client_secret.json`.
5. Revisa `.env`:

```bash
YOUTUBE_CLIENT_SECRETS_FILE=input/youtube_client_secret.json
YOUTUBE_TOKEN_FILE=output/youtube_token.json
```

La metadata de YouTube se genera con IA desde `master_summary.json` y `final_script.txt`, y se guarda en:

```bash
output/scripts/youtube_metadata.json
```

Para generar/revisar la metadata sin subir:

```bash
python src/main.py youtube --title "12 reglas para vivir" --youtube-dry-run
```

Usa `--force` para regenerar esa metadata con IA:

```bash
python src/main.py youtube --title "12 reglas para vivir" --youtube-dry-run --force
```

Para subir el video final:

```bash
python src/main.py youtube --title "12 reglas para vivir"
```

Para generar/reutilizar toda la pipeline y subir al final:

```bash
python src/main.py publish --pdf input/book.pdf --title "12 reglas para vivir" --duration 20
```

El comando `youtube` también genera `output/video/thumbnail.jpg` y la aplica al video después de subirlo. La miniatura usa IA para crear un fondo relacionado con el contenido del video y luego superpone el título con tipografía real para que sea legible.

Para generar solo la miniatura:

```bash
python src/main.py thumbnail --title "12 reglas para vivir" --force
```

Por defecto se guarda también el prompt usado para la imagen en:

```bash
output/video/thumbnail_prompt.json
```

Si la API de imágenes falla, el sistema usa una plantilla local como fallback para no romper la pipeline.

Opciones útiles:

```bash
python src/main.py youtube \
  --youtube-title "12 reglas para vivir | Resumen narrado en español" \
  --youtube-description "Descripción personalizada..." \
  --youtube-tags "libros,Jordan Peterson,desarrollo personal,audiolibro" \
  --privacy-status unlisted
```

La configuración base vive en `config.yaml`:

```yaml
youtube_privacy_status: unlisted
youtube_category_id: "27"
youtube_default_language: es
youtube_made_for_kids: false
youtube_license: youtube
thumbnail_use_ai: true
thumbnail_image_model: gpt-image-1.5
thumbnail_image_quality: medium
thumbnail_image_size: 1536x1024
thumbnail_text_source: thumbnail_text
```

Si el guion o el audio quedaron demasiado cortos en una corrida anterior, regenera desde el guion:

```bash
python src/main.py script --title "Nombre del libro" --duration 20 --force
python src/main.py tts --force
python src/main.py subtitles --force
python src/main.py render --title "Nombre del libro" --force
```

Si el modelo devuelve un guion corto, el paso `script` reintenta y luego expande sección por sección con metas de palabras propias hasta acercarse al rango configurado.

## Pasos individuales

```bash
python src/main.py extract --pdf input/book.pdf
python src/main.py summarize
python src/main.py script --title "Nombre del libro" --duration 20
python src/main.py tts
python src/main.py subtitles
python src/main.py render --title "Nombre del libro"
```

Usa `--force` para regenerar un paso aunque ya exista el archivo intermedio:

```bash
python src/main.py script --title "Nombre del libro" --force
```

## Costos estimados

Los costos dependen del largo del PDF, los modelos configurados y la duración del audio. El diseño intenta minimizarlos así:

- modelo económico para resúmenes por chunk
- memoria acumulada entre chunks para conservar continuidad sin sumar otra llamada por fragmento
- modelo mejor solo para resumen maestro y guion final
- archivos intermedios cacheados
- TTS no se regenera si el guion y la voz no cambiaron
- sin imágenes IA por defecto

Para bajar costos, reduce `chunk_size_chars`, usa modelos más económicos o ejecuta solo los pasos que necesites.

## Memoria entre chunks

Cada resumen de chunk recibe un contexto acumulado de los resúmenes anteriores. Esto ayuda a detectar continuidad de capítulos, ideas que se desarrollan en varias secciones y matices que aparecerían cortados si cada fragmento se leyera aislado.

Puedes ajustar el tamaño de esa memoria en `config.yaml`:

```yaml
rolling_context_max_chars: 6000
```

## Subtítulos y alineación

La pipeline siempre genera primero el audio TTS y después los subtítulos. Hay tres modos:

- `approximate`: fallback barato; reparte frases del guion según la duración real del audio.
- `faster_whisper`: transcribe el audio real y genera SRT por segmentos.
- `whisperx`: transcribe el audio real, alinea palabras y agrupa word-level timestamps en bloques SRT.

Config recomendado para mejor sincronización:

```yaml
subtitle_alignment_mode: whisperx
```

WhisperX es opcional porque instala dependencias pesadas como PyTorch y modelos de alineación. Si no lo tienes instalado, el comando fallará con una instrucción clara:

```bash
pip install whisperx
```

La opción antigua sigue funcionando:

```yaml
use_whisper_subtitles: true
```

Eso equivale a `subtitle_alignment_mode: faster_whisper`.

## Limitaciones del MVP

- Si el PDF es escaneado y no tiene texto seleccionable, necesitas OCR antes.
- La limpieza de headers/footers es heurística.
- La visualización de audio es simple y reutilizable.
- ElevenLabs está preparado como interfaz, pero no implementado.
- La sincronización perfecta de subtítulos requiere `subtitle_alignment_mode: whisperx`.
- El render rechaza audios fuera del rango `min_video_duration_minutes` / `max_video_duration_minutes`.
- El render prioriza estabilidad local sobre diseño complejo.

## Próximos pasos sugeridos

- Agregar OCR opcional con Tesseract.
- Implementar `ElevenLabsTTSProvider`.
- Mejorar detección de capítulos.
- Generar waveform real desde amplitud del audio.
- Agregar plantillas visuales por tipo de libro.
- Añadir tests unitarios para limpieza, chunking y SRT.
