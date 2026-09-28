import os

import pytest

from services.api.auth import (
    hash_password,
    verify_password,
    create_access_token,
    _decode_part,
    _signing_secret,
)

# Asegurar que la variable de entorno para los tests está presente
os.environ["AUTH_SECRET"] = "test-secret-key-123456"


def test_hash_password_happy_path():
    """Camino feliz: verifica que el hash se genera correctamente y tiene el formato esperado."""
    password = "SecurePassword123!"
    hashed = hash_password(password)
    
    assert hashed is not None
    assert isinstance(hashed, str)
    assert "pbkdf2_sha256" in hashed


def test_verify_password_happy_path():
    """Camino feliz: verifica que una contraseña correcta valida positivamente contra su hash."""
    password = "SecurePassword123!"
    hashed = hash_password(password)
    
    assert verify_password(password, hashed) is True


def test_verify_password_failure_mode():
    """Modo de fallo: verifica que una contraseña incorrecta rechaza la validación."""
    password = "SecurePassword123!"
    hashed = hash_password(password)
    
    assert verify_password("WrongPassword999!", hashed) is False


def test_verify_password_edge_case_malformed_hash():
    """Caso límite: verifica que un hash malformado no rompe la ejecución y retorna False."""
    assert verify_password("AnyPassword", "invalid$format$hash") is False


def test_create_access_token_happy_path():
    """Camino feliz: verifica que se genera un token de acceso válido para un user_id."""
    user_id = 42
    token = create_access_token(user_id)

    assert token is not None
    assert isinstance(token, str)
    assert len(token.split(".")) == 2  # Payload y firma separados por punto


def test_decode_part():
    """Camino feliz: verifica la decodificación base64 interna."""
    # "YmFzZTY0" es "base64" codificado
    assert _decode_part("YmFzZTY0") == b"base64"


def test_signing_secret_missing(monkeypatch):
    """Modo de fallo: verifica que falle si falta la variable de entorno."""
    # Borramos temporalmente la variable de entorno
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_SECRET must be configured"):
        _signing_secret()
    