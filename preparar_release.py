from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_DIR = ROOT / "respuestas_extraidas"


def safe_print(value: str = "") -> None:
    try:
        print(value)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(value.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def git_output(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    ).stdout.strip()


def release_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0-local"
    except Exception:
        return "0.0.0-local"


def run_verification(skip_offline: bool) -> tuple[int, str]:
    cmd = [sys.executable, "verificar_app.py"]
    if skip_offline:
        cmd.append("--sin-prueba-offline")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    return proc.returncode, proc.stdout


def create_manifest(version: str, verification_code: int, verification_output: str) -> Path:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    commit = git_output(["rev-parse", "--short", "HEAD"]) or "sin-git"
    status = git_output(["status", "--short"])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    manifest = {
        "version": version,
        "commit": commit,
        "dirty": bool(status),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "verification_ok": verification_code == 0,
        "verification_exit_code": verification_code,
        "verification_tail": verification_output.splitlines()[-80:],
        "status_short": status.splitlines(),
    }
    path = MANIFEST_DIR / f"release_manifest_{version}_{timestamp}.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def create_git_tag(version: str) -> bool:
    tag = f"v{version}"
    existing = git_output(["tag", "--list", tag])
    if existing:
        safe_print(f"ERROR: La etiqueta {tag} ya existe.")
        return False
    proc = subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"Corrector CARM {version}"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if proc.stdout.strip():
        safe_print(proc.stdout.strip())
    if proc.returncode != 0:
        safe_print(f"ERROR: No se pudo crear la etiqueta {tag}.")
        return False
    safe_print(f"Etiqueta creada: {tag}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara un release local del Corrector CARM.")
    parser.add_argument("--sin-prueba-offline", action="store_true", help="Omite prueba offline durante la verificacion.")
    parser.add_argument("--crear-tag", action="store_true", help="Crea etiqueta Git v<VERSION> si la verificacion pasa y no hay cambios locales.")
    args = parser.parse_args()

    version = release_version()
    safe_print(f"Preparando release local {version}...")
    code, output = run_verification(skip_offline=args.sin_prueba_offline)
    safe_print(output.strip())
    manifest_path = create_manifest(version, code, output)
    safe_print(f"\nManifiesto generado: {manifest_path}")

    status = git_output(["status", "--short"])
    if args.crear_tag:
        if code != 0:
            safe_print("ERROR: No se crea etiqueta porque la verificacion no ha pasado.")
            return 1
        if status:
            safe_print("ERROR: No se crea etiqueta porque hay cambios locales sin commit.")
            return 1
        return 0 if create_git_tag(version) else 1
    if code != 0:
        return 1
    safe_print("Release local preparado. Para etiquetar, ejecuta de nuevo con --crear-tag tras hacer commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
