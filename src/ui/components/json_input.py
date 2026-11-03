from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


class JsonInputWidget(QWidget):
  """Komponen input teks JSON dan tombol aksi simpan/bersihkan."""

  json_submitted = pyqtSignal(str)

  def __init__(self, parent=None):
    super().__init__(parent)
    self.init_ui()

  def init_ui(self):
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 5, 0, 0)

    label = QLabel("<b>Paste JSON Akun di Sini:</b>")
    self.txt_json = QTextEdit()
    self.txt_json.setPlaceholderText("Paste teks JSON...")

    btn_layout = QHBoxLayout()
    self.btn_save = QPushButton("Simpan ke Database SQLite")
    self.btn_save.setStyleSheet(
        "background-color: #2b5c8f; color: white; font-weight: bold; padding:"
        " 6px;"
    )
    self.btn_save.clicked.connect(self._on_save_clicked)

    self.btn_clear = QPushButton("Bersihkan Input")
    self.btn_clear.clicked.connect(self.clear_input)

    btn_layout.addWidget(self.btn_save)
    btn_layout.addWidget(self.btn_clear)

    layout.addWidget(label)
    layout.addWidget(self.txt_json)
    layout.addLayout(btn_layout)

  def _on_save_clicked(self):
    raw_text = self.txt_json.toPlainText().strip()
    self.json_submitted.emit(raw_text)

  def clear_input(self):
    self.txt_json.clear()
