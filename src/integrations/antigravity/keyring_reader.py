"""Modul KeyringReader — membaca dan memparsing Keyring Item Antigravity CLI.

Bertanggung jawab hanya untuk membaca ``service=gemini, username=antigravity``
via KeyringPort yang diinjeksi, memparsing JSON-nya, dan mendekode email dari
klaim ``email`` di payload JWT ``id_token``.

Tidak ada ``import dbus`` di sini — semua akses keyring dilakukan lewat port.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .constants import KEYRING_SERVICE, KEYRING_USERNAME
from .errors import (
    KeyringItemNotFoundError,
    KeyringLockedError,
    KeyringParseError,
    KeyringUnavailableError,
)
from .ports import KeyringPort


@dataclass(frozen=True)
class KeyringImportData:
    """Data yang diekstrak dari Keyring Item Antigravity CLI."""

    refresh_token: str
    email: Optional[str]        # None jika id_token tidak ada atau tidak bisa di-decode
    project_id: Optional[str]   # Dari JSON keyring jika tersedia
    raw_fields: Dict[str, Any] = field(default_factory=dict)  # Semua field lain dari JSON keyring


def _decode_id_token_email(id_token: str) -> Optional[str]:
    """Membaca klaim email dari payload JWT tanpa memverifikasi tanda tangan.

    Jika id_token tidak valid atau klaim email tidak ada, kembalikan None.
    """
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        # Tambah padding agar base64 valid
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None
    email = payload.get("email")
    return email if isinstance(email, str) and email else None


class KeyringReader:
    """Membaca dan memparsing Keyring Item ``service=gemini, username=antigravity``.

    Dependensi satu-satunya adalah ``KeyringPort`` yang diinjeksi — tidak ada
    akses langsung ke D-Bus atau Secret Service.
    """

    def read_and_parse(self, keyring: KeyringPort) -> KeyringImportData:
        """Baca item keyring, parse JSON, dan kembalikan ``KeyringImportData``.

        Raises:
            KeyringUnavailableError: Keyring/D-Bus tidak dapat dihubungi.
            KeyringLockedError: Keyring terkunci.
            KeyringItemNotFoundError: Item tidak ada di keyring.
            KeyringParseError: JSON tidak valid atau field ``refresh_token`` tidak ada.
        """
        # Baca dari keyring; tangkap error yang dilempar port
        try:
            raw_bytes = keyring.read(KEYRING_SERVICE, KEYRING_USERNAME)
        except KeyringUnavailableError:
            raise
        except KeyringLockedError:
            raise
        except Exception as exc:
            raise KeyringUnavailableError(str(exc)) from exc

        if raw_bytes is None:
            raise KeyringItemNotFoundError(
                f"Item service={KEYRING_SERVICE!r}/username={KEYRING_USERNAME!r} "
                "tidak ada di keyring."
            )

        # Parse JSON
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise KeyringParseError(f"JSON keyring tidak valid: {exc}") from exc

        if not isinstance(data, dict):
            raise KeyringParseError("JSON keyring bukan objek.")

        # Ambil refresh_token — bisa di root atau di bawah kunci "token"
        token_section = data.get("token", {}) if isinstance(data.get("token"), dict) else {}
        refresh_token = data.get("refresh_token") or token_section.get("refresh_token")

        if not refresh_token or not isinstance(refresh_token, str):
            raise KeyringParseError(
                "Field 'refresh_token' tidak ada atau kosong di JSON keyring."
            )

        # Ambil project_id (opsional)
        project_id = data.get("project_id") or token_section.get("project_id")
        if project_id is not None and not isinstance(project_id, str):
            project_id = str(project_id)

        # Decode email dari id_token (opsional — tidak error jika tidak ada)
        id_token = data.get("id_token") or token_section.get("id_token")
        email: Optional[str] = None
        if id_token and isinstance(id_token, str):
            email = _decode_id_token_email(id_token)

        # raw_fields: semua field selain yang sudah diekstrak
        raw_fields = {k: v for k, v in data.items()}

        return KeyringImportData(
            refresh_token=refresh_token,
            email=email,
            project_id=project_id,
            raw_fields=raw_fields,
        )
