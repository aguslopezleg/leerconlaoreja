# Leer con la Oreja

MVP local en Python para convertir un PDF de un libro en un video MP4 estilo audio overview / video podcast visualizado, con una sola voz, subtítulos, fondo visual, frases clave, miniatura y subida opcional a YouTube.

El proyecto prioriza automatización, bajo costo, claridad narrativa y archivos intermedios cacheados para no repetir llamadas caras.

## Qué Genera

- Texto limpio extraído desde PDF.
- Chunks del libro.
- Resúmenes por chunk con memoria acumulada.
- Resumen maestro del libro.
- Guion narrativo en español neutro.
- Estructura visual por secciones.
- Audio TTS con una sola voz.
- Subtítulos SRT desde el audio real o aproximados.
- Video MP4 1920x1080 apto para YouTube.
- Miniatura generada con IA visual y texto superpuesto legible.
- Metadata de YouTube generada con IA: título, descripción, tags y badge.
- Upload a YouTube mediante OAuth.

## Instalación

```bash
cd notebook_style_video
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

También necesitas `ffmpeg`:

```bash
brew install ffmpeg
```

## Configuración

Copia el archivo de entorno:

```bash
cp .env.example .env
```

Edita `.env`:

```bash
OPENAI_API_KEY=tu_clave
ELEVENLABS_API_KEY=
YOUTUBE_CLIENT_SECRETS_FILE=input/youtube_client_secret.json
YOUTUBE_TOKEN_FILE=output/youtube_token.json
```

La configuración principal vive en `config.yaml`.

## Uso Rápido

Coloca un PDF en `input/book.pdf` y genera el video:

```bash
python src/main.py --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Generar todo desde un PDF y subir a YouTube:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Probar el flujo completo sin publicar:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20 --youtube-dry-run
```

Regenerar todo ignorando caches:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20 --force
```

## Comandos

Pipeline completa sin subir:

```bash
python src/main.py all --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Pipeline completa con upload:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Pasos individuales:

```bash
python src/main.py extract --pdf input/book.pdf
python src/main.py summarize
python src/main.py script --title "Nombre del libro" --duration 20
python src/main.py tts
python src/main.py subtitles
python src/main.py render --title "Nombre del libro"
python src/main.py thumbnail --title "Nombre del libro"
python src/main.py youtube --title "Nombre del libro"
```

Usa `--force` para regenerar aunque existan archivos cacheados:

```bash
python src/main.py script --title "Nombre del libro" --force
```

## Scheduler Local

El scheduler funciona como administrador local del canal. Puede mirar una carpeta de PDFs, armar un calendario editorial cada 3 días, generar el video cuando corresponda, subirlo a YouTube y notificar por Telegram.

Carpeta de PDFs pendientes:

```bash
input/queue/
```

Cola/plan editorial persistente:

```bash
output/scheduler/jobs.json
```

Ese archivo guarda qué PDF procesar, título, fecha programada, duración, estado, intentos, errores, URL de YouTube y timestamps. Como está dentro de `output/`, no se sube a Git.

Config:

```yaml
scheduler_queue_dir: input/queue
scheduler_interval_days: 3
scheduler_publish_time: "09:00"
scheduler_default_publish: true
telegram_notifications_enabled: false
```

Organizar PDFs nuevos y asignarles fecha cada 3 días:

```bash
python src/main.py schedule-organize
```

Ejecutar el administrador como lo haría cron:

```bash
python src/main.py schedule-tick
```

`schedule-tick` hace dos cosas:

1. Escanea `input/queue/` y agrega PDFs nuevos al calendario.
2. Ejecuta trabajos `pending` cuya fecha `scheduled_for` ya llegó.

Agregar un trabajo que genere todo y suba a YouTube:

```bash
python src/main.py schedule-add --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Agregar un trabajo que genere el video pero no publique:

```bash
python src/main.py schedule-add --pdf input/book.pdf --title "Nombre del libro" --duration 20 --schedule-no-publish
```

Agregar un trabajo de prueba que llega hasta YouTube en dry-run:

```bash
python src/main.py schedule-add --pdf input/book.pdf --title "Nombre del libro" --duration 20 --youtube-dry-run
```

Ver la cola:

```bash
python src/main.py schedule-list
```

Ejecutar todos los trabajos pendientes:

```bash
python src/main.py schedule-run
```

Ejecutar solo un trabajo pendiente:

```bash
python src/main.py schedule-run --schedule-limit 1
```

Forzar ejecución de cualquier trabajo pendiente aunque su fecha futura no haya llegado:

```bash
python src/main.py schedule-run --schedule-all-pending
```

Reintentar trabajos fallidos:

```bash
python src/main.py schedule-reset-failed
python src/main.py schedule-run
```

El scheduler procesa los trabajos en orden y marca cada uno como:

- `pending`
- `running`
- `succeeded`
- `failed`

Si un trabajo falla, guarda el error en `last_error` y sigue con el siguiente.

Para correrlo diariamente con cron, por ejemplo a las 9 AM:

```cron
0 9 * * * cd /ruta/a/notebook_style_video && .venv/bin/python src/main.py schedule-tick >> output/scheduler/cron.log 2>&1
```

## Telegram

El administrador puede avisar por Telegram cuando:

- empieza un trabajo
- un video queda listo
- se sube un video y hay URL
- falla un trabajo
- se actualiza el plan editorial

Crea un bot con BotFather y configura `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456:token
TELEGRAM_CHAT_ID=123456789
```

Activa notificaciones:

```yaml
telegram_notifications_enabled: true
```

Prueba el bot:

```bash
python src/main.py telegram-test
```

## Preview De 1 Minuto

Para revisar cómo va quedando el video sin renderizar todo:

```bash
python src/main.py render --title "Nombre del libro" --preview-seconds 60 --force
```

Salida:

```bash
output/video/preview_60s.mp4
```

El preview no pisa `output/video/final_video.mp4`.

## Salidas

La pipeline genera:

```bash
output/text/book_clean.txt
output/text/chunks/chunk_001.txt
output/summaries/chunk_summaries.json
output/summaries/master_summary.json
output/scripts/final_script.txt
output/scripts/final_script.json
output/scripts/visual_production.json
output/scripts/youtube_metadata.json
output/audio/narration.mp3
output/subtitles/subtitles.srt
output/video/final_video.mp4
output/video/thumbnail.jpg
output/video/thumbnail_ai_background.png
output/video/thumbnail_prompt.json
```

`output/` está ignorado por Git porque contiene artefactos generados, audio, video, tokens y archivos pesados.

## YouTube

La subida usa OAuth, no una API key simple.

Pasos en Google Cloud:

1. Crea un proyecto en Google Cloud.
2. Habilita **YouTube Data API v3**.
3. Configura **OAuth consent screen**.
4. Crea credenciales OAuth tipo **Desktop app**.
5. Descarga el JSON como:

```bash
input/youtube_client_secret.json
```

6. Si la app está en modo Testing, agrega tu Gmail en **OAuth consent screen** → **Audience/Test users**.

Si ves este error:

```text
Error 403: access_denied
La app se está probando y solo pueden acceder testers aprobados
```

significa que el email con el que intentas autorizar no está agregado como tester.

Dry-run de YouTube:

```bash
python src/main.py youtube --title "Nombre del libro" --youtube-dry-run
```

Subir el video final ya generado:

```bash
python src/main.py youtube --title "Nombre del libro"
```

Generar todo y subir:

```bash
python src/main.py publish --pdf input/book.pdf --title "Nombre del libro" --duration 20
```

Opciones útiles:

```bash
python src/main.py youtube \
  --youtube-title "Título personalizado" \
  --youtube-description "Descripción personalizada..." \
  --youtube-tags "libros,audiolibro,resumen de libros" \
  --privacy-status unlisted
```

Privacidad por defecto:

```yaml
youtube_privacy_status: unlisted
youtube_category_id: "27"
youtube_default_language: es
youtube_made_for_kids: false
youtube_license: youtube
```

Después de la primera autorización, el token queda en:

```bash
output/youtube_token.json
```

## Miniaturas IA

Las miniaturas se generan con IA en dos capas:

1. La IA genera el fondo visual relacionado con el libro.
2. Python superpone el título con tipografía real para evitar texto deformado.

Comando:

```bash
python src/main.py thumbnail --title "Nombre del libro" --force
```

Archivos:

```bash
output/video/thumbnail.jpg
output/video/thumbnail_ai_background.png
output/video/thumbnail_prompt.json
```

Configuración:

```yaml
thumbnail_use_ai: true
thumbnail_image_model: gpt-image-1.5
thumbnail_image_quality: medium
thumbnail_image_size: 1536x1024
thumbnail_text_source: thumbnail_text
thumbnail_width: 1280
thumbnail_height: 720
```

El prompt de miniatura recibe contexto del libro:

- tesis central
- tono sugerido
- ejemplos prácticos
- matices
- estructura del video
- ideas principales

También evita explícitamente fondos de destrucción:

- sin ruinas
- sin explosiones
- sin fuego
- sin humo denso
- sin ciudades apocalípticas
- sin monstruos, dragones, calaveras o fantasía épica

Si la API de imágenes falla, el sistema usa una plantilla local como fallback para no romper la pipeline.

## Guion Y Duración

Por defecto apunta a un video entre 10 y 20 minutos:

```yaml
min_video_duration_minutes: 10
target_duration_minutes: 20
max_video_duration_minutes: 20
words_per_minute: 150
openai_max_output_tokens_script: 12000
```

El paso `script` reintenta si el guion queda corto y luego expande sección por sección.

Para regenerar desde el guion si algo quedó corto:

```bash
python src/main.py script --title "Nombre del libro" --duration 20 --force
python src/main.py tts --force
python src/main.py subtitles --force
python src/main.py render --title "Nombre del libro" --force
```

## TTS

El TTS usa una sola voz para todo el guion.

Configuración actual:

```yaml
tts_provider: openai
tts_model: gpt-4o-mini-tts
tts_voice: echo
tts_instructions: "Leé este texto con estilo de audiolibro: voz cálida, ritmo pausado y natural, buena dicción, pausas expresivas y tono envolvente. Narrá como si estuvieras contando una historia íntima, con emoción sutil y sin sobreactuar."
```

Hay una interfaz base `TTSProvider` y un placeholder para ElevenLabs.

## Música

La pipeline puede mezclar música de fondo local. Debe ser un archivo autorizado por ti.

```yaml
enable_background_music: true
background_music_path: input/music.mp3
background_music_volume_db: -34
music_fade_seconds: 4
```

No descarga música desde YouTube ni desde fuentes no autorizadas.

## Subtítulos

La pipeline genera primero el audio TTS y después los subtítulos.

Modos:

- `approximate`: divide el guion por frases y distribuye según duración real del audio.
- `faster_whisper`: transcribe el audio real por segmentos.
- `whisperx`: transcribe y alinea palabras para SRT más preciso.

Config recomendada:

```yaml
subtitle_alignment_mode: whisperx
whisperx_model: small
whisperx_device: cpu
whisperx_compute_type: int8
whisperx_batch_size: 8
```

Si WhisperX no está instalado, usa:

```bash
pip install whisperx
```

Fallback barato:

```yaml
subtitle_alignment_mode: approximate
```

## Memoria Entre Chunks

Cada resumen de chunk recibe contexto acumulado de resúmenes anteriores. Esto ayuda cuando un capítulo desarrolla ideas conectadas en varias partes.

```yaml
chunk_size_chars: 32000
rolling_context_max_chars: 6000
```

## Costos

El diseño reduce costos así:

- modelo barato para resúmenes por chunk
- modelo mejor solo para guion y piezas editoriales importantes
- caches para texto, resúmenes, guion, audio, subtítulos, video y miniatura
- TTS no se regenera si el guion y la voz no cambian
- miniaturas IA separadas del render de video
- previews cortos para revisar antes de renderizar todo

## Git Y Seguridad

No subas secretos ni artefactos pesados.

El `.gitignore` excluye:

```bash
.env
.venv/
input/*.pdf
input/youtube_client_secret.json
input/music.mp3
output/
```

Para pushear el repo:

```bash
git init
git branch -M main
git add -A
git commit -m "Initial MVP for Leer con la Oreja"
git remote add origin https://github.com/aguslopezleg/leerconlaoreja.git
git push -u origin main
```

Si usas SSH y ves:

```text
Permission denied (publickey)
```

cambia el remoto a HTTPS:

```bash
git remote set-url origin https://github.com/aguslopezleg/leerconlaoreja.git
git push -u origin main
```

## Limitaciones

- Si el PDF es escaneado y no tiene texto seleccionable, necesitas OCR antes.
- La limpieza de headers/footers es heurística.
- La visualización de audio es simple.
- ElevenLabs está preparado como interfaz, pero no implementado.
- La sincronización más precisa requiere WhisperX.
- El render rechaza audios fuera del rango configurado de duración.
- Las miniaturas IA pueden requerir varios intentos para lograr el tono exacto.

## Próximos Pasos

- Agregar OCR opcional con Tesseract.
- Implementar `ElevenLabsTTSProvider`.
- Mejorar detección de capítulos.
- Generar waveform real desde amplitud del audio.
- Agregar plantillas visuales por tipo de libro.
- Añadir tests unitarios para limpieza, chunking, SRT y metadata.
