#!/usr/bin/env python3
"""Escáner de secretos escritos en el código (proyecto NIST · Protect, PR.DS / OWASP A02).

Recorre los ficheros que sigue git (`git ls-files`) y falla si encuentra:

1. **Claves con formato de proveedor** en cualquier fichero de texto (código, docs,
   tests): OpenAI/OpenRouter (`sk-…`), AWS (`AKIA…`), GitHub (`ghp_…`,
   `github_pat_…`), Resend (`re_…`), Slack (`xox…`), Google (`AIza…`), claves
   privadas PEM y JWT completos (cabecera.payload.firma).
2. **Asignaciones de un literal a un nombre sensible** (`api_key`, `secret`,
   `password`, `token`, `client_secret`…) en ficheros de código fuera de `tests/`:
   `LLM_API_KEY = "abc123…"`. No cuentan los marcadores de ejemplo
   (`<tenant>`, `replace-with…`, `changeme`, `${VAR}`…) ni leer del entorno.
3. **Ficheros `.env` versionados** (cualquier `.env*` salvo `.env.example`).
4. **Valores reales en `.env.example`**: las variables con nombre de secreto deben ir vacías
   o con un marcador.

Una línea con `secrets-scan: allow` se ignora (para valores de prueba conocidos y
documentados, p. ej. la contraseña antigua que la sonda OWASP comprueba que **ya no** entra).
Nunca imprime un secreto entero: muestra los 4 primeros caracteres y `…`.

    python scripts/secrets_scan.py            # salida legible; código 1 si hay hallazgos
    python scripts/secrets_scan.py --json     # para guardar como evidencia
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW_MARK = "secrets-scan: allow"
MAX_FILE_BYTES = 1_000_000

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".woff", ".woff2",
    ".ttf", ".mp4", ".mov", ".sqlite", ".db", ".pkl", ".joblib", ".parquet", ".xlsx", ".docx",
}
SKIP_FILES = {"uv.lock", "package-lock.json", "skills-lock.json"}
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg"}
CODE_NAMES = {"Dockerfile", "docker-compose.yml"}

PROVIDER_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_like_key": re.compile(r"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{24,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "resend_key": re.compile(r"\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{12,}\b"),
    "slack_token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}

SENSITIVE_NAME = r"(?:[A-Za-z_]*(?:api[_-]?key|apikey|secret|password|passwd|pwd|token|private[_-]?key|service[_-]?key)[A-Za-z_]*)"
ASSIGNMENT = re.compile(
    rf"""(?ix)
    (?P<name>{SENSITIVE_NAME})["']?\s*(?::|=|:=)\s*
    (?P<quote>["'])(?P<value>[^"'\s]{{8,}})(?P=quote)
    """
)
PLACEHOLDER = re.compile(
    r"<[^>]+>|\$\{|\{\{|replace|example|changeme|change-me|your[_-]|placeholder|dummy|fake|xxxx|\*\*\*|redacted|"
    r"^(?:none|null|true|false|bearer|basic)$|(?-i:^[A-Z][A-Z0-9_]+$)",  # el nombre de otra variable de entorno
    re.I,
)
SECRET_ENV_NAME = re.compile(r"(?i)(key|secret|password|token)")
# Nombres que contienen «key/secret/token» pero guardan un nombre, no un secreto
# (`SERVICE_KEY_HEADER = "X-Service-Key"`, `tokenUrl="/auth/login"`, un bloque de Prefect…).
NOT_A_SECRET_NAME = re.compile(
    r"(?i)(header|block|env|url|name|field|path|endpoint|prefix|type|kind|label|min_length|minutes|seconds|ttl)$|^event_"
)
# Identificadores en minúsculas sin dígitos («token_chunk», «trackflow_access_token»): nombres, no secretos.
IDENTIFIER_VALUE = re.compile(r"[a-z][a-z_.:-]*")


@dataclass
class Finding:
    rule: str
    path: str
    line: int
    preview: str


def mask(value: str) -> str:
    return value[:4] + "…" if len(value) > 4 else "…"


def tracked_files(root: Path = ROOT) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True).stdout
        return [line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        return [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]


def is_code(path: str) -> bool:
    p = Path(path)
    return p.suffix in CODE_SUFFIXES or p.name in CODE_NAMES


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    in_tests = path.startswith("tests/") or "/tests/" in path or Path(path).name.startswith("test_")
    for number, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARK in line:
            continue
        for rule, pattern in PROVIDER_PATTERNS.items():
            for match in pattern.finditer(line):
                findings.append(Finding(rule, path, number, mask(match.group(0))))
        if is_code(path) and not in_tests:
            for match in ASSIGNMENT.finditer(line):
                value = match.group("value")
                if (PLACEHOLDER.search(value) or NOT_A_SECRET_NAME.search(match.group("name"))
                        or IDENTIFIER_VALUE.fullmatch(value) or value.startswith(("/", "http"))
                        or "environ" in line or "getenv" in line):
                    continue
                findings.append(Finding("hardcoded_assignment", path, number, f"{match.group('name')}={mask(value)}"))
    return findings


def scan_env_example(path: str, text: str) -> list[Finding]:
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if (SECRET_ENV_NAME.search(name) and value and not PLACEHOLDER.search(value)
                and not NOT_A_SECRET_NAME.search(name.strip()) and not value.isdigit()):
            findings.append(Finding("env_example_real_value", path, number, f"{name.strip()}={mask(value)}"))
    return findings


def scan(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for rel in files if files is not None else tracked_files(root):
        name = Path(rel).name
        if name.startswith(".env") and name != ".env.example":
            findings.append(Finding("tracked_env_file", rel, 0, "fichero .env versionado"))
            continue
        if name in SKIP_FILES or Path(rel).suffix.lower() in BINARY_SUFFIXES:
            continue
        full = root / rel
        try:
            if not full.is_file() or full.stat().st_size > MAX_FILE_BYTES:
                continue
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_env_example(rel, text) if name == ".env.example" else scan_text(rel, text))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="salida JSON (evidencia)")
    args = parser.parse_args(argv)
    files = tracked_files()
    findings = scan(files=files)
    if args.json:
        print(json.dumps({"files_scanned": len(files), "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"Escaneo de secretos · {len(files)} ficheros versionados")
        print(f"Reglas: {len(PROVIDER_PATTERNS)} formatos de proveedor + asignaciones en código + .env versionados + .env.example")
        for finding in findings:
            print(f"  ✗ {finding.rule:<24} {finding.path}:{finding.line}  {finding.preview}")
        print("RESULTADO:", "PASS — 0 secretos en el código" if not findings else f"FAIL — {len(findings)} hallazgos")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
