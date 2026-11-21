"""Test untuk tiket 06: Availability Antigravity CLI dan grup Pengaturan Integrasi.

Mencakup:
- Availability selalu True untuk OpenCode
- Availability CLI hanya True bila semua kondisi terpenuhi (Linux, D-Bus, keyring, bukan root)
- Alasan tidak tersedia dikembalikan sebagai kode + teks
- NullKeyringPort selalu melaporkan tidak tersedia
- TargetBadge: menu CLI disabled dengan tooltip alasan, recheck per open
- SettingsDialog: grup Integrasi memuat dan menyimpan auto_kill_agy dan write_gemini_files
  dengan default yang benar
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from src.integrations.antigravity.factory import (
    NullKeyringPort,
    ProductionEnvironmentPort,
    check_cli_availability,
)
from src.integrations.antigravity.ports import TargetCondition, TargetStatus
from src.integrations.antigravity.service import AntigravityFacade
from src.targets import TARGET_ANTIGRAVITY_CLI, TARGET_OPENCODE
from src.ui.components.settings_dialog import SettingsDialog
from src.ui.components.target_badge import TargetBadge, _UNAVAIL_REASON_TEXT

from tests.fakes import FakeClock, FakeKeyring, FakeOAuth, FakeProcTable


# ─── Fake port helpers ────────────────────────────────────────────────────────


class FakeAccountStorage:
    def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
        return {"id": account_id, "email": f"{account_id}@example.com"}

    def mark_applied(self, account_id: str, target: str, applied_at: Optional[int] = None) -> bool:
        return True

    def update_refresh_token(self, account_id: str, new_refresh_token: str, password: str = "") -> bool:
        return True

    def account_exists(self, email: str) -> bool:
        return False


class FakeOpenCodeFile:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.written_data = None

    def read_accounts_data(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        return self.data, self.error

    def write_accounts_data(self, data: Dict[str, Any]) -> None:
        self.written_data = data


class FakeGeminiFiles:
    def read_oauth_creds(self) -> Optional[Dict]:
        return None

    def write_oauth_creds(self, creds: Dict) -> None:
        pass

    def read_google_accounts(self) -> Optional[Dict]:
        return None

    def write_google_accounts(self, accounts: Dict) -> None:
        pass


class FakeProcessManager:
    def detect_sessions(self):
        return []

    def terminate_sessions(self, sessions, poll_timeout: float = 5.0) -> bool:
        return True


class FakeEnvironment:
    def __init__(self, *, is_linux=True, is_root=False, is_dbus=True, is_locked=False):
        self._linux = is_linux
        self._root = is_root
        self._dbus = is_dbus
        self._locked = is_locked

    def is_linux(self) -> bool:
        return self._linux

    def is_root(self) -> bool:
        return self._root

    def is_dbus_available(self) -> bool:
        return self._dbus

    def is_keyring_locked(self) -> bool:
        return self._locked


def _make_facade(env: FakeEnvironment) -> AntigravityFacade:
    return AntigravityFacade(
        account_storage=FakeAccountStorage(),
        keyring=FakeKeyring(),
        gemini_files=FakeGeminiFiles(),
        opencode_file=FakeOpenCodeFile(
            data={"accounts": [{"email": "test@example.com"}], "activeIndex": 0}
        ),
        oauth=FakeOAuth(),
        process_manager=FakeProcessManager(),
        environment=env,
        clock=FakeClock(),
    )


# ─── Tests: Availability OpenCode selalu True ─────────────────────────────────


def test_opencode_always_available_on_linux():
    """Availability OpenCode tidak tergantung D-Bus maupun keyring."""
    env = FakeEnvironment(is_linux=True, is_dbus=False, is_locked=True)
    facade = _make_facade(env)
    status = facade.read_status()
    # OpenCode tidak pernah UNAVAILABLE; bisa jadi NONE, ACTIVE, INVALID_FILE, dsb.
    assert status.opencode.condition != TargetCondition.UNAVAILABLE


def test_opencode_always_available_on_non_linux():
    """OpenCode harus tersedia bahkan di OS non-Linux."""
    env = FakeEnvironment(is_linux=False)
    facade = _make_facade(env)
    status = facade.read_status()
    assert status.opencode.condition != TargetCondition.UNAVAILABLE


# ─── Tests: Availability CLI dengan semua kondisi ─────────────────────────────


def test_cli_unavailable_unsupported_os():
    """CLI tidak tersedia di OS non-Linux, alasan 'unsupported_os'."""
    env = FakeEnvironment(is_linux=False)
    facade = _make_facade(env)
    status = facade.read_status()
    assert status.antigravity_cli.condition == TargetCondition.UNAVAILABLE
    assert status.antigravity_cli.unavailable_reason == "unsupported_os"


def test_cli_unavailable_root():
    """CLI tidak tersedia saat root, alasan 'root'."""
    env = FakeEnvironment(is_linux=True, is_root=True, is_dbus=True, is_locked=False)
    facade = _make_facade(env)
    status = facade.read_status()
    assert status.antigravity_cli.condition == TargetCondition.UNAVAILABLE
    assert status.antigravity_cli.unavailable_reason == "root"


def test_cli_unavailable_no_dbus():
    """CLI tidak tersedia tanpa D-Bus, alasan 'no_dbus'."""
    env = FakeEnvironment(is_linux=True, is_root=False, is_dbus=False)
    facade = _make_facade(env)
    status = facade.read_status()
    assert status.antigravity_cli.condition == TargetCondition.UNAVAILABLE
    assert status.antigravity_cli.unavailable_reason == "no_dbus"


def test_cli_locked_keyring():
    """CLI berstatus LOCKED saat keyring terkunci, alasan 'keyring_locked'."""
    env = FakeEnvironment(is_linux=True, is_root=False, is_dbus=True, is_locked=True)
    facade = _make_facade(env)
    status = facade.read_status()
    assert status.antigravity_cli.condition == TargetCondition.LOCKED
    assert status.antigravity_cli.unavailable_reason == "keyring_locked"


def test_cli_available_all_conditions_met():
    """CLI berstatus NONE (tersedia, belum login) bila semua kondisi terpenuhi."""
    env = FakeEnvironment(is_linux=True, is_root=False, is_dbus=True, is_locked=False)
    facade = _make_facade(env)
    status = facade.read_status()
    # Harus bukan UNAVAILABLE maupun LOCKED
    assert status.antigravity_cli.condition not in (
        TargetCondition.UNAVAILABLE,
        TargetCondition.LOCKED,
        TargetCondition.ERROR,
    )


def test_read_status_never_raises():
    """read_status tidak pernah melempar exception ke pemanggil."""
    for env in [
        FakeEnvironment(is_linux=False),
        FakeEnvironment(is_linux=True, is_root=True),
        FakeEnvironment(is_linux=True, is_dbus=False),
        FakeEnvironment(is_linux=True, is_locked=True),
        FakeEnvironment(is_linux=True),
    ]:
        facade = _make_facade(env)
        try:
            facade.read_status()
        except Exception as exc:
            pytest.fail(f"read_status melempar exception: {exc}")


# ─── Tests: NullKeyringPort ───────────────────────────────────────────────────


def test_null_keyring_read_returns_none():
    """NullKeyringPort.read() selalu mengembalikan None."""
    kp = NullKeyringPort()
    assert kp.read("any_service", "any_user") is None


def test_null_keyring_write_raises():
    """NullKeyringPort.write() melempar RuntimeError."""
    kp = NullKeyringPort()
    with pytest.raises(RuntimeError):
        kp.write("service", "user", b"data")


def test_null_keyring_delete_does_not_raise():
    """NullKeyringPort.delete() tidak melempar exception."""
    kp = NullKeyringPort()
    kp.delete("service", "user")  # harus tidak melempar apa-apa


# ─── Tests: check_cli_availability() ─────────────────────────────────────────


def test_check_cli_availability_unsupported_os():
    """check_cli_availability mengembalikan (False, 'unsupported_os') di non-Linux."""
    with patch(
        "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_linux",
        return_value=False,
    ):
        available, reason = check_cli_availability()
    assert available is False
    assert reason == "unsupported_os"


def test_check_cli_availability_root():
    """check_cli_availability mengembalikan (False, 'root') saat root."""
    with (
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_linux",
            return_value=True,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_root",
            return_value=True,
        ),
    ):
        available, reason = check_cli_availability()
    assert available is False
    assert reason == "root"


def test_check_cli_availability_no_dbus():
    """check_cli_availability mengembalikan (False, 'no_dbus') tanpa D-Bus."""
    with (
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_linux",
            return_value=True,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_root",
            return_value=False,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_dbus_available",
            return_value=False,
        ),
    ):
        available, reason = check_cli_availability()
    assert available is False
    assert reason == "no_dbus"


def test_check_cli_availability_keyring_locked():
    """check_cli_availability mengembalikan (False, 'keyring_locked') saat keyring terkunci."""
    with (
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_linux",
            return_value=True,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_root",
            return_value=False,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_dbus_available",
            return_value=True,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_keyring_locked",
            return_value=True,
        ),
    ):
        available, reason = check_cli_availability()
    assert available is False
    assert reason == "keyring_locked"


def test_check_cli_availability_all_ok():
    """check_cli_availability mengembalikan (True, '') bila semua kondisi terpenuhi."""
    with (
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_linux",
            return_value=True,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_root",
            return_value=False,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_dbus_available",
            return_value=True,
        ),
        patch(
            "src.integrations.antigravity.factory.ProductionEnvironmentPort.is_keyring_locked",
            return_value=False,
        ),
    ):
        available, reason = check_cli_availability()
    assert available is True
    assert reason == ""


# ─── Tests: TargetBadge menu disabled saat CLI tidak tersedia ────────────────


def _make_badge_with_unavail(reason: str) -> TargetBadge:
    """Buat TargetBadge dengan CLI availability yang sudah dimock."""
    settings = QSettings()
    settings.clear()
    badge = TargetBadge(settings=settings)
    # Simulasikan recheck availability dengan inject langsung
    badge._apply_cli_availability(reason)
    return badge


def test_target_badge_cli_disabled_unsupported_os(qtbot):
    """Item CLI di menu harus disabled saat unsupported_os."""
    badge = _make_badge_with_unavail("unsupported_os")
    qtbot.addWidget(badge)
    action = badge._actions.get(TARGET_ANTIGRAVITY_CLI)
    assert action is not None
    assert not action.isEnabled()


def test_target_badge_cli_tooltip_contains_reason(qtbot):
    """Tooltip item CLI harus memuat teks alasan ketidaktersediaan."""
    for reason in ("unsupported_os", "no_dbus", "keyring_locked", "root", "dbus_error"):
        badge = _make_badge_with_unavail(reason)
        qtbot.addWidget(badge)
        action = badge._actions.get(TARGET_ANTIGRAVITY_CLI)
        assert action is not None
        tooltip = action.toolTip()
        # Tooltip harus memuat teks alasan (dari _UNAVAIL_REASON_TEXT atau kode raw)
        reason_text = _UNAVAIL_REASON_TEXT.get(reason, reason)
        assert reason_text in tooltip or reason in tooltip, (
            f"Tooltip untuk {reason!r} tidak memuat teks alasan. Tooltip: {tooltip!r}"
        )


def test_target_badge_cli_enabled_when_available(qtbot):
    """Item CLI harus enabled saat availability = None (tersedia)."""
    settings = QSettings()
    settings.clear()
    badge = TargetBadge(settings=settings)
    qtbot.addWidget(badge)
    badge._apply_cli_availability(None)
    action = badge._actions.get(TARGET_ANTIGRAVITY_CLI)
    assert action is not None
    assert action.isEnabled()


def test_target_badge_opencode_always_enabled(qtbot):
    """Item OpenCode harus selalu enabled tanpa kondisi apapun."""
    for reason in (None, "unsupported_os", "no_dbus"):
        settings = QSettings()
        settings.clear()
        badge = TargetBadge(settings=settings)
        qtbot.addWidget(badge)
        badge._apply_cli_availability(reason)
        action = badge._actions.get(TARGET_OPENCODE)
        assert action is not None
        assert action.isEnabled(), f"OpenCode harus enabled (reason={reason!r})"


# ─── Tests: TargetBadge recheck di aboutToShow ───────────────────────────────


def test_target_badge_menu_about_to_show_rechecks(qtbot):
    """Sinyal aboutToShow pada menu harus memanggil ulang _apply_cli_availability."""
    with patch(
        "src.ui.components.target_badge._get_cli_unavailable_reason",
        return_value="no_dbus",
    ) as mock_check:
        settings = QSettings()
        settings.clear()
        badge = TargetBadge(settings=settings)
        qtbot.addWidget(badge)
        # Simulasikan menu dibuka
        badge.menu().aboutToShow.emit()
        assert mock_check.called
        action = badge._actions.get(TARGET_ANTIGRAVITY_CLI)
        assert not action.isEnabled()


# ─── Tests: SettingsDialog grup Integrasi ────────────────────────────────────


def test_settings_dialog_integrasi_default_values(qtbot):
    """Default: auto_kill_agy=False, write_gemini_files=True."""
    settings = QSettings()
    settings.clear()
    # Hapus key agar benar-benar default
    settings.remove("auto_kill_agy")
    settings.remove("write_gemini_files")

    with patch(
        "src.ui.components.settings_dialog.QSettings",
        return_value=settings,
    ):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

    assert not dialog.chk_auto_kill_agy.isChecked(), (
        "auto_kill_agy default harus mati (False)"
    )
    assert dialog.chk_write_gemini_files.isChecked(), (
        "write_gemini_files default harus aktif (True)"
    )


def test_settings_dialog_integrasi_load_saved_values(qtbot):
    """SettingsDialog harus membaca nilai yang sudah tersimpan di QSettings."""
    settings = QSettings()
    settings.clear()
    settings.setValue("auto_kill_agy", True)
    settings.setValue("write_gemini_files", False)

    with patch(
        "src.ui.components.settings_dialog.QSettings",
        return_value=settings,
    ):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

    assert dialog.chk_auto_kill_agy.isChecked()
    assert not dialog.chk_write_gemini_files.isChecked()


def test_settings_dialog_integrasi_save(qtbot):
    """Mengklik Simpan harus menulis nilai integrasi ke QSettings."""
    settings = QSettings()
    settings.clear()
    settings.setValue("auto_kill_agy", False)
    settings.setValue("write_gemini_files", True)

    with patch(
        "src.ui.components.settings_dialog.QSettings",
        return_value=settings,
    ):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

    # Ubah nilai
    dialog.chk_auto_kill_agy.setChecked(True)
    dialog.chk_write_gemini_files.setChecked(False)

    # Panggil _save_settings langsung (hindari QMessageBox)
    with patch.object(dialog, "accept"), patch(
        "src.ui.components.settings_dialog.QMessageBox.information"
    ):
        dialog._save_settings()

    assert settings.value("auto_kill_agy") in (True, "true", "True")
    assert settings.value("write_gemini_files") in (False, "false", "False")


def test_settings_dialog_no_import_button(qtbot):
    """Tidak boleh ada tombol impor file lama pada v1.0."""
    settings = QSettings()
    settings.clear()

    with patch(
        "src.ui.components.settings_dialog.QSettings",
        return_value=settings,
    ):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)

    # Pastikan tidak ada widget dengan teks yang mengandung "impor" (case-insensitive)
    from PyQt6.QtWidgets import QPushButton
    buttons = dialog.findChildren(QPushButton)
    import_buttons = [
        b for b in buttons
        if "impor" in b.text().lower() or "import" in b.text().lower()
    ]
    assert len(import_buttons) == 0, (
        f"Ditemukan tombol impor yang seharusnya tidak ada pada v1.0: "
        f"{[b.text() for b in import_buttons]}"
    )
