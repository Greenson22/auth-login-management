"""Tests untuk ImportDialog dan entri menu File (Tiket 02).

Kasus yang diuji:
1. Dialog terbuka dengan form lengkap dan data dari keyring terisi:
   - email (read-only)
   - refresh token (SecureLineEdit dengan mode Password + tombol reveal)
   - project ID (editable)
   - kategori (editable combobox terisi kategori dari DB)
2. Dialog tidak terbuka jika keyring error (item tidak ada, terkunci, tidak tersedia):
   - QMessageBox ditampilkan
   - exec() mengembalikan Rejected
3. Tombol Batal menutup dialog tanpa perubahan pada DB.
4. Menu File -> "Import dari Antigravity…" ada di MainWindow.
5. Menu action dinonaktifkan dengan tooltip yang sesuai bila CLI tidak tersedia (non-Linux, keyring locked, dsb).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLineEdit, QMessageBox

from src.database import AccountDatabase
from src.integrations.antigravity.constants import KEYRING_SERVICE, KEYRING_USERNAME
from src.ui.components.import_dialog import ImportDialog
from src.ui.main_window import MainWindow, REASON_MESSAGES
from tests.fakes import FakeClock, FakeKeyring, FakeOAuth, FakeRoot, make_id_token


class FakeDBForDialog:
    """Fake minimal untuk AccountDatabase yang dipakai ImportDialog."""

    def __init__(self, categories: Optional[List[str]] = None):
        self._categories = categories or ["Pribadi", "Kerja", "Testing"]
        self.inserted_or_updated: List[Dict[str, Any]] = []
        self.updated_tokens: List[Dict[str, Any]] = []

    def fetch_categories(self) -> List[str]:
        return list(self._categories)

    def insert_or_update_json(self, json_str: str, encrypt: bool = False, password: str = "") -> bool:
        self.inserted_or_updated.append({
            "json_str": json_str,
            "encrypt": encrypt,
            "password": password,
        })
        return True

    def update_refresh_token(self, account_id: str, new_token: str, password: str = "") -> bool:
        self.updated_tokens.append({
            "account_id": account_id,
            "new_token": new_token,
            "password": password,
        })
        return True


def test_dialog_opens_with_keyring_data(qtbot):
    """Dialog terbuka dengan data yang dibaca dari keyring."""
    keyring = FakeKeyring()
    email = "antigravity.user@example.com"
    refresh_token = "1//rt_super_secret_123"
    project_id = "test-project-456"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": refresh_token,
            "id_token": make_id_token(email),
            "project_id": project_id,
        }).encode("utf-8"),
    )

    db = FakeDBForDialog(categories=["Alpha", "Beta"])
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=refresh_token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db, password="dummy_pass")
    qtbot.addWidget(dialog)

    # Tunggu validasi selesai
    if dialog._validation_worker:
        qtbot.waitUntil(lambda: "Valid" in dialog.token_status_badge.text(), timeout=2000)

    assert dialog.import_data is not None
    assert dialog.email_input.text() == email
    assert dialog.email_input.isReadOnly() is True

    # Token tersimpan dan dalam mode password
    assert dialog.token_input.text() == refresh_token
    assert dialog.token_input.echoMode() == QLineEdit.EchoMode.Password

    # Project ID terisi
    assert dialog.project_id_input.text() == project_id
    assert dialog.project_id_input.isReadOnly() is False

    # Kategori combo terisi dari DB dan editable
    assert dialog.category_combo.isEditable() is True
    categories = [dialog.category_combo.itemText(i) for i in range(dialog.category_combo.count())]
    assert "Alpha" in categories
    assert "Beta" in categories

    # Reveal button toggle
    dialog.reveal_btn.click()
    assert dialog.token_input.echoMode() == QLineEdit.EchoMode.Normal
    dialog.reveal_btn.click()
    assert dialog.token_input.echoMode() == QLineEdit.EchoMode.Password


def test_dialog_does_not_open_when_keyring_empty(qtbot, monkeypatch):
    """Jika keyring kosong (item tidak ada), dialog tidak terbuka dan QMessageBox muncul."""
    keyring = FakeKeyring()
    db = FakeDBForDialog()
    oauth = FakeOAuth()

    warning_called = []

    def mock_warning(parent, title, text):
        warning_called.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    assert dialog.import_data is None
    assert len(warning_called) == 1
    assert "Tidak Ditemukan" in warning_called[0][0]
    assert dialog.exec() == QDialog.DialogCode.Rejected


def test_dialog_does_not_open_when_keyring_locked(qtbot, monkeypatch):
    """Jika keyring terkunci, dialog tidak terbuka dan QMessageBox muncul."""
    keyring = FakeKeyring()
    keyring.locked = True
    db = FakeDBForDialog()
    oauth = FakeOAuth()

    warning_called = []

    def mock_warning(parent, title, text):
        warning_called.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    assert dialog.import_data is None
    assert len(warning_called) == 1
    assert "Terkunci" in warning_called[0][0]
    assert dialog.exec() == QDialog.DialogCode.Rejected


def test_dialog_does_not_open_when_keyring_unavailable(qtbot, monkeypatch):
    """Jika keyring tidak tersedia, dialog tidak terbuka dan QMessageBox muncul."""
    keyring = FakeKeyring()
    keyring.available = False
    db = FakeDBForDialog()
    oauth = FakeOAuth()

    critical_called = []

    def mock_critical(parent, title, text):
        critical_called.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    assert dialog.import_data is None
    assert len(critical_called) == 1
    assert "Tidak Tersedia" in critical_called[0][0]
    assert dialog.exec() == QDialog.DialogCode.Rejected


def test_cancel_button_closes_dialog_without_changes(qtbot):
    """Menekan tombol Batal menutup dialog dengan Rejected dan DB tidak tersentuh."""
    keyring = FakeKeyring()
    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": "1//rt_dummy",
            "id_token": make_id_token("user@example.com"),
        }).encode("utf-8"),
    )

    db = FakeDBForDialog()
    oauth = FakeOAuth()

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    dialog.btn_cancel.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert len(db.inserted_or_updated) == 0
    assert len(db.updated_tokens) == 0


def test_menu_file_has_import_action(qtbot):
    """Menu File di MainWindow memiliki aksi 'Import dari Antigravity…'."""
    win = MainWindow()
    qtbot.addWidget(win)

    file_menu = None
    for action in win.menuBar().actions():
        if "File" in action.text():
            file_menu = action.menu()
            break

    assert file_menu is not None, "Menu File harus ada di menuBar"
    assert hasattr(win, "import_action"), "MainWindow harus memiliki atribut import_action"

    action_found = False
    for act in file_menu.actions():
        if "Import dari Antigravity" in act.text():
            action_found = True
            break
    assert action_found, "Aksi 'Import dari Antigravity…' harus ada di menu File"


def test_menu_action_disabled_when_cli_unavailable(qtbot, monkeypatch):
    """Aksi menu dinonaktifkan dengan tooltip sesuai alasan jika check_cli_availability() False."""
    from src.ui import main_window as mw_mod

    def mock_unavailable():
        return False, "unsupported_os"

    monkeypatch.setattr(mw_mod, "check_cli_availability", mock_unavailable)

    win = MainWindow()
    qtbot.addWidget(win)

    win._update_import_action_state()
    assert win.import_action.isEnabled() is False
    assert win.import_action.toolTip() == REASON_MESSAGES["unsupported_os"]


# ─── Tests Tiket 03: Validasi Token Async ────────────────────────────────────


def test_token_validation_success_shows_valid_badge(qtbot):
    """Token valid menghasilkan badge ✅ Token Valid."""
    keyring = FakeKeyring()
    email = "valid.user@example.com"
    token = "1//rt_valid_test_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    # Validasi berjalan segera setelah dialog dibuka
    assert dialog._validation_worker is not None
    qtbot.waitUntil(lambda: dialog.token_status_badge.text() == "✅ Token Valid", timeout=3000)

    # Tombol Simpan tidak diblokir
    assert dialog.btn_save.isEnabled() is True


def test_token_validation_oauth_error_shows_invalid_badge(qtbot):
    """Token tidak valid (mis. invalid_grant) menampilkan badge ❌ dengan error_code."""
    keyring = FakeKeyring()
    token = "1//rt_revoked_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token("user@example.com"),
        }).encode("utf-8"),
    )

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    oauth.fail_with("invalid_grant", "Token has been expired or revoked.")

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    qtbot.waitUntil(
        lambda: "❌ Token Tidak Valid: invalid_grant" in dialog.token_status_badge.text(),
        timeout=3000,
    )

    # Nilai token tidak boleh bocor ke badge
    assert token not in dialog.token_status_badge.text()
    # Pengguna tetap bisa mengedit dan menyimpan
    assert dialog.btn_save.isEnabled() is True


def test_token_validation_connection_failure_shows_warning_badge(qtbot):
    """Kegagalan koneksi/timeout menampilkan badge ⚠️ oranye."""
    keyring = FakeKeyring()
    token = "1//rt_timeout_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token("user@example.com"),
        }).encode("utf-8"),
    )

    class TimeoutOAuth:
        def exchange_refresh_token(self, rt):
            raise TimeoutError("Connection timed out")

    db = FakeDBForDialog()
    oauth = TimeoutOAuth()

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    qtbot.waitUntil(
        lambda: "⚠️ Validasi gagal (timeout/jaringan)" in dialog.token_status_badge.text(),
        timeout=3000,
    )
    assert dialog.btn_save.isEnabled() is True


def test_token_rotation_updates_refresh_token_field(qtbot):
    """Jika respons OAuth mengembalikan refresh_token baru (rotasi token), form diperbarui otomatis."""
    keyring = FakeKeyring()
    old_token = "1//old_refresh_token"
    new_token = "1//new_rotated_refresh_token_xyz"
    email = "rotated.user@example.com"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": old_token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    # Respons OAuth mengembalikan refresh_token baru
    oauth.respond_for(email, refresh_token=new_token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    # Sebelum validasi selesai, token adalah old_token
    assert dialog.token_input.text() == old_token

    # Tunggu validasi selesai
    qtbot.waitUntil(lambda: dialog.token_status_badge.text() == "✅ Token Valid", timeout=3000)

    # Field refresh token di form harus telah terupdate otomatis dengan new_token
    assert dialog.token_input.text() == new_token

