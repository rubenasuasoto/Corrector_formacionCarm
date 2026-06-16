# Preparación para Publicar

Checklist para publicar Corrector CARM como repositorio abierto o compartido.

## No Versionar

- `.env`
- `.corrector_app.json`
- `.venv/`
- `cache_carm/`
- `logs_correcciones/`
- `respuestas_extraidas/`
- `correcciones_validadas/`
- bases SQLite, logs, entregas, prompts reales y CSV de alumnos
- paquetes generados `Corrector_CARM_*_Setup_*.exe`

## Sí Versionar

- código fuente principal;
- scripts de instalación y verificación;
- documentación;
- `.env.example`;
- assets públicos del icono;
- prompts base sin datos reales.

## Revisión Manual

1. Ejecutar verificación offline.
2. Confirmar que `.env.example` no contiene secretos reales.
3. Comprobar que README, QUICKSTART y checklist de release reflejan el estado
   actual.
4. Revisar que no hay rutas personales ni datos de alumnos en archivos
   versionados.
5. Revisar `docs/VALIDACION_RELEASE_0.3.0-local.md` si se va a publicar el
   instalador validado.
6. Generar paquete o instalador solo desde árbol limpio.

## Comandos

```powershell
git status
python verificar_app.py --sin-endpoints
.\verificar_app_windows.cmd --instalacion
.\tools\windows\preparar_release_windows.cmd
```

Para publicar el release local validado:

```text
docs/RELEASE_NOTES_0.3.0-local_20260615.md
docs/GITHUB_RELEASE_0.3.0-local_20260615.md
```
