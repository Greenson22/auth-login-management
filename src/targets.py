"""Nilai kanonik dan persistensi Target global.

Target hanya boleh bernilai ``opencode`` atau ``antigravity_cli``. Nilai kosong
atau tidak dikenal selalu diperlakukan sebagai ``opencode`` agar aplikasi lama
tetap berjalan tanpa migrasi setting.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSettings

TARGET_OPENCODE = "opencode"
TARGET_ANTIGRAVITY_CLI = "antigravity_cli"

ALL_TARGETS = (TARGET_OPENCODE, TARGET_ANTIGRAVITY_CLI)
TARGET_LABELS = {
    TARGET_OPENCODE: "OpenCode",
    TARGET_ANTIGRAVITY_CLI: "Antigravity CLI",
}
ACTIVE_TARGET_KEY = "active_target"

SETTINGS_ORGANIZATION = "OpenCodeApp"
SETTINGS_APPLICATION = "AccountManager"


def create_settings() -> QSettings:
  """QSettings produksi untuk organisasi/aplikasi yang sudah dipakai aplikasi."""
  return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def normalize_target(value: object) -> str:
  """Kembalikan target kanonik; nilai kosong/tak dikenal menjadi OpenCode."""
  if isinstance(value, str) and value in ALL_TARGETS:
    return value
  return TARGET_OPENCODE


def load_active_target(settings: Optional[QSettings] = None) -> str:
  """Baca Selected Target dari QSettings dengan fallback OpenCode."""
  settings = settings if settings is not None else create_settings()
  return normalize_target(settings.value(ACTIVE_TARGET_KEY))


def save_active_target(
    settings: Optional[QSettings], target: str
) -> str:
  """Simpan target kanonik ke QSettings dan kembalikan nilai yang disimpan."""
  settings = settings if settings is not None else create_settings()
  canonical = normalize_target(target)
  settings.setValue(ACTIVE_TARGET_KEY, canonical)
  settings.sync()
  return canonical


def target_label(target: object) -> str:
  """Label tampilan untuk sebuah nilai target."""
  return TARGET_LABELS[normalize_target(target)]
