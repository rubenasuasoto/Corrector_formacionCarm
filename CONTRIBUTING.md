# Contribuir

Corrector CARM prioriza seguridad, revisión humana y estabilidad en Windows. Las
contribuciones deben mantener ese criterio.

## Reglas Básicas

- No subas `.env`, datos de alumnos, caches, sesiones, logs ni salidas reales.
- Mantén el guardado en CARM bajo control humano.
- Conserva compatibilidad con los lanzadores Windows de la raíz del proyecto.
- Usa rutas genéricas o configurables en documentación pública.
- Documenta cambios relevantes en `ESTADO_PROYECTO.md` si afectan al flujo real.

## Estilo

- Cambios pequeños y verificables.
- Comentarios de código solo cuando aclaren una decisión no obvia.
- Textos de interfaz claros, en español y orientados al docente.
- Evita mezclar refactors grandes con cambios funcionales.

## Pruebas

```powershell
python verificar_app.py --sin-endpoints
.\verificar_app_windows.cmd --instalacion
```

Si el cambio afecta instalador o paquete:

```powershell
.\preparar_release_windows.cmd
.\crear_paquete_windows.cmd
```
