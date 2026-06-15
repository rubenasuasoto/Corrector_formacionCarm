# Validación Release 0.3.0-local

Validación realizada el 15 de junio de 2026 sobre los artefactos generados tras
el commit `d7bab57`. El informe se actualizó posteriormente para registrar la
prueba visual completa del EXE.

## Artefactos

Artefactos generados en una carpeta temporal ignorada por Git:

```text
.tmp_release/Corrector_CARM_0.3.0-local_guiado_20260615_122447.zip
.tmp_release/Corrector_CARM_0.3.0-local_Setup_20260615_122449.exe
```

SHA256 del instalador EXE:

```text
638C35CA4AE18B4E4811B7576C45E44C7DFB884CA68EFDCA0E9C46D5F751BFE5
```

## Pruebas Ejecutadas

- `verificar_app.py --sin-endpoints`: correcto.
- Generación de ZIP guiado: correcta.
- Generación de EXE autoextraíble con icono propio: correcta.
- Escaneo de rutas y patrones sensibles en ZIP/EXE: correcto.
- Extracción del ZIP en carpeta de laboratorio: correcta.
- Compilación estática de los `.py` del paquete extraído: correcta.
- Smoke test previo a instalación: aviso esperado de `.venv` ausente.
- Instalación técnica en carpeta de laboratorio: correcta.
- Verificación de la instalación de laboratorio con `--instalacion --sin-endpoints`: correcta.
- Desinstalación de laboratorio: correcta.
- Instalación visual desde el EXE como usuario final: correcta.
- Verificación de la instalación creada por el EXE con `--instalacion --sin-endpoints`: correcta.
- Retirada de la instalación de prueba y restauración del registro/arranque de trabajo: correcta.

## Seguridad Comprobada

El paquete no incluye:

- `.env`
- `.corrector_app.json`
- `.venv/`
- `cache_carm/`
- `logs_correcciones/`
- `respuestas_extraidas/`
- `correcciones_validadas/`
- `codex_project/`
- `.git/`
- `__pycache__/`

El EXE no contiene:

- rutas personales del equipo de desarrollo;
- prefijos de API key realistas;
- contraseña demo antigua;
- valores de contraseña CARM.

## Hallazgo Corregido

Durante la prueba de desinstalación se detectó que el desinstalador podía borrar
accesos de otra instalación con el mismo nombre. Se corrigió para que solo retire
accesos que apunten a la carpeta que se está desinstalando.

La prueba confirmó que el arranque real de otra instalación se conservó intacto.

## Prueba Visual del EXE

El instalador EXE se ejecutó manualmente desde la carpeta de distribución. La
instalación se completó en la ruta por defecto del usuario y creó la estructura
esperada con `.venv`, configuración local, scripts y assets.

La verificación posterior informó:

- instalación lista;
- credenciales CARM pendientes de configurar, como se espera en una instalación
  nueva;
- curso activo pendiente de seleccionar;
- carpetas de trabajo creadas;
- endpoints locales y flujos offline correctos.

Tras la prueba, se desinstaló la copia creada por el EXE y se restauró el
registro local para que `Corrector CARM` vuelva a apuntar al repositorio de
trabajo.

## Estado Final

- Rama `casa`: sincronizada.
- Rama `main`: sincronizada.
- Artefactos generados: fuera de Git.
- Repositorio: limpio tras la validación.
