from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class ConfigBarWidget(QWidget):
  """Komponen bar atas untuk menampilkan folder aktif, indikator status Turso/Local DB, dan tombol Pengaturan."""

  settings_requested = pyqtSignal()

  def __init__(self, parent=None):
    super().__init__(parent)
    self.init_ui()

  def init_ui(self):
    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 4)
    layout.setSpacing(8)

    # Indikator Database Status (Local SQLite / Turso Cloud)
    self.lbl_db_status = QLabel("📁 DB: Local (SQLite)")
    self.lbl_db_status.setStyleSheet(
        "background-color: rgba(128, 128, 128, 0.12); color: #333; border: 1px"
        " solid rgba(128, 128, 128, 0.3); border-radius: 4px; padding: 4px"
        " 10px; font-weight: bold; font-size: 11px;"
    )
    self.lbl_db_status.setToolTip("Menggunakan database lokal: accounts_manager.db")

    label_folder = QLabel("<b>Folder Aktif:</b>")
    self.txt_folder_path = QLineEdit()
    self.txt_folder_path.setReadOnly(True)
    self.txt_folder_path.setPlaceholderText("Belum ditentukan (Atur di Menu Pengaturan)...")
    self.txt_folder_path.setStyleSheet(
        "QLineEdit { background-color: rgba(128, 128, 128, 0.08); padding: 4px 8px; }"
    )

    self.btn_settings = QPushButton("⚙ Pengaturan...")
    self.btn_settings.setStyleSheet("padding: 4px 14px; font-weight: bold;")
    self.btn_settings.setToolTip("Buka Menu Pengaturan untuk database Turso, folder, dan enkripsi (Ctrl+,)")
    self.btn_settings.clicked.connect(self.settings_requested.emit)

    layout.addWidget(self.lbl_db_status)
    layout.addWidget(label_folder)
    layout.addWidget(self.txt_folder_path)
    layout.addWidget(self.btn_settings)

  def get_folder_path(self) -> str:
    return self.txt_folder_path.text().strip()

  def set_folder_path(self, path: str):
    self.txt_folder_path.setText(path)

  def set_db_status(
      self,
      use_turso: bool,
      is_connected: bool = True,
      db_name: str = "",
      error_msg: str = "",
  ):
    """Memperbarui badge indikator koneksi database di UI."""
    if not use_turso:
      self.lbl_db_status.setText("📁 DB: Local (SQLite)")
      self.lbl_db_status.setStyleSheet(
          "background-color: rgba(128, 128, 128, 0.12); color: #333; border:"
          " 1px solid rgba(128, 128, 128, 0.3); border-radius: 4px; padding:"
          " 4px 10px; font-weight: bold; font-size: 11px;"
      )
      self.lbl_db_status.setToolTip(
          "Mode Database: Local SQLite (accounts_manager.db)"
      )
    else:
      name_str = f" ({db_name})" if db_name else ""
      if is_connected:
        self.lbl_db_status.setText(f"🟢 Turso: Terhubung{name_str}")
        self.lbl_db_status.setStyleSheet(
            "background-color: #e6f4ea; color: #137333; border: 1px solid"
            " #34a853; border-radius: 4px; padding: 4px 10px; font-weight:"
            " bold; font-size: 11px;"
        )
        self.lbl_db_status.setToolTip(
            f"Koneksi Aktif ke Turso Database{name_str}!"
        )
      else:
        self.lbl_db_status.setText("🔴 Turso: Gagal Konek")
        self.lbl_db_status.setStyleSheet(
            "background-color: #fce8e6; color: #c5221f; border: 1px solid"
            " #ea4335; border-radius: 4px; padding: 4px 10px; font-weight:"
            " bold; font-size: 11px;"
        )
        self.lbl_db_status.setToolTip(
            f"Gagal terhubung ke Turso!\n{error_msg or 'Periksa URL dan Auth Token di Pengaturan.'}"
        )
