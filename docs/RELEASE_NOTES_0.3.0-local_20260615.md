# Release Notes 0.3.0-local Validado 20260615

Release local validado para Corrector CARM.

## Artefactos

- `Corrector_CARM_0.3.0-local_guiado_20260615_122447.zip`
- `Corrector_CARM_0.3.0-local_Setup_20260615_122449.exe`

SHA256 del EXE:

```text
638C35CA4AE18B4E4811B7576C45E44C7DFB884CA68EFDCA0E9C46D5F751BFE5
```

## Cambios Principales

- Panel local con flujo `Preparar`, `Revisar` y `Subir`.
- Corrección por OpenAI API o por prompts individuales para Codex.
- Proyecto Codex por curso con contexto didáctico sin entregas ni datos
  personales.
- Subida asistida a CARM con guardado humano.
- Revisión manual bloqueante para casos dudosos o ilegibles.
- Regularización asistida de suspensos con revisión previa.
- Instalador guiado Windows con comprobación de dependencias.
- Arranque en bandeja sin depender de una consola visible.

## Seguridad y Calidad

- El paquete no incluye credenciales, `.env`, cachés, logs, entregas,
  correcciones, bases SQLite ni proyectos Codex por curso.
- La interfaz local escucha en `127.0.0.1`.
- Los endpoints locales requieren token.
- La publicación directa queda bloqueada; el flujo normal es subida asistida.
- El desinstalador solo borra accesos que apuntan a la instalación que se está
  desinstalando, para no afectar a otras copias.
- El EXE no está firmado digitalmente; Windows SmartScreen puede avisar de
  editor desconocido.

## Pruebas Realizadas

- Verificación offline completa.
- Generación de ZIP limpio.
- Generación de EXE autoextraíble con icono propio.
- Escaneo de contenido sensible en ZIP y EXE.
- Extracción del ZIP en laboratorio.
- Instalación técnica en laboratorio.
- Verificación de instalación con credenciales pendientes.
- Desinstalación de laboratorio conservando accesos ajenos.
- Instalación visual desde el EXE y verificación posterior.

Más detalle en [VALIDACION_RELEASE_0.3.0-local.md](VALIDACION_RELEASE_0.3.0-local.md).

## Instalación Recomendada

1. Descarga el EXE y revisa el SHA256.
2. Ejecuta el instalador.
3. Elige carpeta de instalación y carpeta de datos.
4. Abre el panel.
5. Configura credenciales CARM y, si procede, OpenAI API.
6. Detecta curso, prepara prompts y revisa siempre antes de subir.
