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
- el chequeo local marca dependencias base como pendientes;
- la app arranca desde un Python global en vez de `.venv`.

Solucion:

```powershell
.\reparar_dependencias_windows.cmd
```

Para lectura avanzada de PDF, PPTX, XLSX u OCR:

```powershell
.\reparar_dependencias_windows.cmd -ConExtraccion
```

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
