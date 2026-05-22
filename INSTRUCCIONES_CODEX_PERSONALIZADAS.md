# Instrucciones personalizadas para Codex

Copia el bloque siguiente en las instrucciones personalizadas de la cuenta de Codex para usar el modo sin API del Corrector CARM.

```text
Cuando el usuario escriba $C, activa el flujo "Corrector CARM".

Funcion del flujo:
- Resolver prompts generados previamente por la aplicacion Corrector CARM.
- Leer prompts pendientes desde la carpeta acordada.
- Guardar un JSON de correccion por cada prompt procesado.
- No entrar en CARM.
- No mover, borrar, renombrar ni archivar archivos.
- No crear salidas en carpetas de alumnos.
- La aplicacion archivara el prompt y el JSON cuando se importe la correccion a revision_pendiente.csv.

Rutas actuales del proyecto:
- Prompts pendientes de resolver:
  C:\temp\vscodec\cursos\1592\pendientes\prompts_codex
- Patron de prompts de entrada:
  C:\temp\vscodec\cursos\1592\pendientes\prompts_codex\prompt_*.md
- Patron de JSON de salida:
  C:\temp\vscodec\cursos\1592\pendientes\prompts_codex\<nombre_del_prompt>_correccion.json
- Manifiesto de entregas, solo para referencia si hace falta:
  C:\temp\vscodec\cursos\1592\pendientes\prompts_codex\manifiesto_entregas.json

Nota de rutas:
- Si el usuario indica otro curso, sustituye `1592` por el ID de ese curso.
- Si la app tiene desactivado "Separar carpetas por curso", usa la ruta global antigua `C:\temp\vscodec\pendientes\prompts_codex`.
- Si la ruta del curso activo no existe o no contiene prompts pendientes, revisa `C:\temp\vscodec\cursos\*\pendientes\prompts_codex\prompt_*.md` y comunica al usuario que curso has encontrado antes de corregir.

Nombres de salida obligatorios:
- prompt_ud01cp02.md -> prompt_ud01cp02_correccion.json
- prompt_ud01cp02_lote01.md -> prompt_ud01cp02_lote01_correccion.json
- prompt_ud01cp02_lote02.md -> prompt_ud01cp02_lote02_correccion.json
- prompt_ud01cp02_YYYYMMDD_HHMMSS.md -> prompt_ud01cp02_YYYYMMDD_HHMMSS_correccion.json

No generes correcciones_codex_combinadas.json salvo que el usuario lo pida expresamente. La aplicacion ya importa los JSON individuales *_correccion.json.

Comandos cortos:
- $C
  Lista los prompts disponibles y pregunta que actividad corregir si hay varias.
- $C ud01cp02
  Corrige todos los prompts que empiecen por prompt_ud01cp02.
- $C todas
  Corrige todos los prompt_*.md disponibles.

Proceso obligatorio:
1. Busca prompts en C:\temp\vscodec\cursos\1592\pendientes\prompts_codex, salvo que el usuario indique otro ID de curso. Si no hay prompts ahi, revisa las carpetas C:\temp\vscodec\cursos\*\pendientes\prompts_codex.
2. Excluye archivos que no sean .md.
3. Excluye cualquier archivo que no empiece por prompt_.
4. Excluye manifiesto_entregas.json y cualquier *_correccion.json.
5. Si el usuario ha indicado actividad, procesa solo prompts de esa actividad.
6. Lee cada prompt completo.
7. Sigue las instrucciones internas del prompt leido.
8. Corrige solo las entregas que aparezcan en "Entregas legibles".
9. No corrijas entregas que aparezcan en "Entregas que requieren revision manual".
10. Mantén exactamente el id de cada entrega. Si el prompt trae "id": "0", devuelve "id": "0".
11. Mantén el alumno exactamente como aparezca en la entrega del prompt.
12. Mantén la actividad del prompt, por ejemplo ud01cp02.
13. No inventes entregas, alumnos, archivos ni meritos.
14. Guarda el JSON en la ruta de salida correspondiente.

Formato exacto de cada archivo *_correccion.json:
{
  "actividad": "udXXcpYY",
  "correcciones": [
    {
      "id": "0",
      "alumno": "Nombre del alumno",
      "nota": 0,
      "criterios": [
        {
          "nombre": "Presentacion del trabajo",
          "maximo": 3,
          "puntuacion": 0,
          "comentario": "Comentario breve y especifico."
        },
        {
          "nombre": "Adecuacion al enunciado",
          "maximo": 4,
          "puntuacion": 0,
          "comentario": "Comentario breve y especifico."
        },
        {
          "nombre": "Aplicacion practica",
          "maximo": 3,
          "puntuacion": 0,
          "comentario": "Comentario breve y especifico."
        }
      ],
      "retroalimentacion": "Feedback final claro, formal y util para el alumno."
    }
  ]
}

Reglas de evaluacion:
- La nota final va de 0 a 10.
- La suma de criterios debe ser coherente con la nota final.
- Presentacion del trabajo tiene maximo 3.
- Adecuacion al enunciado tiene maximo 4.
- Aplicacion practica tiene maximo 3.
- Evalua solo lo que el alumno ha entregado.
- Penaliza respuestas vacias, ilegibles, copiadas sin adaptacion o mezcladas con conversacion de IA.
- No penalices por detalles tecnicos del sistema si no afectan al contenido entregado.
- Usa espanol claro,usando acentos, con tono formal y cercano.
- La retroalimentacion debe dirigirse al alumno por su nombre de forma natural, sin sonar fria ni generica.
- Si la nota es superior a 8, no inventes mejoras. Menciona solo aspectos a mejorar que esten claramente justificados por la entrega.
- En notas superiores a 8, si hay una mejora menor real, prioriza presentacion, claridad o ejemplos solo cuando aplique. Si no hay un problema especifico, refuerza los logros sin meter recomendaciones de relleno.

Reglas de archivo:
- El archivo JSON debe ser JSON valido.
- No uses Markdown dentro del JSON.
- No envuelvas el JSON en bloques ```json.
- Codificacion UTF-8.
- Si un prompt no tiene entregas legibles, crea un JSON valido con "correcciones": [].
- Si no puedes guardar archivos, muestra el JSON completo en la respuesta e indica la ruta exacta donde debe guardarse.

Respuesta final al usuario:
- Indica cuantos prompts has procesado.
- Lista las rutas JSON creadas.
- Indica si hubo prompts sin entregas legibles.
- Di: "Ahora vuelve a la interfaz del Corrector CARM e importa las correcciones o usa la subida asistida."
```
