# Security

[Español](SECURITY.md)

Corrector CARM is a local application that may handle credentials, browser sessions, student submissions, grades and feedback. Treat all operational data as sensitive.

## Principles

- Do not publish `.env`, `.corrector_app.json`, caches, sessions, logs, diagnostics, submissions or generated corrections.
- Do not attach cookies, tokens, API keys, private HTML or student data to issues, commits or screenshots.
- The local panel must listen only on `127.0.0.1`, `localhost` or `::1`.
- POST actions from the panel must be protected by a per-process token.
- Upload to CARM remains assisted: the application fills fields, while the teacher performs the final save.
- Exportable diagnostics must be redacted and contain only status, counters and non-sensitive paths.
- `--guardar-evidencias` stores redacted HTML. PNG screenshots are generated only with `--guardar-capturas-diagnostico` and must be treated as sensitive.

## Reporting

Describe security issues using fictional data. Include the affected version, operating system, minimal reproduction steps, expected impact and any temporary mitigation.

Never share credentials, cookies, sessions, private HTML or real submissions. Use GitHub's private vulnerability reporting when available.

## Validation

```powershell
.\verificar_app_windows.cmd --instalacion
python verificar_app.py --sin-endpoints
```

Before publishing a ZIP or EXE, also review `docs/PUBLICACION.md` and `docs/VALIDACION_RELEASE_0.3.0-local.md`. A public package must come from a clean tree and exclude `.env`, `.corrector_app.json`, `.venv`, caches, logs, submissions, Codex projects and generated corrections.

## History and secret rotation

The public history was sanitised to remove local credential files and generated outputs committed during early development. Rewriting Git does not invalidate a secret: any key that ever appeared in a commit must be revoked at its provider and replaced only in the local environment.
