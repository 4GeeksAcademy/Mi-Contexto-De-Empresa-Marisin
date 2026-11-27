"""Validación estática del endurecimiento del servidor (OWASP, D1–D7, D19).

Sin Docker ni red: comprueba que los ficheros de `infra/hardening/` dicen lo que el plan
decide. Lo dinámico (SSH real, ufw, escaneo) lo demuestra el laboratorio (`lab.sh`).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARDENING = ROOT / "infra" / "hardening"
SSH_DROPIN = HARDENING / "sshd_config.d" / "10-trackflow-hardening.conf"
HARDEN = HARDENING / "harden.sh"
AUDIT = HARDENING / "audit.sh"
SCAN = HARDENING / "scan_ports.sh"
LAB = HARDENING / "lab.sh"
SERVER_DOCKERFILE = HARDENING / "server-sim" / "Dockerfile"
ENTRYPOINT = HARDENING / "server-sim" / "entrypoint.sh"

SHELL_SCRIPTS = [HARDEN, AUDIT, SCAN, LAB, ENTRYPOINT]
STACK_PORTS = {22, 80, 443, 3000, 3001, 3002, 5555, 6333, 6379, 8000, 8001}
PUBLIC_PORTS = {22, 80, 443}


def _sshd_options(path: Path) -> dict[str, str]:
    options: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        assert key.lower() not in options, f"opción repetida en el drop-in: {key}"
        options[key.lower()] = value.strip()
    return options


def _code_lines(path: Path) -> list[str]:
    """Líneas del script sin comentarios (para no contar lo que solo se documenta)."""
    return [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


# --------------------------------------------------------------------------- #
# Scripts de shell
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("bash") is None, reason="sin bash")
@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_parse_with_bash_n(script):
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_are_executable_bash(script):
    assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash\n")
    assert script.stat().st_mode & 0o111, f"{script.name} no es ejecutable"


@pytest.mark.parametrize("script", [HARDEN, LAB, ENTRYPOINT], ids=lambda p: p.name)
def test_scripts_that_change_state_stop_on_errors(script):
    assert "set -euo pipefail" in script.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# SSH (D4)
# --------------------------------------------------------------------------- #
def test_ssh_dropin_has_exactly_the_planned_options():
    assert _sshd_options(SSH_DROPIN) == {
        "permitrootlogin": "no",
        "passwordauthentication": "no",
        "kbdinteractiveauthentication": "no",
        "pubkeyauthentication": "yes",
        "authenticationmethods": "publickey",
        "allowusers": "trackflow-ops",
        "maxauthtries": "3",
        "logingracetime": "30",
        "x11forwarding": "no",
        "allowtcpforwarding": "no",
        "clientaliveinterval": "300",
        "clientalivecountmax": "2",
    }


def test_ssh_dropin_loads_before_other_dropins():
    # sshd se queda con el primer valor leído: 10- va antes que, p. ej., 50-cloud-init.conf.
    assert re.fullmatch(r"\d\d-[a-z-]+\.conf", SSH_DROPIN.name)
    assert int(SSH_DROPIN.name[:2]) < 50


def test_harden_validates_sshd_before_reloading():
    text = HARDEN.read_text(encoding="utf-8")
    setup_ssh = text[text.index("setup_ssh() {"):text.index("# (c) Permisos")]
    assert "/etc/ssh/sshd_config.d/10-trackflow-hardening.conf" in text
    assert setup_ssh.index("sshd -t") < setup_ssh.index("reload_sshd")
    assert "die" in setup_ssh[setup_ssh.index("sshd -t"):setup_ssh.index("reload_sshd")]


def test_harden_removes_root_keys_only_after_ops_has_a_key():
    text = HARDEN.read_text(encoding="utf-8")
    assert "rm -f /root/.ssh/authorized_keys" in text
    assert 'no tiene ninguna clave autorizada' in text
    order = [text.rindex(f"\n{step}\n") for step in ("setup_users", "setup_ssh", "remove_root_keys")]
    assert order == sorted(order)


# --------------------------------------------------------------------------- #
# Usuarios (D3)
# --------------------------------------------------------------------------- #
def test_harden_creates_service_account_without_login_or_sudo():
    text = HARDEN.read_text(encoding="utf-8")
    assert 'SERVICE_USER="trackflow"' in text
    assert re.search(r"useradd --system --user-group --no-create-home --home-dir /nonexistent\s*\\\s*\n\s*"
                     r"--shell /usr/sbin/nologin \"\$SERVICE_USER\"", text)
    assert 'gpasswd -d "$SERVICE_USER" sudo' in text


def test_harden_creates_ops_user_with_password_sudo():
    text = HARDEN.read_text(encoding="utf-8")
    assert 'OPS_USER="trackflow-ops"' in text
    assert 'useradd --create-home --user-group --shell /bin/bash "$OPS_USER"' in text
    assert 'usermod -aG sudo "$OPS_USER"' in text
    assert 'gpasswd -d "$OPS_USER" "$SERVICE_USER"' in text  # ops no lee config/.env
    assert re.search(r"NOPASSWD.*\n.*die ", text)  # una regla NOPASSWD para ops detiene el script


# --------------------------------------------------------------------------- #
# Permisos (D5)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "expected",
    [
        'install -d -m 755 -o root -g root "$BASE_DIR"',
        'chown -R "$OPS_USER:$SERVICE_USER" "$BASE_DIR/app"',
        'find "$BASE_DIR/app" -type d -exec chmod 750 {} +',
        'find "$BASE_DIR/app" -type f -exec chmod 640 {} +',
        'chown -R "$SERVICE_USER:$OPS_USER" "$BASE_DIR/logs"',
        'chmod 2750 "$BASE_DIR/logs"',
        'chown -R "root:$SERVICE_USER" "$BASE_DIR/config"',
        'chmod 750 "$BASE_DIR/config"',
        'find "$BASE_DIR/config" -type f -exec chmod 640 {} +',
        "UMask=0027",
    ],
)
def test_harden_sets_explicit_folder_permissions(expected):
    assert expected in HARDEN.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "expected",
    [
        '"755 root:root"',
        '"750 $OPS_USER:$SERVICE_USER"',
        '"2750 $SERVICE_USER:$OPS_USER"',
        '"750 root:$SERVICE_USER"',
        '"640 root:$SERVICE_USER"',
    ],
)
def test_audit_checks_the_same_permissions(expected):
    assert expected in AUDIT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Firewall (D6)
# --------------------------------------------------------------------------- #
def _ufw_commands() -> list[str]:
    return [line.strip() for line in _code_lines(HARDEN) if line.strip().startswith("ufw ")]


def test_firewall_denies_incoming_by_default():
    commands = _ufw_commands()
    assert "ufw --force reset >/dev/null" in commands
    assert "ufw default deny incoming" in commands
    assert "ufw default allow outgoing" in commands
    assert commands.index("ufw --force reset >/dev/null") < commands.index("ufw default deny incoming")
    assert any(c.startswith("ufw --force enable") for c in commands)


def test_firewall_opens_only_ssh_http_and_https():
    opened: dict[int, str] = {}
    for command in _ufw_commands():
        match = re.match(r"ufw (allow|limit) (\S+)", command)
        if match:
            action, target = match.groups()
            assert re.fullmatch(r"\d+/tcp", target), f"regla demasiado amplia: {command}"
            opened[int(target.split("/")[0])] = action
    assert opened == {22: "limit", 80: "allow", 443: "allow"}
    assert set(opened) == PUBLIC_PORTS


def test_firewall_lab_mode_uses_empty_sysctl_file():
    text = HARDEN.read_text(encoding="utf-8")
    assert 'UFW_LAB_SYSCTL="/etc/ufw/sysctl-lab.conf"' in text
    assert 's|^IPT_SYSCTL=.*|IPT_SYSCTL=$UFW_LAB_SYSCTL|' in text
    assert "STOP (D6)" in text


def test_audit_expects_only_the_public_rules():
    assert '"22/tcp=LIMIT 80/tcp=ALLOW 443/tcp=ALLOW"' in AUDIT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Laboratorio (D1, D2, D7)
# --------------------------------------------------------------------------- #
def test_lab_image_installs_only_the_planned_packages():
    text = SERVER_DOCKERFILE.read_text(encoding="utf-8")
    assert [line for line in text.splitlines() if line.startswith("FROM")] == ["FROM ubuntu:24.04"]
    block = text[text.index("--no-install-recommends"):text.index("rm -rf /var/lib/apt/lists/*")]
    packages = set(re.findall(r"^\s+([a-z0-9][a-z0-9.+-]+) \\$", block, flags=re.M))
    assert packages == {"openssh-server", "openssh-client", "ufw", "iptables", "sudo", "netcat-openbsd"}
    assert "EXPOSE" not in text


def test_lab_image_starts_insecure_on_purpose():
    text = SERVER_DOCKERFILE.read_text(encoding="utf-8")
    assert "PermitRootLogin yes" in text
    assert "PasswordAuthentication yes" in text
    assert "ssh-keygen -q -t ed25519 -N '' -C 'trackflow-lab-key' -f /opt/lab-keys/id_ed25519" in text
    assert "cp /opt/lab-keys/id_ed25519.pub /root/.ssh/authorized_keys" in text
    assert "chmod -R 777 /srv/trackflow" in text


def test_lab_entrypoint_listens_on_every_stack_port():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    ports = {int(p) for p in re.search(r"STACK_PORTS=\(([^)]*)\)", text).group(1).split()}
    assert ports | {22} == STACK_PORTS
    assert "exec /usr/sbin/sshd -D -e" in text


def test_scan_covers_the_eleven_stack_ports():
    text = SCAN.read_text(encoding="utf-8")
    ports = {int(p) for p in re.search(r"DEFAULT_PORTS=\(([^)]*)\)", text).group(1).split()}
    assert ports == STACK_PORTS
    assert "timeout 2" in text and "/dev/tcp/" in text


def test_lab_never_publishes_ports_nor_mounts_the_workspace():
    code = "\n".join(_code_lines(LAB)).replace("\\\n", " ")  # une las líneas partidas con «\»
    runs = [line for line in code.splitlines() if "docker run" in line]
    assert len(runs) == 2  # el servidor (up) y el cliente (client)
    for line in runs:
        assert not re.search(r"\s(-p|-P|-v)\s|--publish|--volume|--mount", line), line
    text = LAB.read_text(encoding="utf-8")
    assert "--cap-add NET_ADMIN" in text
    assert 'docker cp "$SCRIPT_DIR/harden.sh"' in text
    assert 'NETWORK="trackflow-hardening-net"' in text
    assert 'IMAGE="trackflow-server-sim"' in text
    assert 'CONTAINER="trackflow-server"' in text


@pytest.mark.parametrize("subcommand", ["space", "up", "audit", "scan", "ssh-test", "harden", "down"])
def test_lab_has_every_subcommand(subcommand):
    text = LAB.read_text(encoding="utf-8")
    assert re.search(rf"^\s+{re.escape(subcommand)}\) cmd_", text, flags=re.M)


def test_lab_down_removes_container_network_and_image():
    text = LAB.read_text(encoding="utf-8")
    down = text[text.index("cmd_down() {"):text.index("\n}\n", text.index("cmd_down() {"))]
    assert 'docker rm -f "$CONTAINER"' in down
    assert 'docker network rm "$NETWORK"' in down
    assert 'docker image rm "$IMAGE"' in down


def test_lab_key_is_never_stored_in_the_repo():
    tracked = subprocess.run(["git", "ls-files", "infra/hardening"], cwd=ROOT, capture_output=True, text=True)
    if tracked.returncode != 0:
        pytest.skip("sin git")
    for name in tracked.stdout.split():
        assert not name.endswith((".pem", ".key", "id_ed25519", "id_ed25519.pub")), name
    for path in HARDENING.rglob("*"):
        if path.is_file():
            assert "PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="ignore"), path


# --------------------------------------------------------------------------- #
# Contenedores de la pila (Fase 5: D16, D17)
# --------------------------------------------------------------------------- #
COMPOSE = ROOT / "docker-compose.yml"
API_DOCKERFILE = ROOT / "services" / "Dockerfile"
UI_DOCKERFILE = ROOT / "uis" / "Dockerfile"
LOOPBACK_PORT = re.compile(r"^\$\{TRACKFLOW_BIND_ADDR:-127\.0\.0\.1\}:\d+:\d+$")


def _compose() -> dict:
    import yaml  # ya instalado (dependencia transitiva); se lee el fichero en crudo, sin el .env

    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _published_ports() -> list[tuple[str, str]]:
    return [(name, str(port)) for name, service in _compose()["services"].items()
            for port in service.get("ports", [])]


def test_compose_publishes_every_port_on_loopback_by_default():
    ports = _published_ports()
    assert {name for name, _ in ports} == {"ui", "api", "qdrant", "redis", "flower"}
    for name, port in ports:
        assert LOOPBACK_PORT.match(port), f"{name}: {port}"


def test_compose_publishes_only_the_known_stack_ports():
    published = {int(port.rsplit(":", 2)[-2]) for _, port in _published_ports()}
    assert published == {3000, 3001, 3002, 8000, 6333, 6379, 5555}


def test_flower_is_dev_only_and_reads_basic_auth():
    flower = _compose()["services"]["flower"]
    assert flower["profiles"] == ["dev"]
    assert flower["environment"]["FLOWER_BASIC_AUTH"] == "${FLOWER_BASIC_AUTH:-}"
    others = {name for name, service in _compose()["services"].items() if "profiles" in service}
    assert others == {"flower"}  # el resto arranca con `docker compose up`


def _instructions(path: Path) -> list[str]:
    return [line.strip() for line in _code_lines(path) if line.strip()]


def _last_user(path: Path) -> str | None:
    users = [line.split(None, 1)[1] for line in _instructions(path) if line.upper().startswith("USER ")]
    return users[-1] if users else None


@pytest.mark.parametrize("dockerfile, user", [(API_DOCKERFILE, "trackflow"), (UI_DOCKERFILE, "node")])
def test_containers_do_not_run_as_root(dockerfile, user):
    assert _last_user(dockerfile) == user
    lines = _instructions(dockerfile)
    user_at = max(i for i, line in enumerate(lines) if line.upper().startswith("USER "))
    cmd_at = max(i for i, line in enumerate(lines) if line.upper().startswith("CMD "))
    assert user_at < cmd_at


@pytest.mark.parametrize("dockerfile, owner", [(API_DOCKERFILE, "trackflow:trackflow"), (UI_DOCKERFILE, "node:node")])
def test_code_is_copied_with_the_unprivileged_owner(dockerfile, owner):
    copies = [line for line in _instructions(dockerfile) if line.upper().startswith("COPY ")]
    app_copies = [line for line in copies if line.endswith(" .") or "package.json" in line]
    assert app_copies
    assert all(f"--chown={owner}" in line for line in app_copies), app_copies


def test_api_service_account_has_fixed_ids_and_no_login():
    text = API_DOCKERFILE.read_text(encoding="utf-8")
    assert "groupadd --system --gid 10001 trackflow" in text
    assert "useradd --system --uid 10001 --gid trackflow --no-create-home --shell /usr/sbin/nologin trackflow" in text


def test_ui_installs_dependencies_as_node():
    lines = _instructions(UI_DOCKERFILE)
    user_at = next(i for i, line in enumerate(lines) if line == "USER node")
    install_at = next(i for i, line in enumerate(lines) if "npm install" in line)
    assert user_at < install_at


def test_api_runs_without_reload():
    cmd = next(line for line in _instructions(API_DOCKERFILE) if line.upper().startswith("CMD "))
    assert "--reload" not in cmd
    assert '"api.main:app"' in cmd
