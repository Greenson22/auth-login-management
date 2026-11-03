from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class ConfigBarWidget(QWidget):
  """Komponen bagian atas untuk memilih dan menampilkan folder Antigravity serta membuka pengaturan."""

  folder_changed = pyqtSignal(str)
  settings_requested = pyqtSignal()

  def __init__(self, parent=None):
    super().__init__(parent)
    self.init_ui()

  def init_ui(self):
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)

    label_folder = QLabel("<b>Folder Antigravity:</b>")
    self.txt_folder_path = QLineEdit()
    self.txt_folder_path.setReadOnly(True)
    self.txt_folder_path.setPlaceholderText("Belum ada folder yang dipilih...")

    self.btn_browse = QPushButton("Pilih Folder...")
    self.btn_browse.setStyleSheet("padding: 4px 10px;")
    self.btn_browse.clicked.connect(self._select_folder)

    self.btn_settings = QPushButton("⚙ Pengaturan")
    self.btn_settings.setStyleSheet("padding: 4px 12px; font-weight: bold;")
    self.btn_settings.setToolTip("Buka Menu Pengaturan (Ctrl+,)")
    self.btn_settings.clicked.connect(self.settings_requested.emit)

    layout.addWidget(label_folder)
    layout.addWidget(self.txt_folder_path)
    layout.addWidget(self.btn_browse)
    layout.addWidget(self.btn_settings)

  def _select_folder(self):
    current_dir = self.txt_folder_path.text() or ""
    folder = QFileDialog.getExistingDirectory(
        self, "Pilih Folder Antigravity", current_dir
    )
    if folder:
      self.txt_folder_path.setText(folder)
      self.folder_changed.emit(folder)

  def get_folder_path(self) -> str:
    return self.txt_folder_path.text().strip()

  def set_folder_path(self, path: str):
    self.txt_folder_path.setText(path)
