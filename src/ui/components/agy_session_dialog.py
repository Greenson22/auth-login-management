"""Dialog konfirmasi dan progres untuk pengelolaan proses sesi agy."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.integrations.antigravity.process import AgySession


class AgyConfirmDialog(QDialog):
  """Dialog konfirmasi penghentian sesi agy (tiket 07).

  - Ukuran tetap sekitar 480x320.
  - Memuat PID, state, dan perintah dalam daftar yang bisa di-scroll.
  - Tombol Batal menjadi fokus default.
  - Tombol 'Hentikan Sesi' ditandai destruktif (#d93025).
  - Checkbox 'Jangan tanya lagi' menulis auto_kill_agy=True.
  """

  def __init__(
      self,
      sessions: List[AgySession],
      parent=None,
      *,
      settings=None,
  ):
    super().__init__(parent)
    self.sessions = sessions
    self._settings = settings
    self.setWindowTitle("Sesi agy Masih Berjalan")
    self.setFixedSize(480, 320)
    self.setWindowModality(Qt.WindowModality.ApplicationModal)

    self._init_ui()

  def _init_ui(self):
    layout = QVBoxLayout(self)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    # Label instruksi / peringatan
    lbl_desc = QLabel(
        "Aplikasi mendeteksi sesi <b>agy</b> yang masih berjalan. Untuk mencegah token lama menimpa kembali perubahan, sesi ini harus dihentikan terlebih dahulu:"
    )
    lbl_desc.setWordWrap(True)
    layout.addWidget(lbl_desc)

    # Tabel daftar PID, State, Command (scrollable)
    self.table = QTableWidget(len(self.sessions), 3)
    self.table.setHorizontalHeaderLabels(["PID", "Status", "Perintah"])
    self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    for row, s in enumerate(self.sessions):
      item_pid = QTableWidgetItem(str(s.pid))
      item_state = QTableWidgetItem(s.state_label)
      item_cmd = QTableWidgetItem(s.command_str)
      item_cmd.setToolTip(s.command_str)

      self.table.setItem(row, 0, item_pid)
      self.table.setItem(row, 1, item_state)
      self.table.setItem(row, 2, item_cmd)

    layout.addWidget(self.table)

    # Checkbox 'Jangan tanya lagi'
    self.chk_dont_ask = QCheckBox("Jangan tanya lagi (selalu hentikan otomatis)")
    layout.addWidget(self.chk_dont_ask)

    # Tombol aksi: Batal (default focus) dan Hentikan Sesi (destruktif)
    btn_layout = QHBoxLayout()
    btn_layout.addStretch()

    self.btn_cancel = QPushButton("Batal")
    self.btn_cancel.setDefault(True)
    self.btn_cancel.clicked.connect(self.reject)

    self.btn_kill = QPushButton("Hentikan Sesi")
    self.btn_kill.setStyleSheet(
        "QPushButton { background-color: #d93025; color: white; font-weight: bold; border-radius: 4px; padding: 6px 12px; }"
        "QPushButton:hover { background-color: #b3261e; }"
    )
    self.btn_kill.clicked.connect(self._on_confirm_kill)

    btn_layout.addWidget(self.btn_cancel)
    btn_layout.addWidget(self.btn_kill)
    layout.addLayout(btn_layout)

    # Set default focus explicitly to Cancel button
    self.btn_cancel.setFocus()

  def _on_confirm_kill(self):
    if self.chk_dont_ask.isChecked() and self._settings is not None:
      self._settings.setValue("auto_kill_agy", True)
    self.accept()


class KillWorkerThread(QThread):
  """Worker thread untuk eksekusi penghentian proses agy secara non-blocking."""

  progress = pyqtSignal(str)
  finished_result = pyqtSignal(bool, list, str)

  def __init__(self, process_manager, sessions: List[AgySession]):
    super().__init__()
    self.process_manager = process_manager
    self.sessions = sessions
    self._is_cancelled = False

  def cancel(self):
    self._is_cancelled = True

  def run(self):
    success, failed_pids, err_msg = self.process_manager.terminate_sessions(
        self.sessions,
        on_progress=lambda msg: self.progress.emit(msg),
        is_cancelled=lambda: self._is_cancelled,
    )
    self.finished_result.emit(success, failed_pids, err_msg)
