# Prueba Segura del Instalador

Esta guía sirve para validar un paquete o instalador de Corrector CARM sin tocar
datos reales de alumnos ni la instalación habitual del equipo.

## Objetivo

- Confirmar que el ZIP y el EXE se generan desde un árbol limpio.
- Comprobar que el paquete no contiene `.env`, cachés, logs, entregas ni
  correcciones reales.
- Probar que el instalador guiado abre, instala, verifica y desinstala en rutas
  de laboratorio.
- Evitar usar credenciales reales durante capturas, demos o pruebas públicas.

## Preparación

Usa rutas temporales separadas de tu trabajo real:

```text
C:\temp\corrector_carm_release_test\app
C:\temp\corrector_carm_release_test\data
```

Antes de generar artefactos:

```powershell
git status
.\verificar_app_windows.cmd --instalacion
.\preparar_release_windows.cmd
```

El estado de Git debe estar limpio o contener solo cambios que se quieran
probar explícitamente.

## Generar Artefactos

Para crear el ZIP guiado:

```powershell
.\crear_paquete_windows.cmd -Salida C:\temp\corrector_carm_release_test\salida
```

Para crear el instalador EXE:

```powershell
.\crear_instalador_setup_windows.cmd -Salida C:\temp\corrector_carm_release_test\salida
```

El EXE no está firmado digitalmente, así que Windows SmartScreen puede avisar de
editor desconocido. Ese aviso es esperado mientras no haya firma.

## Comprobación del Contenido

El ZIP o carpeta extraída no debe incluir:

- `.env`
- `.corrector_app.json`
- `.venv/`
- `cache_carm/`
- `logs_correcciones/`
- `respuestas_extraidas/`
- `correcciones_validadas/`
- `codex_project/`
- entregas, prompts reales, CSV de alumnos o bases SQLite reales

Comprobación rápida:

```powershell
$pkg = "C:\temp\corrector_carm_release_test\salida\<carpeta_del_paquete>"
Get-ChildItem -LiteralPath $pkg -Recurse -Force |
  Where-Object {
    $_.Name -eq ".env" -or
    $_.Name -eq ".corrector_app.json" -or
    $_.FullName -match "\\.venv\\|\\cache_carm\\|\\logs_correcciones\\|\\respuestas_extraidas\\|\\correcciones_validadas\\|\\codex_project\\"
  }
```

Si el comando devuelve archivos, el paquete no debe compartirse.

## Prueba de Instalación

1. Ejecuta el EXE o `INSTALAR_CORRECTOR_CARM.cmd` desde la carpeta extraída.
2. Elige como carpeta de instalación:
   `C:\temp\corrector_carm_release_test\app`
3. Elige como carpeta de datos:
   `C:\temp\corrector_carm_release_test\data`
4. No introduzcas credenciales CARM reales si la prueba es pública o de demo.
5. Comprueba que el asistente muestra progreso gráfico y no depende de una
   consola visible.
6. Abre el panel y confirma que se bloquea correctamente si faltan credenciales.
7. Ejecuta la comprobación local desde la interfaz o con:

```powershell
C:\temp\corrector_carm_release_test\app\verificar_app_windows.cmd --instalacion
```

## Prueba de Desinstalación

Desde Windows:

1. Abre Aplicaciones instaladas.
2. Busca `Corrector CARM`.
3. Desinstala conservando datos.
4. Comprueba que la carpeta de datos sigue existiendo.

Desde consola:

```powershell
C:\temp\corrector_carm_release_test\app\desinstalar_windows.cmd
```

Para una prueba de limpieza total, usa solo carpetas de laboratorio:

```powershell
C:\temp\corrector_carm_release_test\app\desinstalar_windows.ps1 -EliminarDatos
```

## Cierre

Antes de publicar o compartir:

- Guarda el hash SHA256 del EXE.
- Comprueba que el manifiesto del paquete no incluye rutas personales.
- Comprueba que el ZIP y el EXE proceden del commit que se quiere distribuir.
- No subas a GitHub artefactos generados salvo que se publiquen como release
  adjunto y se haya revisado su contenido.
