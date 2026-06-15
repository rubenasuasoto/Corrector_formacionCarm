# Borrador GitHub Release 0.3.0-local 20260615

## Título

```text
Corrector CARM 0.3.0-local validado 20260615
```

## Tag

```text
v0.3.0-local-20260615-final
```

## Adjuntos

Subir estos archivos desde:

```text
<carpeta de distribución>\Corrector CARM\0.3.0-local-20260615
```

- `Corrector_CARM_0.3.0-local_Setup_20260615_122449.exe`
- `Corrector_CARM_0.3.0-local_guiado_20260615_122447.zip`
- `SHA256SUMS.txt`
- `RELEASE_NOTES.md`
- `VALIDACION_RELEASE.md`

## Texto

````markdown
Release local validado para Corrector CARM.

### Instalación recomendada

Descarga `Corrector_CARM_0.3.0-local_Setup_20260615_122449.exe`, revisa el
SHA256 y ejecuta el instalador.

SHA256 del EXE:

```text
638C35CA4AE18B4E4811B7576C45E44C7DFB884CA68EFDCA0E9C46D5F751BFE5
```

### Cambios principales

- Panel local con flujo `Preparar`, `Revisar` y `Subir`.
- Corrección por OpenAI API o por prompts individuales para Codex.
- Proyecto Codex por curso con contexto didáctico sin entregas ni datos personales.
- Subida asistida a CARM con guardado humano.
- Revisión manual bloqueante para casos dudosos o ilegibles.
- Regularización asistida de suspensos con revisión previa.
- Instalador guiado Windows con comprobación de dependencias.
- Arranque en bandeja sin depender de una consola visible.

### Seguridad y calidad

- El paquete no incluye credenciales, `.env`, cachés, logs, entregas,
  correcciones, bases SQLite ni proyectos Codex por curso.
- La interfaz local escucha en `127.0.0.1`.
- Los endpoints locales requieren token.
- La publicación directa queda bloqueada; el flujo normal es subida asistida.
- El desinstalador solo borra accesos que apuntan a la instalación que se está
  desinstalando, para no afectar a otras copias.
- El EXE no está firmado digitalmente; Windows SmartScreen puede avisar de
  editor desconocido.

### Pruebas realizadas

- Verificación offline completa.
- Generación de ZIP limpio.
- Generación de EXE autoextraíble con icono propio.
- Escaneo de contenido sensible en ZIP y EXE.
- Extracción del ZIP en laboratorio.
- Instalación técnica en laboratorio.
- Verificación de instalación con credenciales pendientes.
- Desinstalación de laboratorio conservando accesos ajenos.
- Instalación visual desde el EXE y verificación posterior.

Consulta `VALIDACION_RELEASE.md` para el detalle de validación.
````
