# Guía rápida

## 1. Instalar

```powershell
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## 2. Configurar

Copia `.env.example` a `.env` y rellena las credenciales.

Importante: `.env` contiene usuario, contraseña y API key. No lo subas al repositorio y rota cualquier clave que se haya compartido por error.

## 3. Probar sin CARM y sin IA

```powershell
python prueba_correcciones.py
```

Esto crea envíos ficticios en `tmp_prueba/pendientes`, genera correcciones de respaldo y deja las salidas en `tmp_prueba/temporal`.

## 4. Corregir archivos reales ya descargados

Coloca las entregas en `C:\temp\vscodec\pendientes` con el nombre del alumno como nombre de archivo.

```powershell
python corrector_agente.py --contexto-unidad C:\ruta\manual_ud01.txt
```

Salidas:

- `C:\temp\vscodec\temporal\<alumno>\ud01cp01.ext`: copia de la entrega.
- `C:\temp\vscodec\temporal\<alumno>\ud01cp01.txt`: corrección generada.
- `C:\temp\vscodec\temporal\resumen.txt`: resumen global.
- `C:\temp\vscodec\temporal\resumen_ud01cp01.txt`: resumen específico de esa unidad y caso práctico.
- `C:\temp\vscodec\temporal\revision_pendiente.csv`: hoja para revisar notas y feedback antes de subir.

El código `ud01cp01` cambia según la actividad. Si se extrae desde CARM, el agente intenta detectarlo desde el nombre de la unidad y del caso práctico. Si corriges archivos descargados a mano, puedes indicarlo con `--actividad-codigo ud02cp03` o meter los archivos en una subcarpeta con ese nombre.

## 5. Extraer desde CARM

```powershell
python corrector_agente.py --extraer-carm
```

En este modo descarga los archivos entregados desde CARM a `C:\temp\vscodec\pendientes\<actividad>\` con el nombre del alumno, y corrige cada actividad en lote para hacer una petición de IA por unidad/caso práctico.

Cuando una entrega ya ha sido copiada a `temporal` y tiene su corrección generada, se elimina automáticamente de `pendientes`. Para pruebas en las que quieras conservar los originales, usa `--conservar-pendientes`.

La subida automática queda para una fase posterior. En esta primera prueba, todo queda en estado `borrador_pendiente_de_revision`.
