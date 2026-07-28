# Seguridad

[English](SECURITY.en.md)

Corrector CARM es una aplicación local que puede manejar credenciales, sesiones
de navegador, entregas de alumnos, calificaciones y retroalimentación. Trata
todo dato operativo como sensible.

## Principios

- No publiques `.env`, `.corrector_app.json`, caches, sesiones, logs,
  diagnósticos, entregas ni correcciones generadas.
- No adjuntes cookies, tokens, API keys, HTML privado ni datos de alumnos en
  issues, commits o capturas.
- El panel local debe escuchar solo en `127.0.0.1`, `localhost` o `::1`.
- Las acciones POST del panel deben protegerse con token por proceso.
- La subida a CARM debe seguir siendo asistida: la app rellena campos, pero el
  guardado final corresponde al docente.
- Los diagnósticos exportables deben estar redactados y contener solo estado,
  contadores y rutas no sensibles.
- `--guardar-evidencias` guarda HTML redactado. Las capturas PNG solo deben
  generarse con `--guardar-capturas-diagnostico` y tratarse como datos
  sensibles.

## Reportar Problemas

Describe problemas de seguridad con datos ficticios. Incluye:

- versión o commit afectado;
- sistema operativo;
- pasos mínimos para reproducir;
- impacto esperado;
- mitigación temporal si existe.

No compartas credenciales, cookies, sesiones, HTML privado ni entregas reales.

## Validación Recomendada

```powershell
.\verificar_app_windows.cmd --instalacion
python verificar_app.py --sin-endpoints
```

Antes de compartir un ZIP o EXE, revisa también
`docs/PUBLICACION.md` y `docs/VALIDACION_RELEASE_0.3.0-local.md`. El paquete
publicable debe salir de un árbol limpio y no debe contener `.env`,
`.corrector_app.json`, `.venv`, caches, logs, entregas, proyectos Codex ni
correcciones generadas.

## Historial y rotación de secretos

El historial público se saneó para retirar archivos locales de credenciales y
resultados generados que se habían versionado durante el desarrollo inicial.
Reescribir Git no invalida un secreto: cualquier clave que haya aparecido en un
commit debe revocarse en su proveedor y sustituirse por otra distinta solo en
el entorno local.
