"""NIST · Protect: ningún secreto escrito en el código (criterio de la rúbrica).

* El repositorio entero pasa el escáner (`scripts/secrets_scan.py`): ni claves con
  formato de proveedor, ni literales asignados a nombres sensibles, ni `.env`
  versionados, ni valores reales en `.env.example`.
* El escáner detecta de verdad lo que dice detectar (contenido sintético) y no
  imprime nunca el secreto entero.
* Los secretos de la aplicación se leen del entorno.

    python -m pytest tests/test_nist_secrets.py
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("secrets_scan", ROOT / "scripts" / "secrets_scan.py")
secrets_scan = importlib.util.module_from_spec(spec)
sys.modules["secrets_scan"] = secrets_scan  # las dataclasses lo buscan en sys.modules
spec.loader.exec_module(secrets_scan)

# Construidos por partes para que este fichero no contenga ningún secreto con formato real.
FAKE_OPENAI = "sk-" + "Zx9" * 10
FAKE_GITHUB = "ghp_" + "a1" * 18
FAKE_JWT = "eyJ" + "h" * 12 + ".eyJ" + "p" * 12 + "." + "s" * 16


def test_the_repository_has_no_hardcoded_secrets():
    findings = secrets_scan.scan(ROOT)
    assert findings == [], "\n".join(f"{f.rule} {f.path}:{f.line} {f.preview}" for f in findings)


@pytest.mark.parametrize("line, rule", [
    (f'LLM_API_KEY = "{FAKE_OPENAI}"', "openai_like_key"),
    (f"token: {FAKE_GITHUB}", "github_token"),
    (f"Authorization: Bearer {FAKE_JWT}", "jwt"),
    ("-----BEGIN RSA " + "PRIVATE KEY-----", "private_key"),
    ('MCP_AGENT_CLIENT_SECRET = "h7Ks92LmQp4"', "hardcoded_assignment"),
    ('const apiKey = "Q2w3E4r5T6y7"', "hardcoded_assignment"),
])
def test_scanner_detects_secrets(line, rule):
    findings = secrets_scan.scan_text("services/example.py", line)
    assert rule in {finding.rule for finding in findings}
    assert all(len(finding.preview) < 40 and FAKE_OPENAI not in finding.preview for finding in findings)


@pytest.mark.parametrize("line", [
    'api_key = os.environ["LLM_API_KEY"]',
    'secret = os.getenv("JWT_SECRET", "")',
    'password = "<tu-contraseña>"',
    'SERVICE_KEY_HEADER = "X-Service-Key"',
    'oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")',
    'EVENT_TOKEN_CHUNK = "token_chunk"',
    'DEFAULT_PASSWORD = "password123"  # secrets-scan: allow (valor de prueba)',
])
def test_scanner_ignores_names_env_reads_placeholders_and_allowed_lines(line):
    assert secrets_scan.scan_text("services/example.py", line) == []


def test_test_fixtures_are_not_flagged_for_assignments_but_real_key_formats_are():
    assert secrets_scan.scan_text("tests/test_x.py", 'password = "SecurePassword123!"') == []
    assert secrets_scan.scan_text("tests/test_x.py", f'key = "{FAKE_OPENAI}"')[0].rule == "openai_like_key"


def test_env_example_must_not_carry_real_values():
    text = "JWT_SECRET=\nLLM_API_KEY=\nAUTH_SECRET=replace-with-a-long-random-secret\nACCESS_TOKEN_EXPIRE_MINUTES=60\n"
    assert secrets_scan.scan_env_example(".env.example", text) == []
    flagged = secrets_scan.scan_env_example(".env.example", "JWT_SECRET=s3cr3tValue99\n")
    assert flagged[0].rule == "env_example_real_value" and "s3cr3tValue99" not in flagged[0].preview


def test_tracked_env_files_are_flagged(tmp_path):
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("X=\n", encoding="utf-8")
    findings = secrets_scan.scan(tmp_path, files=[".env", ".env.example"])
    assert [finding.rule for finding in findings] == ["tracked_env_file"]


def test_application_secrets_are_read_from_the_environment():
    expected = {
        "services/api/security.py": "JWT_SECRET",
        "services/api/email.py": "RESEND_API_KEY",
        "services/agent/mcp_client.py": "MCP_AGENT_CLIENT_SECRET",
    }
    for path, name in expected.items():
        source = (ROOT / path).read_text(encoding="utf-8")
        assert name in source, path
        assert f'{name} = "' not in source and f"{name}='" not in source, path
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore and "!.env.example" in gitignore
