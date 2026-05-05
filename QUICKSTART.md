## 🚀 GUÍA RÁPIDA DE INICIO

### Paso 1: Setup (2 min)
```bash
cd C:\Users\ruben\Desktop\agente

# Crear entorno virtual
python -m venv venv

# PowerShell: permitir la activación solo en esta sesión
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt

# Instalar navegadores Playwright
playwright install chromium
```

### Paso 2: Configurar credenciales (1 min)
```bash
# Copiar archivo de ejemplo
copy .env.example .env

# Editar .env con tus datos
notepad .env
```

Rellena:
- `CARM_USUARIO=` tu usuario de CARM
- `CARM_CONTRASENA=` tu contraseña
- `OPENAI_API_KEY=` tu API key de OpenAI/Codex
- `OPENAI_MODEL=` modelo a usar, por ejemplo uno disponible en tu cuenta de Codex

### Paso 3a: Prueba sin conectar a CARM (5 min)
```bash
python prueba_correcciones.py
```

Esto:
- Usa casos de prueba predefinidos
- Corrige con IA sin acceder al sitio
- Genera trazabilidad en `correcciones_validadas/`

### Paso 3b: Conexión a CARM real (requiere permisos)
En `corrector_agente.py` línea ~200:

Descomenta:
```python
actividades = await extractor.ejecutar()
```

Y ejecuta:
```bash
python corrector_agente.py
```

### Resultado
Encuentra las correcciones en:
- **Correcciones**: `correcciones_validadas/` (JSON con notas, feedback, trazabilidad)
- **Logs**: `logs_correcciones/` (detalles de ejecución)
- **Respuestas extraídas**: `respuestas_extraidas/` (datos del sitio)

### Próximo paso: Publicar correcciones validadas
```bash
# Después de revisar y validar las correcciones:
python sincronizador_moodle.py
```

---

### 🔧 Troubleshooting rápido

| Problema | Solución |
|----------|----------|
| `ModuleNotFoundError: No module named 'playwright'` | Ejecuta: `pip install -r requirements.txt` |
| `CARM_USUARIO not found` | Copia `.env.example` a `.env` y rellena |
| `Error en login` | Verifica usuario/contraseña en `.env` |
| No hay API key | Añade `OPENAI_API_KEY` en `.env` con tu clave de OpenAI |
| Playwright no encuentra navegador | Ejecuta: `playwright install chromium` |

---

### 📊 Estructura de salida (JSON ejemplo)

```json
{
  "timestamp": "2026-05-05T14:30:00",
  "alumno": "alumno_001",
  "actividad": "Ejercicio IA en turismo",
  "respuesta_original": "La IA puede usarse para...",
  "correccion_generada": {
    "nota": 8.5,
    "justificacion": "Respuesta clara y bien fundamentada...",
    "fortalezas": ["Aplicación concreta", "Argumento sólido"],
    "mejoras": ["Más ejemplos de Murcia"],
    "feedback": "Excelente. Para mejorar..."
  },
  "estado": "borrador"
}
```

---

**¡Listo! Empieza con la prueba y dime si algo no funciona.**
