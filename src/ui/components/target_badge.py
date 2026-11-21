"""Chip Target di ConfigBar: QToolButton berteks dengan menu dropdown."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QMenu, QSizePolicy, QToolButton

from src.targets import (
    ALL_TARGETS,
    create_settings,
    load_active_target,
    normalize_target,
    save_active_target,
    target_label,
)

# Padding kiri-kanan + border dari stylesheet chip.
_CHIP_HORIZONTAL_CHROME = 22
_MIN_CHIP_WIDTH = 96

_BADGE_STYLESHEET = (
    "QToolButton { background-color: rgba(128, 128, 128, 0.12); color: #333;"
    " border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 4px;"
    " padding: 4px 10px; font-weight: bold; font-size: 11px; }"
    "QToolButton::menu-indicator { image: none; }"
)


class TargetBadge(QToolButton):
  """Chip Target dengan menu OpenCode / Antigravity CLI.

  Pilihan disimpan ke QSettings. Widget ini tidak pernah menyentuh file
  OpenCode, keyring, maupun ``~/.gemini``.
  """

  target_changed = pyqtSignal(str)

  def __init__(self, settings=None, parent=None):
    super().__init__(parent)
    self._settings = settings if settings is not None else create_settings()
    self._target = load_active_target(self._settings)
    self._actions: dict[str, QAction] = {}

    self.setObjectName("targetBadge")
    self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    # Ukuran alami = sizeHint (tidak melar), tetapi boleh menyusut saat sempit.
    self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    self.setMinimumWidth(_MIN_CHIP_WIDTH)
    self.setStyleSheet(_BADGE_STYLESHEET)

    self._build_menu()
    self._sync_checked_action()
    self._update_display()

  def resizeEvent(self, event):
    super().resizeEvent(event)
    self._update_display()

  def sizeHint(self) -> QSize:
    """Lebar alami selalu berdasarkan teks penuh, bukan teks yang ter-elide."""
    base = super().sizeHint()
    full_width = (
        self.fontMetrics().horizontalAdvance(self._full_label())
        + _CHIP_HORIZONTAL_CHROME
    )
    return QSize(max(_MIN_CHIP_WIDTH, full_width), base.height())

  # ─── API publik ───

  def get_target(self) -> str:
    return self._target

  def set_target(self, target: object) -> str:
    """Pilih target, simpan, perbarui chip, dan pancarkan sinyal bila berubah."""
    canonical = normalize_target(target)
    changed = canonical != self._target
    self._target = canonical
    self._sync_checked_action()
    self._update_display()
    self.updateGeometry()
    if changed:
      save_active_target(self._settings, canonical)
      self.target_changed.emit(canonical)
    return canonical

  # ─── Internal ───

  def _build_menu(self) -> None:
    menu = QMenu(self)
    group = QActionGroup(menu)
    group.setExclusive(True)

    for target in ALL_TARGETS:
      action = menu.addAction(target_label(target))
      action.setCheckable(True)
      action.setActionGroup(group)
      action.triggered.connect(
          lambda _checked=False, value=target: self.set_target(value)
      )
      self._actions[target] = action

    self.setMenu(menu)

  def _sync_checked_action(self) -> None:
    for target, action in self._actions.items():
      action.setChecked(target == self._target)

  def _full_label(self) -> str:
    return f"🎯 Target: {target_label(self._target)}"

  def _update_display(self) -> None:
    full_text = self._full_label()
    # Lebar teks penuh dihitung independen dari teks yang sedang tampil agar
    # elide tidak berosilasi ketika sizeHint berubah mengikuti teks terpangkas.
    full_width = (
        self.fontMetrics().horizontalAdvance(full_text)
        + _CHIP_HORIZONTAL_CHROME
    )
    if 0 < self.width() < full_width:
      text = self.fontMetrics().elidedText(
          full_text,
          Qt.TextElideMode.ElideRight,
          max(0, self.width() - _CHIP_HORIZONTAL_CHROME),
      )
    else:
      text = full_text
    self.setText(text)
    self.setToolTip(full_text)
