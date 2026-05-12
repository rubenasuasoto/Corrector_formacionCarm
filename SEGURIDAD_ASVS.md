# Seguridad ASVS aplicada al Corrector CARM

Referencia de trabajo: OWASP Application Security Verification Standard 5.0.0.
Para priorizar hallazgos concretos se usara `SEGURIDAD_CVSS.md`.

Este proyecto no necesita aplicar ASVS completo como si fuera una aplicacion web publica. Es una app local de Windows con interfaz en `127.0.0.1`, automatizacion de CARM, credenciales locales y tratamiento de entregas de alumnos. Por eso se aplicara ASVS de forma selectiva, priorizando controles que reduzcan riesgo real en esta app.

## Alcance

Activos sensibles:

- Credenciales CARM y sesion recordada.
- Entregas, nombres de alumnos, notas y retroalimentacion.
- JSON de correcciones y CSV de revision.
- Cache didactica del curso.
- Automatizacion de publicacion en CARM.

Superficie principal:

- Servidor local de `interfaz_app.py`.
- Endpoints HTTP locales.
- Procesos Playwright contra CARM.
- Descarga y lectura de archivos entregados por alumnos.
- Llamadas a Codex CLI/OpenAI.

## Reglas de diseno

- La app no tendra login propio: solo configuracion de credenciales CARM.
- Las credenciales CARM se verifican contra CARM antes de guardarse.
- `Borrar credenciales CARM` debe vaciar `CARM_USUARIO`/`CARM_CONTRASENA` y borrar la sesion recordada con confirmacion explicita.
- La interfaz debe seguir escuchando solo en `127.0.0.1`.
- Los endpoints locales deben aceptar acciones cerradas, no comandos arbitrarios.
- Los selectores de actividad/unidad/rutas deben ser menus o listas permitidas.
- La publicacion en CARM nunca debe ocurrir automaticamente.
- Los errores y archivos no corregibles deben generar notificacion.
- Los logs no deben guardar credenciales, tokens, cookies, emails o HTML sensible sin redaccion.
- Los archivos no reconocidos, multimedia, comprimidos peligrosos o ilegibles van a revision manual.

## Checklist Vivo

### Prioridad Alta

- [x] `.env` ignorado por git.
- [x] Credenciales CARM verificadas antes de guardarse.
- [x] Cierre de sesion borra credenciales y storage state.
- [x] Acciones de interfaz en lista cerrada.
- [x] Sin campos libres para comandos/rutas peligrosas.
- [x] Filtros CARM forzados a `Requiere calificacion` y nombre/apellido en todos.
- [x] Cachear curso no recorre tablas de alumnos.
- [x] Notificaciones en errores y revision manual.
- [x] Proteger endpoints locales con token de sesion local para evitar peticiones desde paginas externas del navegador.
- [x] Separar arranque de Windows y autoprompteo al inicio como opciones explicitas.
- [ ] Separar cache didactica de datos personales y purgar datos de alumnos tras finalizar curso.
- [ ] Redactar nombres/emails en diagnosticos exportables por defecto.

### Prioridad Media

- [x] Validar tamano maximo y extension antes de leer archivos de alumnos.
- [x] Endurecer ZIP: limite de numero de ficheros, tamano total y proteccion contra zip-slip.
- [x] Registrar auditoria local de acciones sensibles: descargar, corregir, previsualizar, publicar.
- [x] Bloquear publicacion si hay `revision_manual_necesaria` o errores en CSV/JSON.
- [ ] Confirmacion fuerte antes de `--publicar-carm`.
- [ ] Timeouts y reintentos controlados para Playwright.
- [x] Sanitizar feedback antes de insertarlo en editores Moodle.

### Prioridad Baja

- [ ] Revisar permisos del directorio del proyecto y archivos generados.
- [x] Rotacion/limpieza de logs antiguos.
- [ ] Modo exportacion de diagnostico seguro.
- [ ] Pruebas automatizadas para endpoints locales.

### Aceptado / No Prioritario

- [ ] Guardar credenciales CARM con Windows DPAPI. Decision actual: no se prioriza porque la app es local y el modelo de amenaza asume que, si el usuario Windows esta comprometido, tambien lo esta el uso normal de CARM en navegador.

## Mapeo ASVS Practico

- Arquitectura y modelo de amenazas: mantener este documento y actualizarlo cuando cambie el flujo.
- Autenticacion y gestion de sesiones: credenciales CARM, sesion recordada, logout y futura proteccion DPAPI.
- Control de acceso: endpoints locales solo con acciones permitidas y token local.
- Validacion de entrada: menus cerrados, allowlists, validacion de rutas y actividades.
- Proteccion de datos: `.env`, cache, logs, CSV, JSON y datos de alumnos.
- Comunicaciones: CARM siempre por HTTPS y sin registrar URLs sensibles completas si contienen tokens.
- Manejo de errores y logging: notificaciones, redaccion y ausencia de secretos.
- Archivos: extensiones, tamano, ZIP y revision manual.
- Logica de negocio: no publicar sin revision humana.
- Configuracion: arranque Windows, bandeja, `127.0.0.1`, dependencias y modo headless.

## Regla Para Cambios Futuros

Antes de cambiar codigo relacionado con credenciales, endpoints HTTP, descargas, lectura de archivos, logs, cache o publicacion en CARM, revisar este documento y actualizar el checklist si aparece un riesgo nuevo.
