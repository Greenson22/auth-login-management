"""Unit test untuk KeyringReader (Tiket 01).

Menguji semua kasus yang disebutkan di tiket:
1. Item ada + JSON valid + id_token punya email → data lengkap
2. Item ada + JSON tanpa id_token → email=None, refresh_token tidak kosong
3. Item tidak ada → raise KeyringItemNotFoundError
4. Keyring tidak tersedia → raise KeyringUnavailableError
5. Keyring terkunci → raise KeyringLockedError
6. JSON rusak → raise KeyringParseError
7. JSON valid tapi refresh_token tidak ada → raise KeyringParseError

Setiap test menggunakan FakeKeyring dan make_id_token dari tests/fakes.py —
tidak ada fake baru.
"""

from __future__ import annotations

import json

import pytest

from src.integrations.antigravity.errors import (
    KeyringItemNotFoundError,
    KeyringLockedError,
    KeyringParseError,
    KeyringUnavailableError,
)
from src.integrations.antigravity.keyring_reader import KeyringImportData, KeyringReader
from tests.fakes import FakeKeyring, make_id_token

KEYRING_SERVICE = "gemini"
KEYRING_USERNAME = "antigravity"


def _write_json(keyring: FakeKeyring, data: dict) -> None:
    """Helper: tulis dict sebagai JSON bytes ke keyring."""
    keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(data).encode("utf-8"))


# ─── Kasus 1: Item ada, JSON valid, id_token punya email ─────────────────────


def test_happy_path_dengan_id_token(fake_keyring: FakeKeyring) -> None:
    """Item ada + JSON valid + id_token dengan email → data lengkap dikembalikan."""
    email = "user@example.com"
    refresh_token = "1//rt_xyz_valid"
    id_token = make_id_token(email)

    _write_json(fake_keyring, {
        "refresh_token": refresh_token,
        "id_token": id_token,
        "project_id": "my-project-123",
    })

    reader = KeyringReader()
    result = reader.read_and_parse(fake_keyring)

    assert isinstance(result, KeyringImportData)
    assert result.refresh_token == refresh_token
    assert result.email == email
    assert result.project_id == "my-project-123"
    assert isinstance(result.raw_fields, dict)


# ─── Kasus 2: Item ada, JSON tanpa id_token ───────────────────────────────────


def test_tanpa_id_token_email_adalah_none(fake_keyring: FakeKeyring) -> None:
    """JSON tanpa id_token → email=None; refresh_token tidak kosong."""
    refresh_token = "1//rt_no_id_token"

    _write_json(fake_keyring, {
        "refresh_token": refresh_token,
    })

    reader = KeyringReader()
    result = reader.read_and_parse(fake_keyring)

    assert result.email is None
    assert result.refresh_token == refresh_token


# ─── Kasus 3: Item tidak ada ──────────────────────────────────────────────────


def test_item_tidak_ada_raise_not_found(fake_keyring: FakeKeyring) -> None:
    """Keyring kosong → raise KeyringItemNotFoundError."""
    reader = KeyringReader()

    with pytest.raises(KeyringItemNotFoundError):
        reader.read_and_parse(fake_keyring)


# ─── Kasus 4: Keyring tidak tersedia ─────────────────────────────────────────


def test_keyring_tidak_tersedia_raise_unavailable(fake_keyring: FakeKeyring) -> None:
    """available=False → raise KeyringUnavailableError."""
    fake_keyring.available = False
    reader = KeyringReader()

    with pytest.raises(KeyringUnavailableError):
        reader.read_and_parse(fake_keyring)


# ─── Kasus 5: Keyring terkunci ────────────────────────────────────────────────


def test_keyring_terkunci_raise_locked(fake_keyring: FakeKeyring) -> None:
    """locked=True → raise KeyringLockedError."""
    fake_keyring.locked = True
    reader = KeyringReader()

    with pytest.raises(KeyringLockedError):
        reader.read_and_parse(fake_keyring)


# ─── Kasus 6: JSON rusak ──────────────────────────────────────────────────────


def test_json_rusak_raise_parse_error(fake_keyring: FakeKeyring) -> None:
    """Bytes non-JSON → raise KeyringParseError."""
    fake_keyring.write(KEYRING_SERVICE, KEYRING_USERNAME, b"ini bukan JSON {{{")
    reader = KeyringReader()

    with pytest.raises(KeyringParseError):
        reader.read_and_parse(fake_keyring)


# ─── Kasus 7: JSON valid tapi refresh_token tidak ada ────────────────────────


def test_refresh_token_tidak_ada_raise_parse_error(fake_keyring: FakeKeyring) -> None:
    """JSON valid tapi tidak memiliki refresh_token → raise KeyringParseError."""
    _write_json(fake_keyring, {
        "access_token": "ya29.some-access-token",
        "id_token": make_id_token("user@example.com"),
    })
    reader = KeyringReader()

    with pytest.raises(KeyringParseError):
        reader.read_and_parse(fake_keyring)


# ─── Kasus bonus: id_token tidak bisa di-decode → email=None, bukan error ────


def test_id_token_tidak_valid_email_adalah_none(fake_keyring: FakeKeyring) -> None:
    """id_token yang tidak bisa di-decode → email=None (bukan error)."""
    _write_json(fake_keyring, {
        "refresh_token": "1//rt_valid",
        "id_token": "ini.bukan.jwt.valid",
    })
    reader = KeyringReader()
    result = reader.read_and_parse(fake_keyring)

    assert result.email is None
    assert result.refresh_token == "1//rt_valid"


# ─── Kasus: refresh_token di dalam section "token" ───────────────────────────


def test_refresh_token_di_dalam_section_token(fake_keyring: FakeKeyring) -> None:
    """refresh_token yang tersimpan di sub-objek 'token' berhasil dibaca."""
    email = "nested@example.com"
    refresh_token = "1//rt_nested_token"
    id_token = make_id_token(email)

    _write_json(fake_keyring, {
        "token": {
            "refresh_token": refresh_token,
            "access_token": "ya29.nested-access",
            "id_token": id_token,
        },
        "auth_method": "consumer",
    })

    reader = KeyringReader()
    result = reader.read_and_parse(fake_keyring)

    assert result.refresh_token == refresh_token
    assert result.email == email
