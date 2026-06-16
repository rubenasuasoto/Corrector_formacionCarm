# Demo Local y Capturas

Esta guía sirve para preparar capturas públicas del Corrector CARM sin exponer
datos reales de CARM, alumnos ni credenciales.

## Qué Mostrar

- Panel principal con el flujo `Preparar`, `Revisar` y `Subir`.
- Configuración por secciones.
- Estado de salidas con datos ficticios.
- Revisión manual y subida asistida sin guardar automáticamente.
- Comprobación de equipo o diagnóstico seguro.

## Preparación Segura

1. Usa un curso de prueba o datos ficticios.
2. No captures nombres reales, emails, notas reales ni comentarios reales.
3. No muestres `.env`, cookies, tokens, API keys ni HTML privado.
4. Evita logs completos si proceden de una sesión real.
5. Revisa la imagen al 100% antes de publicarla.

## Capturas Recomendadas

Guarda capturas públicas en:

```text
docs/img/
```

Nombres sugeridos:

```text
docs/img/panel-principal.png
docs/img/configuracion.png
docs/img/subida-asistida.png
```

Capturas públicas actuales:

- `docs/img/panel-principal.png`
- `docs/img/configuracion.png`

Se generaron con la interfaz real y textos de demostración inyectados en el
navegador antes de capturar. Si se regeneran, revisa que no aparezcan cursos,
rutas, logs o credenciales reales.

Si hay duda sobre una captura, recréala con datos ficticios.
