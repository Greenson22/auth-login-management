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

    def __init__(
        self,
        categories: Optional[List[str]] = None,
        existing_accounts: Optional[List[tuple]] = None,
    ):
        self._categories = categories or ["Pribadi", "Kerja", "Testing"]
        self._existing_accounts = existing_accounts or []
        self.inserted_or_updated: List[Dict[str, Any]] = []
        self.updated_tokens: List[Dict[str, Any]] = []
        self.updated_quotas: List[Dict[str, Any]] = []

    def fetch_categories(self) -> List[str]:
        return list(self._categories)

    def fetch_accounts_summary(self) -> List[tuple]:
        return list(self._existing_accounts)

    def insert_or_update_json(
        self,
        json_str: str,
        encrypt: bool = False,
        password: str = "",
        category: str = "",
    ) -> bool:
        self.inserted_or_updated.append({
            "json_str": json_str,
            "encrypt": encrypt,
            "password": password,
            "category": category,
        })
        return True

    def update_refresh_token(self, account_id: str, new_token: str, password: str = "") -> bool:
        self.updated_tokens.append({
            "account_id": account_id,
            "new_token": new_token,
            "password": password,
        })
        return True

    def update_account_quotas(self, account_id: str, quota_data: dict, password: str = "") -> bool:
        self.updated_quotas.append({
            "account_id": account_id,
            "quota_data": quota_data,
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


# ─── Tests Tiket 04: Fetch Kuota Async ───────────────────────────────────────


def test_quota_fetch_success_populates_quota_labels(qtbot, monkeypatch):
    """Setelah validasi token berhasil, kuota diambil di background dan ditampilkan di form."""
    import src.ui.components.import_dialog as dialog_mod

    keyring = FakeKeyring()
    email = "quota.user@example.com"
    token = "1//rt_quota_test"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    fake_quota_data = {
        "gemini-flash": {
            "remainingFraction": 0.85,
            "resetTime": "2026-11-24T12:00:00Z",
            "modelCount": 11,
        },
        "claude": {
            "remainingFraction": 0.50,
            "resetTime": "2026-11-24T12:00:00Z",
            "modelCount": 2,
        },
    }

    def mock_fetch_quota(refresh_token, project_id="aicode-consumers"):
        return fake_quota_data

    monkeypatch.setattr(dialog_mod, "fetch_account_quota", mock_fetch_quota)

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    # Tunggu validasi selesai
    qtbot.waitUntil(lambda: dialog.token_status_badge.text() == "✅ Token Valid", timeout=3000)

    # Kuota worker harus berjalan setelah token valid
    assert dialog._quota_worker is not None
    qtbot.waitUntil(lambda: dialog.cached_quota is not None, timeout=3000)

    # Verifikasi kuota Gemini terisi (persentase 85%)
    assert "85%" in dialog.lbl_quota_gemini.text()
    # Verifikasi kuota Claude terisi (persentase 50%)
    assert "50%" in dialog.lbl_quota_claude.text()
    # Note status kuota kosong setelah sukses
    assert dialog.lbl_quota_status.text() == ""
    # Tombol simpan tetap aktif
    assert dialog.btn_save.isEnabled() is True


def test_quota_fetch_skipped_when_token_invalid(qtbot, monkeypatch):
    """Jika validasi token gagal, fetch kuota dilewati dan kolom kuota tetap kosong."""
    import src.ui.components.import_dialog as dialog_mod

    keyring = FakeKeyring()
    token = "1//rt_invalid_for_quota"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token("user@example.com"),
        }).encode("utf-8"),
    )

    fetch_called = []

    def mock_fetch_quota(refresh_token, project_id="aicode-consumers"):
        fetch_called.append(refresh_token)
        return {}

    monkeypatch.setattr(dialog_mod, "fetch_account_quota", mock_fetch_quota)

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    oauth.fail_with("invalid_grant")

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: "❌" in dialog.token_status_badge.text(), timeout=3000)

    # Fetch kuota tidak pernah dipanggil
    assert len(fetch_called) == 0
    assert dialog._quota_worker is None
    assert dialog.lbl_quota_gemini.text() == "-"
    assert dialog.lbl_quota_claude.text() == "-"
    assert dialog.btn_save.isEnabled() is True


def test_quota_fetch_failure_shows_note_and_keeps_save_enabled(qtbot, monkeypatch):
    """Jika fetch kuota gagal (error jaringan/API), tampilkan note kecil dan Simpan tetap aktif."""
    import src.ui.components.import_dialog as dialog_mod

    keyring = FakeKeyring()
    email = "quota.fail@example.com"
    token = "1//rt_quota_fail"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    def mock_fetch_quota_fail(refresh_token, project_id="aicode-consumers"):
        raise TimeoutError("API Gateway Timeout")

    monkeypatch.setattr(dialog_mod, "fetch_account_quota", mock_fetch_quota_fail)

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    # Tunggu validasi selesai dan fetch kuota gagal
    qtbot.waitUntil(lambda: dialog.token_status_badge.text() == "✅ Token Valid", timeout=3000)
    qtbot.waitUntil(
        lambda: dialog.lbl_quota_status.text() == "Kuota tidak berhasil diambil",
        timeout=3000,
    )

    assert dialog.cached_quota is None
    assert dialog.lbl_quota_gemini.text() == "-"
    assert dialog.lbl_quota_claude.text() == "-"
    # Tombol simpan tidak terpengaruh
    assert dialog.btn_save.isEnabled() is True


# ─── Tests Tiket 05: Duplikat Email & Simpan ke DB ───────────────────────────


def test_save_new_email_inserts_into_db(qtbot):
    """Email baru: form tampil tanpa banner, tombol Simpan aktif, data tersimpan ke DB."""
    keyring = FakeKeyring()
    email = "newbie@example.com"
    token = "1//rt_newbie_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
            "project_id": "proj-new",
        }).encode("utf-8"),
    )

    db = FakeDBForDialog(existing_accounts=[("acc_other", "other@example.com")])
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db, password="my_session_pwd")
    qtbot.addWidget(dialog)

    # Banner duplikat tidak muncul
    assert not hasattr(dialog, "banner_label")
    assert dialog.btn_save.isEnabled() is True

    # Klik Simpan
    dialog.btn_save.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(db.inserted_or_updated) == 1
    assert len(db.updated_tokens) == 0

    saved = db.inserted_or_updated[0]
    assert saved["encrypt"] is True
    assert saved["password"] == "my_session_pwd"
    data = json.loads(saved["json_str"])
    acc = data["accounts"][0]
    assert acc["email"] == email
    assert acc["refreshToken"] == token
    assert acc["projectId"] == "proj-new"


def test_duplicate_email_shows_banner_and_disables_save_until_selected(qtbot):
    """Email duplikat: banner kuning tampil, tombol Simpan nonaktif sampai tindakan dipilih."""
    keyring = FakeKeyring()
    email = "duplicate@example.com"
    token = "1//rt_dup_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    db = FakeDBForDialog(existing_accounts=[("acc_existing_123", "DUPLICATE@example.com")])
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    # Banner tampil
    assert hasattr(dialog, "banner_label")
    assert "acc_existing_123" in dialog.banner_label.text()

    # Tombol Simpan dinonaktifkan
    assert dialog.btn_save.isEnabled() is False

    # Pilih radio Perbarui Token
    dialog.radio_update.click()
    assert dialog.btn_save.isEnabled() is True


def test_duplicate_email_update_token_action(qtbot, monkeypatch):
    """Email duplikat + pilih Perbarui Token: panggil update_refresh_token & update_account_quotas."""
    import src.ui.components.import_dialog as dialog_mod

    keyring = FakeKeyring()
    email = "existing.user@example.com"
    token = "1//rt_latest_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    fake_quota = {"gemini-flash": {"remainingFraction": 0.9, "resetTime": "2026-11-25T00:00:00Z"}}
    monkeypatch.setattr(dialog_mod, "fetch_account_quota", lambda rt, project_id="aicode-consumers": fake_quota)

    db = FakeDBForDialog(existing_accounts=[("acc_exist_99", email)])
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db, password="enc_pass_123")
    qtbot.addWidget(dialog)

    # Tunggu validasi & fetch kuota selesai
    qtbot.waitUntil(lambda: dialog.cached_quota is not None, timeout=3000)

    # Pilih Perbarui Token
    dialog.radio_update.click()
    dialog.btn_save.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    # DB insert tidak dipanggil
    assert len(db.inserted_or_updated) == 0
    # update_refresh_token dipanggil dengan ID akun lama
    assert len(db.updated_tokens) == 1
    assert db.updated_tokens[0]["account_id"] == "acc_exist_99"
    assert db.updated_tokens[0]["new_token"] == token
    assert db.updated_tokens[0]["password"] == "enc_pass_123"

    # update_account_quotas dipanggil
    assert len(db.updated_quotas) == 1
    assert db.updated_quotas[0]["account_id"] == "acc_exist_99"
    assert db.updated_quotas[0]["quota_data"] == fake_quota


def test_duplicate_email_add_as_new_entry_action(qtbot):
    """Email duplikat + pilih Tambah Baru: panggil insert_or_update_json dengan ID baru."""
    keyring = FakeKeyring()
    email = "dup.new@example.com"
    token = "1//rt_new_entry_token"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    db = FakeDBForDialog(existing_accounts=[("acc_old_77", email)])
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    # Pilih Tambah sebagai Entri Baru
    dialog.radio_new_entry.click()
    dialog.btn_save.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(db.updated_tokens) == 0
    assert len(db.inserted_or_updated) == 1

    saved = db.inserted_or_updated[0]
    data = json.loads(saved["json_str"])
    acc = data["accounts"][0]
    assert acc["id"] != "acc_old_77"
    assert acc["email"] == email


def test_save_with_invalid_token_still_allowed(qtbot):
    """Token tidak valid (invalid_grant) tetap boleh disimpan oleh pengguna."""
    keyring = FakeKeyring()
    email = "invalid.token@example.com"
    token = "1//rt_revoked_still_save"

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
    oauth.fail_with("invalid_grant")

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: "❌" in dialog.token_status_badge.text(), timeout=3000)

    # Klik Simpan
    dialog.btn_save.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(db.inserted_or_updated) == 1
    saved = db.inserted_or_updated[0]
    data = json.loads(saved["json_str"])
    assert data["accounts"][0]["refreshToken"] == token


def test_save_when_quota_failed_still_succeeds(qtbot, monkeypatch):
    """Kuota gagal fetch: akun tetap tersimpan tanpa kolom kuota."""
    import src.ui.components.import_dialog as dialog_mod

    keyring = FakeKeyring()
    email = "no.quota@example.com"
    token = "1//rt_no_quota"

    keyring.write(
        KEYRING_SERVICE,
        KEYRING_USERNAME,
        json.dumps({
            "refresh_token": token,
            "id_token": make_id_token(email),
        }).encode("utf-8"),
    )

    monkeypatch.setattr(dialog_mod, "fetch_account_quota", lambda rt, project_id="aicode-consumers": (_ for _ in ()).throw(TimeoutError("Timeout")))

    db = FakeDBForDialog()
    oauth = FakeOAuth()
    oauth.respond_for(email, refresh_token=token)

    dialog = ImportDialog(keyring=keyring, oauth=oauth, db=db)
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: dialog.lbl_quota_status.text() == "Kuota tidak berhasil diambil", timeout=3000)

    dialog.btn_save.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(db.inserted_or_updated) == 1
    data = json.loads(db.inserted_or_updated[0]["json_str"])
    assert "cachedQuota" not in data["accounts"][0]



