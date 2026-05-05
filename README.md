# 🤖 Agente de Corrección Automática - CARM Formación

Agente inteligente para corregir ejercicios prácticos del curso **"Inteligencia Artificial aplicada al sector turístico"** en la plataforma CARM Formación, usando Playwright para navegación y OpenAI/Codex para evaluación.

## 🎯 Características

- ✅ **Extracción automática**: Lee actividades directamente del sitio Moodle
- 📋 **Corrección con IA**: Usa prompts programados según tipo de actividad
- ✔️ **Validación**: Verifica que las correcciones sean coherentes
- 📊 **Trazabilidad completa**: Guarda logs, respuestas originales, correcciones y timestamps
- 🔐 **Revisión obligatoria**: Todo comienza en estado "borrador" para aprobación manual
- 📝 **Prompts personalizables**: Diferentes evaluaciones para ejercicios, autoevaluaciones, foros

## 📋 Requisitos

- Python 3.9+
- API Key de OpenAI/Codex
- Credenciales de acceso a CARM Formación
- Conexión a internet

## 🚀 Instalación

### 1. Clonar/descargar el proyecto
```bash
cd c:\temp\vscode
```

### 2. Crear entorno virtual (recomendado)
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar credenciales
Copia `.env.example` a `.env` y rellena con tus datos:
```bash
cp .env.example .env
```

Abre `.env` y configura:
```
CARM_USUARIO=tu_usuario
CARM_CONTRASENA=tu_contrasena
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

### 5. Instalar navegadores Playwright
```bash
playwright install chromium
```

## ▶️ Uso

### Ejecución básica (modo demostración)
```bash
python corrector_agente.py
```

Esto:
1. Usa datos de prueba (no accede al sitio real)
2. Corrige usando OpenAI/Codex
3. Genera trazabilidad en `correcciones_validadas/`
4. Muestra logs en consola y en `logs_correcciones/`

### Ejecución con sitio real
En `corrector_agente.py`, línea ~200, descomenta:
```python
actividades = await extractor.ejecutar()
```

Y comenta la línea siguiente que usa datos de prueba.

## 📁 Estructura de carpetas

```
corrector_agente.py          # Script principal
requirements.txt             # Dependencias
.env.example                 # Ejemplo de configuración
.env                         # TUS credenciales (no commitear)
│
├── logs_correcciones/       # Logs de ejecución
├── respuestas_extraidas/    # Respuestas originales (JSON)
└── correcciones_validadas/  # Correcciones + trazabilidad (JSON)
```

## 🏗️ Arquitectura

### 1. **Extractor (ExtractorCarm)**
- Inicia sesión en CARM Formación
- Navega el curso y extrae actividades
- Obtiene enunciado y respuesta de cada alumno
- Guarda metadatos en JSON

### 2. **Corrector (CorrectorIA)**
- Usa prompts predefinidos según tipo de actividad
- Envía respuesta + enunciado a OpenAI/Codex
- Recibe evaluación estructurada (JSON)
- Tipos de prompt: `ejercicio_practico`, `autoevaluacion`, `discusion`

### 3. **Validador (ValidadorTrazabilidad)**
- Verifica estructura de la corrección
- Comprueba que nota, justificación, etc. estén presentes
- Guarda registro completo para auditoría

### 4. **Orquestador (main)**
- Coordina flujo completo
- Genera resumen de ejecución
- Mantiene trazabilidad de principio a fin

## 📊 Formato de salida

Cada corrección se guarda en `correcciones_validadas/` como JSON:

```json
{
  "timestamp": "2026-05-05T14:30:00.123456",
  "alumno": "alumno_001",
  "actividad": "Ejercicio IA en turismo",
  "respuesta_original": "La IA puede usarse para...",
  "correccion_generada": {
    "nota": 8.5,
    "justificacion": "Respuesta clara y bien estructurada...",
    "fortalezas": ["Aplicación concreta al turismo", "Argumentación sólida"],
    "mejoras": ["Incluir más ejemplos de Murcia"],
    "feedback": "Excelente trabajo. Para mejorar..."
  },
  "prompt_tipo": "ejercicio_practico",
  "estado": "borrador"
}
```

## 🔄 Flujo de publicación

1. **Borrador** (automático): Se genera la corrección
2. **Validación manual**: Tú revises el JSON en `correcciones_validadas/`
3. **Publicado** (manual): Cambias `"estado"` a `"validado"` o `"publicado"` en el JSON
4. **Sincronización**: Script posterior que sube correcciones validadas a Moodle

## 🛠️ Personalización

### Cambiar prompts
En `corrector_agente.py`, edita el diccionario `PROMPTS`:
```python
PROMPTS = {
    "tu_tipo": """
    Eres un experto en...
    Evalúa según estos criterios...
    Responde en JSON con formato: {...}
    """
}
```

### Cambiar modelo LLM
En `CorrectorIA.corregir()`, modifica:
```python
respuesta = self.cliente.chat.completions.create(
  model="gpt-4.1-mini",  # ← Cambia aquí
    ...
)
```

### Cambiar selectores HTML
Si la estructura de Moodle cambia, actualiza en `ExtractorCarm.extraer_actividades()`:
```python
bloques = await page.query_selector_all(".activity")  # Ajusta selectores
```

## ⚠️ Seguridad

- **No comitees `.env`** con credenciales reales
- Usa variables de entorno en producción
- Mantén logs en carpeta segura (contienen respuestas de alumnos)
- La trazabilidad es obligatoria para auditoría

## 📝 Logs

Accede a logs en `logs_correcciones/`:
```bash
# Ver último log
type logs_correcciones\agente_*.log | tail -50
```

## 🔗 Próximos pasos

1. **Sincronizador Moodle**: Script que sube correcciones desde JSON a Moodle (LMS API)
2. **Dashboard web**: Panel para validar correcciones antes de publicar
3. **Métricas**: Estadísticas de notas, tasa de acierto, tiempos
4. **Feedback iterativo**: El agente aprende de correcciones rechazadas

## ❓ FAQ

**¿Puedo usar otro modelo LLM en lugar de OpenAI/Codex?**
Sí. Cambia `OPENAI_MODEL` en `.env` o reemplaza el cliente por otro compatible. Los prompts son agnósticos.

**¿Qué pasa si falla el login en CARM?**
El agente lo logea y se detiene. Verifica credenciales en `.env` y que tengas permisos en el curso.

**¿Puedo automatizar publicación sin revisión?**
No recomendado sin validación legal/académica. El sistema está diseñado para revisión obligatoria.

**¿Los prompts se pueden entrenar/mejorar?**
Sí. Guarda ejemplos de correcciones validadas y ajusta los prompts iterativamente.

## 📞 Soporte

Para errores:
1. Revisa `logs_correcciones/agente_*.log`
2. Verifica credenciales en `.env`
3. Comprueba que Playwright pueda acceder a CARM

---

**Creado para cursos CARM | Desarrollo de Agentes de IA en Educación 🎓**
