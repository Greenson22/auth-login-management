from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class JsonInputWidget(QWidget):
  """Komponen input teks JSON, pilihan kategori, dan tombol aksi simpan/bersihkan."""

  # Sinyal memancarkan (raw_json_str, category_str)
  json_submitted = pyqtSignal(str, str)

  def __init__(self, parent=None):
    super().__init__(parent)
    self.init_ui()

  def init_ui(self):
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 5, 0, 0)

    # Header baris label & pilihan kategori
    top_layout = QHBoxLayout()
    label = QLabel("<b>Paste JSON Akun di Sini:</b>")

    label_cat = QLabel("<b>Kategori (Opsional):</b>")
    self.cmb_category = QComboBox()
    self.cmb_category.setEditable(True)
    self.cmb_category.setMinimumWidth(220)
    self.cmb_category.lineEdit().setPlaceholderText("Pilih atau ketik kategori baru...")
    self.cmb_category.addItem("(Tanpa Kategori)", "")

    top_layout.addWidget(label)
    top_layout.addStretch()
    top_layout.addWidget(label_cat)
    top_layout.addWidget(self.cmb_category)

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

    layout.addLayout(top_layout)
    layout.addWidget(self.txt_json)
    layout.addLayout(btn_layout)

  def set_categories(self, categories: list):
    """Memperbarui daftar kategori di ComboBox tanpa menghilangkan teks yang sedang diketik user."""
    current_text = self.get_selected_category()
    self.cmb_category.blockSignals(True)
    self.cmb_category.clear()
    self.cmb_category.addItem("(Tanpa Kategori)", "")
    for cat in categories:
      if cat:
        self.cmb_category.addItem(cat, cat)

    # Kembalikan teks jika user sudah mengetik/memilih sebelumnya
    if current_text:
      idx = self.cmb_category.findText(current_text)
      if idx >= 0:
        self.cmb_category.setCurrentIndex(idx)
      else:
        self.cmb_category.setEditText(current_text)
    else:
      self.cmb_category.setCurrentIndex(0)
    self.cmb_category.blockSignals(False)

  def get_selected_category(self) -> str:
    """Mengambil teks kategori yang dipilih atau diketik."""
    text = self.cmb_category.currentText().strip()
    if text == "(Tanpa Kategori)":
      return ""
    return text

  def _on_save_clicked(self):
    raw_text = self.txt_json.toPlainText().strip()
    category = self.get_selected_category()
    self.json_submitted.emit(raw_text, category)

  def clear_input(self):
    self.txt_json.clear()
