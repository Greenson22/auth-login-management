from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class ConfigBarWidget(QWidget):
  """Komponen bagian atas untuk memilih dan menampilkan folder OpenCode Config."""

  folder_changed = pyqtSignal(str)

  def __init__(self, parent=None):
    super().__init__(parent)
    self.init_ui()

  def init_ui(self):
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)

    label_folder = QLabel("<b>Folder OpenCode Config:</b>")
    self.txt_folder_path = QLineEdit()
    self.txt_folder_path.setReadOnly(True)
    self.txt_folder_path.setPlaceholderText("Belum ada folder yang dipilih...")

    self.btn_browse = QPushButton("Pilih Folder...")
    self.btn_browse.setStyleSheet("padding: 4px 10px;")
    self.btn_browse.clicked.connect(self._select_folder)

    layout.addWidget(label_folder)
    layout.addWidget(self.txt_folder_path)
    layout.addWidget(self.btn_browse)

  def _select_folder(self):
    current_dir = self.txt_folder_path.text() or ""
    folder = QFileDialog.getExistingDirectory(
        self, "Pilih Folder OpenCode Config", current_dir
    )
    if folder:
      self.txt_folder_path.setText(folder)
      self.folder_changed.emit(folder)

  def get_folder_path(self) -> str:
    return self.txt_folder_path.text().strip()

  def set_folder_path(self, path: str):
    self.txt_folder_path.setText(path)
