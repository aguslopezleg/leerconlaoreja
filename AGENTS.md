# Instrucciones Para Agentes

Este proyecto genera videos tipo NotebookLM/audio overview desde PDFs, con una sola voz y una pipeline local cacheada.

## Principios

- Mantener arquitectura modular en `src/`.
- No hardcodear claves ni secretos.
- Priorizar bajo costo en cada cambio.
- Mantener prompts en español en `src/prompts.py`.
- No generar imágenes IA por defecto.
- Reutilizar archivos intermedios salvo que exista `--force`.
- Mantener memoria acumulada entre chunks para no perder ideas que cruzan fragmentos.
- Escribir código simple, explícito y mantenible.

## Costos y cache

- Usa modelos económicos para resúmenes por chunk.
- Conserva el contexto acumulado entre chunks sin agregar llamadas caras salvo que el usuario lo pida.
- Usa modelos mejores solo para el guion final cuando haga falta.
- No regeneres audio si no cambió el guion, modelo o voz.
- No regeneres video si existe y no se pasó `--force`.

## Arquitectura

- `extract_text.py`: extracción y limpieza de PDF.
- `chunk_text.py`: división por tamaño configurable.
- `summarize.py`: resúmenes por chunk y resumen maestro.
- `write_script.py`: guion final y producción visual.
- `generate_tts.py`: proveedores TTS.
- `generate_subtitles.py`: SRT aproximado o Whisper.
- `render_video.py`: composición MP4.
- `main.py`: CLI.
- `models.py`: estructuras Pydantic.
- `prompts.py`: prompts centralizados.
- `utils.py`: utilidades compartidas.

## Reglas de edición

- Evitar abstracciones innecesarias.
- Mantener las salidas en `output/`.
- No cambiar defaults para activar imágenes IA.
- Si se agrega un proveedor externo, debe ser configurable desde `config.yaml`.
- Si un paso llama APIs pagadas, debe respetar cache y `--force`.
- Para buena sincronización de subtítulos, preferir alinear contra el audio ya generado; `approximate` es solo fallback barato.
- No renderizar videos de menos de `min_video_duration_minutes`; regenerar guion/TTS si el audio queda corto.
- Si el guion global sale corto, conservar el outline y expandir sección por sección antes de fallar.
- No descargar música de YouTube. Usar archivos locales con licencia/permiso en `input/music.mp3`.
- El modo preview debe escribir `output/video/preview_<segundos>s.mp4` sin pisar `final_video.mp4`.
- El comando `youtube` debe ser explícito, nunca parte automática de `all`.
- No hardcodear credenciales OAuth de YouTube; usar `.env` y archivos locales ignorables.
- Si se agrega una dependencia, actualizar `requirements.txt` y README.

## Manejo de errores

- Si falta PDF, mostrar error claro.
- Si falta `OPENAI_API_KEY`, mostrar error claro antes de llamar OpenAI.
- Si el PDF no tiene texto extraíble, sugerir OCR.
- Si falta ffmpeg, reportar que es necesario para audio/video.
