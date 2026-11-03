from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class ConfigBarWidget(QWidget):
  """Komponen status bar atas untuk menampilkan folder Antigravity aktif dan tombol Pengaturan."""

  settings_requested = pyqtSignal()

  def __init__(self, parent=None):
    super().__init__(parent)
    self.init_ui()

  def init_ui(self):
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 4)

    label_folder = QLabel("<b>Folder Aktif:</b>")
    self.txt_folder_path = QLineEdit()
    self.txt_folder_path.setReadOnly(True)
    self.txt_folder_path.setPlaceholderText("Belum ditentukan (Atur di Menu Pengaturan)...")
    self.txt_folder_path.setStyleSheet(
        "QLineEdit { background-color: rgba(128, 128, 128, 0.08); padding: 4px 8px; }"
    )

    self.btn_settings = QPushButton("⚙ Pengaturan...")
    self.btn_settings.setStyleSheet("padding: 4px 14px; font-weight: bold;")
    self.btn_settings.setToolTip("Buka Menu Pengaturan untuk memilih folder dan password enkripsi (Ctrl+,)")
    self.btn_settings.clicked.connect(self.settings_requested.emit)

    layout.addWidget(label_folder)
    layout.addWidget(self.txt_folder_path)
    layout.addWidget(self.btn_settings)

  def get_folder_path(self) -> str:
    return self.txt_folder_path.text().strip()

  def set_folder_path(self, path: str):
    self.txt_folder_path.setText(path)
