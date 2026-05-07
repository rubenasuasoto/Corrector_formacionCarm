# Guía rápida

Antes de tocar nada, revisa `ESTADO_PROYECTO.md`: ahí queda la memoria del trabajo realizado, decisiones tomadas y próximos pasos.

## 1. Instalar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Para leer formatos ampliados como PDF, PPTX, XLSX o imágenes con OCR:

```powershell
pip install -r requirements-extraccion.txt
```

Para OCR de imágenes (`.jpg`, `.png`) también hace falta tener instalado Tesseract OCR en Windows y que esté disponible en el `PATH`. Esta parte no es prioritaria para la primera versión.

## 2. Configurar

Copia `.env.example` a `.env` y rellena las credenciales.

Importante: `.env` contiene usuario, contraseña y API key. No lo subas al repositorio y rota cualquier clave que se haya compartido por error.

Los prompts de corrección están en `prompts_correccion.json`. Puedes editar `default` para el criterio general o crear entradas por actividad, por ejemplo `ud02cp03`, para otros módulos o casos prácticos.

## 3. Probar sin CARM y sin IA

```powershell
python prueba_correcciones.py
```

Esto crea envíos ficticios en `tmp_prueba\pendientes`, genera correcciones de respaldo y deja las salidas en `tmp_prueba\temporal`.

## 4. Preparar prompts para Codex sin API

Para que el agente lea las entregas, las agrupe por actividad y genere archivos listos para pegar en Codex/ChatGPT, sin llamar a la API de OpenAI:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --preparar-prompts-codex
```

Salidas:

- `C:\temp\vscodec\temporal\prompts_codex\prompt_ud01cp01.md`
- `C:\temp\vscodec\temporal\prompts_codex\prompt_ud02cp03.md`
- `C:\temp\vscodec\temporal\prompts_codex\manifiesto_entregas.json`

El archivo `.md` se copia entero en Codex/ChatGPT. Codex debe devolver un JSON con las correcciones.

## 5. Corregir archivos reales ya descargados

Coloca las entregas en `C:\temp\vscodec\pendientes` con el nombre del alumno como nombre de archivo.

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt
```

Para usar otro archivo de prompts:

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt --prompts C:\ruta\prompts_modulo_02.json
```

Salidas:

- `C:\temp\vscodec\temporal\<alumno>\ud01cp01.ext`: copia de la entrega.
- `C:\temp\vscodec\temporal\<alumno>\ud01cp01.txt`: corrección generada.
- `C:\temp\vscodec\temporal\resumen.txt`: resumen global.
- `C:\temp\vscodec\temporal\resumen_ud01cp01.txt`: resumen específico de esa unidad y caso práctico.
- `C:\temp\vscodec\temporal\revision_pendiente.csv`: hoja para revisar notas y feedback antes de subir.

El código `ud01cp01` cambia según la actividad. Si se extrae desde CARM, el agente intenta detectarlo desde el nombre de la unidad y del caso práctico. Si corriges archivos descargados a mano, puedes indicarlo con `--actividad-codigo ud02cp03` o meter los archivos en una subcarpeta con ese nombre.

Si la respuesta del alumno ya es `.txt`, se copia como `ud01cp01_respuesta.txt` para no pisar la corrección `ud01cp01.txt`.

## 6. Diagnosticar navegación real en CARM

Antes de descargar entregas reales, ejecuta un diagnóstico:

```powershell
python corrector_agente.py --diagnosticar-carm
```

Esto abre Chromium, inicia sesión en CARM, entra al curso configurado en `.env` y guarda un diagnóstico limpio en:

- `logs_correcciones\diagnostico_carm\diagnostico.json`

Por defecto no guarda HTML, capturas ni URLs. Si hace falta depurar selectores visualmente:

```powershell
python corrector_agente.py --diagnosticar-carm --guardar-evidencias
```

Las evidencias se redactan de forma básica, pero pueden contener datos de alumnos. Úsalas solo para depurar y no las compartas.

Si quieres que el navegador se quede abierto al final para mirar la pantalla:

```powershell
python corrector_agente.py --diagnosticar-carm --mantener-navegador
```

Con este diagnóstico ajustamos selectores si Moodle no muestra actividades o entregas como espera el agente.

Para listar entregas que requieren calificación sin descargar archivos:

```powershell
python corrector_agente.py --solo-listar-carm
```

Esto genera `respuestas_extraidas\envios_carm_registros.json` con alumno, actividad, estado y si hay archivo, pero sin descargar entregas ni corregir.

## 7. Extraer desde CARM

```powershell
python corrector_agente.py --extraer-carm
```

En este modo descarga los archivos entregados desde CARM a `C:\temp\vscodec\pendientes\<actividad>\` con el nombre del alumno, y corrige cada actividad en lote para hacer una petición de IA por unidad/caso práctico.

Para extraer desde CARM y generar solo prompts para Codex, sin API:

```powershell
python corrector_agente.py --extraer-carm --preparar-prompts-codex
```

La extracción real deja auditoría en:

- `respuestas_extraidas\envios_descargados.json`: archivos descargados y dueño de cada archivo.
- `respuestas_extraidas\envios_carm_registros.json`: registro mínimo por fila de alumno, incluyendo actividad, estado, si tenía archivo, si no entregó o si hubo error de descarga.

Cuando una entrega ya ha sido copiada a `temporal` y tiene su corrección generada, se elimina automáticamente de `pendientes`. Para pruebas en las que quieras conservar los originales, usa `--conservar-pendientes`.

Los `.txt`, `.docx`, `.odt`, `.rtf`, `.csv`, `.html`, `.json`, `.xml` y similares se intentan leer automáticamente. Con las dependencias opcionales también se intentan leer `.pdf`, `.pptx`, `.xlsx`, `.zip`, `.jpg` y `.png`. Los multimedia, `.doc` antiguo, comprimidos no soportados o formatos no extraíbles quedan marcados en `revision_pendiente.csv` como `revision_manual_necesaria` y no se eliminan de `pendientes`.

La subida automática queda para una fase posterior. En esta primera prueba, todo queda en estado `borrador_pendiente_de_revision`.
