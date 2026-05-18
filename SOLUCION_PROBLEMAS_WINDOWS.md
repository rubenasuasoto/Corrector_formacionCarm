# Solucion de problemas en Windows

Guia rapida para incidencias comunes al instalar o ejecutar Corrector CARM.

## Comprobacion base

Ejecuta:

```powershell
.\verificar_app_windows.cmd
```

Si todavia no has configurado credenciales CARM ni curso activo:

```powershell
.\verificar_app_windows.cmd --instalacion
```

## Playwright o Chromium bloqueado

Sintomas habituales:

- `EPERM`
- `PermissionError`
- `WinError 5`
- `operation not permitted`
- fallo creando `ms-playwright\__dirlock`

Primero cierra ventanas de Chromium/Playwright abiertas y cualquier proceso antiguo de la app.

Despues ejecuta:

```powershell
.\reparar_dependencias_windows.cmd -LimpiarPlaywrightLock -ReinstalarChromium
```

Si el antivirus o Windows Defender bloquean el navegador, permite la ejecucion de Chromium de Playwright desde:

```text
C:\Users\<usuario>\AppData\Local\ms-playwright
```

## Falta .venv

Sintoma:

```text
No existe .venv
```

Solucion:

```powershell
.\instalar_windows.cmd
```

## Faltan dependencias Python

Sintomas:

- `ModuleNotFoundError`
- `RuntimeError: Playwright no esta disponible`
- el chequeo local marca dependencias base como pendientes;
- la app arranca desde un Python global en vez de `.venv`.

Solucion:

```powershell
.\reparar_dependencias_windows.cmd
```

Despues abre la app con:

```powershell
.\ABRIR_CORRECTOR_CARM.cmd
```

o:

```powershell
.\iniciar_app_windows.cmd -AbrirNavegador
```

Evita abrirla con `python interfaz_app.py` desde una consola que no sea la `.venv`.

Para lectura avanzada de PDF, PPTX, XLSX u OCR:

```powershell
.\reparar_dependencias_windows.cmd -ConExtraccion
```

Si el asistente de instalacion falla o se cierra en `Instalando dependencias`, revisa el log que deja el instalador:

```text
%TEMP%\Corrector_CARM_instalador.log
```

Ese archivo guarda la salida de Python, pip, Playwright, OCR y Codex CLI para diagnosticar el fallo sin mostrar terminales al usuario final.

Desde la revision del 2026-05-18, si la instalacion termina correctamente la ventana de progreso se cierra sola. Si se queda abierta, tratalo como incidencia y revisa el log anterior antes de volver a ejecutar el setup.

## No aparece el icono de bandeja

1. Ejecuta:

```powershell
.\verificar_app_windows.cmd
```

2. Si `pystray` o `Pillow` faltan:

```powershell
.\reparar_dependencias_windows.cmd
```

3. Si la app esta activa pero no ves el icono, inicia abriendo navegador:

```powershell
.\iniciar_app_windows.cmd -AbrirNavegador
```

## Se abren y cierran ventanas de comando

Suele ocurrir si hay varias instancias intentando arrancar o si el acceso de inicio de Windows quedo antiguo.

1. Reinstala el arranque desde la interfaz o ejecuta:

```powershell
.\.venv\Scripts\python.exe interfaz_app.py --install-startup
```

2. Inicia manualmente solo una vez:

```powershell
.\iniciar_app_windows.cmd -AbrirNavegador
```

El script de inicio comprueba si el panel ya responde en `127.0.0.1:8765` y no lanza otra instancia.

## No aparece en Aplicaciones instaladas

Las versiones antiguas se instalaban como carpeta local con accesos directos y podian no aparecer en la lista de Windows.

Solucion:

1. Ejecuta el instalador actual de nuevo:

```powershell
.\INSTALAR_CORRECTOR_CARM.cmd
```

2. El instalador registrara `Corrector CARM` en **Configuracion > Aplicaciones instaladas**.

3. Si necesitas quitar una instalacion antigua sin reinstalar:

```powershell
.\desinstalar_windows.cmd
```

Si todavia se inicia al arrancar Windows, revisa y borra accesos antiguos en:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

## El panel local no conecta

Puede pasar si cerraste la app, cambio el puerto o quedo una instancia antigua.

1. Cierra procesos antiguos si los hubiera.
2. Inicia de nuevo:

```powershell
.\iniciar_app_windows.cmd -AbrirNavegador
```

3. Comprueba:

```powershell
.\verificar_app_windows.cmd
```

## La subida asistida no detecta que CARM ha guardado

La app intenta detectar el guardado por mensajes de Moodle y por el cambio de estado de la entrega, por ejemplo de `Sin calificar` a `Calificado`.

Para depurar un caso:

1. Activa `Guardar trace de diagnostico de subida` en la seccion de subida.
2. Ejecuta la subida asistida solo con las correcciones que quieras revisar.
3. El trace se guardara en:

```text
respuestas_extraidas\traces\
```

El trace puede contener nombres, notas, feedback y contenido de CARM. No lo compartas sin revisarlo o purgarlo despues.

## La API de OpenAI falla por cuota

El flujo sin API sigue disponible:

1. Configura `CORRECTION_MODE=prompt`.
2. Genera prompts desde la app.
3. Resuelve con Codex/ChatGPT siguiendo `INSTRUCCIONES_CODEX_PERSONALIZADAS.md`.
4. Importa los `*_correccion.json`.

## Antes de tocar datos reales

Ejecuta:

```powershell
.\verificar_app_windows.cmd
```

Y revisa:

```powershell
RELEASE_CHECKLIST.md
```
