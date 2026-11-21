"""Test pemilihan target global dan chip ConfigBar.

Seam yang diuji adalah widget langsung (``ConfigBarWidget``/``TargetBadge``)
dan helper nilai kanonik. Tidak ada test yang menyentuh QSettings pengguna,
file OpenCode pengguna, keyring, atau ``~/.gemini``.
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QScrollArea, QToolButton

from src.targets import (
    TARGET_ANTIGRAVITY_CLI,
    TARGET_LABELS,
    TARGET_OPENCODE,
    load_active_target,
    normalize_target,
    save_active_target,
)
from src.ui.components.config_bar import ConfigBarWidget


def _settings(tmp_path) -> QSettings:
  """QSettings terisolasi dalam file INI sementara."""
  settings = QSettings(
      str(tmp_path / "settings.ini"), QSettings.Format.IniFormat
  )
  settings.clear()
  settings.sync()
  return settings


def _process_events() -> None:
  QApplication.processEvents()


def _action_texts(widget: ConfigBarWidget) -> list[str]:
  return [action.text() for action in widget.target_badge.menu().actions()]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("opencode", TARGET_OPENCODE),
        ("antigravity_cli", TARGET_ANTIGRAVITY_CLI),
        ("", TARGET_OPENCODE),
        (None, TARGET_OPENCODE),
        ("OpenCode", TARGET_OPENCODE),
        ("antigravity", TARGET_OPENCODE),
        ("tidak-dikenal", TARGET_OPENCODE),
    ],
)
def test_target_values_are_canonical(value, expected):
  assert normalize_target(value) == expected


def test_helper_menyimpan_dan_membaca_target_dari_settings(tmp_path):
  settings = _settings(tmp_path)
  assert load_active_target(settings) == TARGET_OPENCODE

  assert save_active_target(settings, TARGET_ANTIGRAVITY_CLI) == TARGET_ANTIGRAVITY_CLI
  assert settings.value("active_target") == TARGET_ANTIGRAVITY_CLI
  assert load_active_target(settings) == TARGET_ANTIGRAVITY_CLI

  settings.setValue("active_target", "nilai-lama-tak-dikenal")
  assert load_active_target(settings) == TARGET_OPENCODE


def test_config_bar_default_target_adalah_opencode(tmp_path, qtbot):
  widget = ConfigBarWidget(settings=_settings(tmp_path))
  qtbot.addWidget(widget)
  widget.resize(900, 60)
  widget.show()
  _process_events()

  assert widget.get_active_target() == TARGET_OPENCODE
  assert isinstance(widget.target_badge, QToolButton)
  assert widget.target_badge.text() == f"🎯 Target: {TARGET_LABELS[TARGET_OPENCODE]}"


def test_memilih_target_mengubah_chip_menyimpan_setting_dan_memancarkan_sinyal(
    tmp_path, qtbot
):
  settings = _settings(tmp_path)
  widget = ConfigBarWidget(settings=settings)
  qtbot.addWidget(widget)
  widget.resize(900, 60)
  widget.show()
  _process_events()

  with qtbot.waitSignal(widget.target_changed) as blocker:
    actions = widget.target_badge.menu().actions()
    actions[_action_texts(widget).index(TARGET_LABELS[TARGET_ANTIGRAVITY_CLI])].trigger()
  _process_events()

  assert blocker.args == [TARGET_ANTIGRAVITY_CLI]
  assert widget.get_active_target() == TARGET_ANTIGRAVITY_CLI
  assert widget.target_badge.text() == (
      f"🎯 Target: {TARGET_LABELS[TARGET_ANTIGRAVITY_CLI]}"
  )
  assert settings.value("active_target") == TARGET_ANTIGRAVITY_CLI


def test_target_tersimpan_setelah_reopen(tmp_path, qtbot):
  first_settings = _settings(tmp_path)
  first = ConfigBarWidget(settings=first_settings)
  qtbot.addWidget(first)
  first.target_badge.set_target(TARGET_ANTIGRAVITY_CLI)
  first_settings.sync()

  reopened_settings = QSettings(
      str(tmp_path / "settings.ini"), QSettings.Format.IniFormat
  )
  reopened = ConfigBarWidget(settings=reopened_settings)
  qtbot.addWidget(reopened)

  assert reopened.get_active_target() == TARGET_ANTIGRAVITY_CLI
  assert reopened.target_badge.text() == (
      f"🎯 Target: {TARGET_LABELS[TARGET_ANTIGRAVITY_CLI]}"
  )


def test_urutan_dan_layout_config_bar(tmp_path, qtbot):
  widget = ConfigBarWidget(settings=_settings(tmp_path))
  qtbot.addWidget(widget)
  layout = widget.layout()

  widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
  assert widgets == [
      widget.lbl_db_status,
      widget.lbl_crypto_status,
      widget.target_badge,
      widget.lbl_folder,
      widget.txt_folder_path,
  ]
  assert layout.stretch(4) == 1
  assert widget.txt_folder_path.minimumWidth() == 120
  assert layout.stretch(2) == 0
  assert (
      widget.target_badge.sizePolicy().horizontalPolicy().name == "Maximum"
  )


def test_config_bar_satu_baris_dan_folder_terlihat_pada_900px(tmp_path, qtbot):
  widget = ConfigBarWidget(settings=_settings(tmp_path))
  qtbot.addWidget(widget)
  widget.resize(900, 60)
  widget.show()
  _process_events()

  for child in (
      widget.lbl_db_status,
      widget.lbl_crypto_status,
      widget.target_badge,
      widget.lbl_folder,
      widget.txt_folder_path,
  ):
    assert child.isVisible()
    assert child.x() >= 0
    assert child.x() + child.width() <= widget.width() + 1

  assert widget.txt_folder_path.width() >= 120
  assert widget.findChildren(QScrollArea) == []


def test_teks_chip_dielide_pada_lebar_sempit_dan_tooltip_tetap_penuh(
    tmp_path, qtbot
):
  widget = ConfigBarWidget(settings=_settings(tmp_path))
  qtbot.addWidget(widget)
  widget.target_badge.set_target(TARGET_ANTIGRAVITY_CLI)
  full_text = f"🎯 Target: {TARGET_LABELS[TARGET_ANTIGRAVITY_CLI]}"

  widget.resize(620, 60)
  widget.show()
  _process_events()

  assert widget.target_badge.toolTip() == full_text
  assert widget.target_badge.text() != full_text
  assert widget.target_badge.text().endswith("…")


def test_mengganti_target_tidak_menyentuh_kredensial(
    tmp_path, qtbot, fake_root, fake_keyring
):
  opencode_file = fake_root.opencode_accounts_file
  opencode_file.parent.mkdir(parents=True, exist_ok=True)
  opencode_file.write_text('{"version": 2, "accounts": [{"email": "lama@x"}]}\n')
  oauth_file = fake_root.gemini_dir / "oauth_creds.json"
  fake_root.gemini_dir.mkdir(parents=True, exist_ok=True)
  oauth_file.write_text('{"refresh_token": "rahasia"}\n')
  fake_keyring.write("gemini", "antigravity", b'{"refresh_token": "rahasia"}')

  before_opencode = opencode_file.read_bytes()
  before_oauth = oauth_file.read_bytes()
  before_keyring = fake_keyring.items
  before_writes = len(fake_keyring.writes)
  before_opencode_stat = os.stat(opencode_file)
  before_oauth_stat = os.stat(oauth_file)

  widget = ConfigBarWidget(settings=_settings(tmp_path))
  qtbot.addWidget(widget)
  widget.target_badge.set_target(TARGET_ANTIGRAVITY_CLI)

  assert opencode_file.read_bytes() == before_opencode
  assert oauth_file.read_bytes() == before_oauth
  assert fake_keyring.items == before_keyring
  assert len(fake_keyring.writes) == before_writes
  assert os.stat(opencode_file).st_mtime_ns == before_opencode_stat.st_mtime_ns
  assert os.stat(oauth_file).st_mtime_ns == before_oauth_stat.st_mtime_ns
