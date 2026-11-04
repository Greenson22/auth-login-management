from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class DeleteConfirmationDialog(QDialog):
  """Dialog konfirmasi penghapusan ketat yang mewajibkan pengguna mengetik nama kategori secara persis."""

  def __init__(self, category_name: str, account_count: int, parent=None):
    super().__init__(parent)
    self.category_name = category_name
    self.account_count = account_count
    self.init_ui()

  def init_ui(self):
    self.setWindowTitle("⚠️ Konfirmasi Hapus Kategori & Akun")
    self.setFixedWidth(460)
    self.setStyleSheet("background-color: #ffffff; color: #333333;")

    layout = QVBoxLayout(self)
    layout.setSpacing(14)
    layout.setContentsMargins(20, 20, 20, 20)

    # Peringatan Bahaya
    lbl_warning = QLabel(
        f"<b style='color: #d32f2f; font-size: 14px;'>PERINGATAN TINDAKAN BERBAHAYA!</b><br><br>"
        f"Anda akan menghapus kategori <b>\"{self.category_name}\"</b> dan "
        f"<b>{self.account_count} akun</b> yang berada di dalamnya.<br><br>"
        f"Semua akun beserta token dan kuotanya akan <b>terhapus secara permanen</b> "
        f"dari database dan tidak dapat dikembalikan.<br><br>"
        f"Untuk melanjutkan, ketik nama kategori persis di bawah ini: "
        f"<br><span style='background-color: #ffebee; color: #c62828; padding: 2px 6px; font-weight: bold; border-radius: 3px;'>{self.category_name}</span>"
    )
    lbl_warning.setWordWrap(True)
    layout.addWidget(lbl_warning)

    # Input Konfirmasi
    self.txt_confirm = QLineEdit()
    self.txt_confirm.setPlaceholderText(f"Ketik persis '{self.category_name}'")
    self.txt_confirm.setStyleSheet(
        "QLineEdit { padding: 8px 10px; border: 1px solid #d32f2f; border-radius: 4px; font-size: 13px; }"
    )
    self.txt_confirm.textChanged.connect(self._on_text_changed)
    layout.addWidget(self.txt_confirm)

    # Tombol Aksi
    btn_layout = QHBoxLayout()
    btn_layout.setSpacing(10)
    btn_layout.addStretch()

    self.btn_cancel = QPushButton("Batal")
    self.btn_cancel.setStyleSheet("padding: 7px 16px; border-radius: 4px;")
    self.btn_cancel.clicked.connect(self.reject)

    self.btn_delete = QPushButton("Hapus Permanen")
    self.btn_delete.setEnabled(False)
    self.btn_delete.setStyleSheet(
        "QPushButton { background-color: #d32f2f; color: white; font-weight: bold; padding: 7px 16px; border-radius: 4px; border: none; }"
        "QPushButton:hover { background-color: #b71c1c; }"
        "QPushButton:disabled { background-color: #e0e0e0; color: #9e9e9e; }"
    )
    self.btn_delete.clicked.connect(self.accept)

    btn_layout.addWidget(self.btn_cancel)
    btn_layout.addWidget(self.btn_delete)
    layout.addLayout(btn_layout)

  def _on_text_changed(self, text: str):
    self.btn_delete.setEnabled(text.strip() == self.category_name.strip())


class CategoryManagementDialog(QDialog):
  """Dialog manajemen kategori akun (Rename, Bulk Move, dan Hapus Kategori & Akun)."""

  categories_updated = pyqtSignal()

  def __init__(self, db, parent=None):
    super().__init__(parent)
    self.db = db
    self.has_changes = False
    self.init_ui()
    self.load_categories()

  def init_ui(self):
    self.setWindowTitle("📁 Manajemen Kategori Akun")
    self.resize(560, 420)
    self.setStyleSheet("background-color: #ffffff; color: #333333;")

    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(18, 18, 18, 18)
    main_layout.setSpacing(12)

    # Info Header
    lbl_desc = QLabel(
        "Kelola kategori yang digunakan oleh akun Anda. Pilih salah satu kategori pada tabel "
        "lalu pilih tindakan di bawah."
    )
    lbl_desc.setWordWrap(True)
    lbl_desc.setStyleSheet("color: #555555; font-size: 12px; margin-bottom: 4px;")
    main_layout.addWidget(lbl_desc)

    # Content Area (Tabel + Action Buttons)
    content_layout = QHBoxLayout()
    content_layout.setSpacing(12)

    # Tabel Kategori
    self.table = QTableWidget()
    self.table.setColumnCount(2)
    self.table.setHorizontalHeaderLabels(["Nama Kategori", "Jumlah Akun"])
    header = self.table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    self.table.itemSelectionChanged.connect(self._on_selection_changed)
    content_layout.addWidget(self.table)

    # Panel Tombol Aksi Kategori
    action_panel = QVBoxLayout()
    action_panel.setSpacing(8)

    self.btn_rename = QPushButton("✏️ Ubah Nama")
    self.btn_rename.setToolTip("Mengubah nama kategori ini untuk semua akun terkait")
    self.btn_rename.setStyleSheet("padding: 7px 12px; text-align: left; font-size: 12px;")
    self.btn_rename.clicked.connect(self._rename_category)

    self.btn_move = QPushButton("➡️ Pindah Semua Akun")
    self.btn_move.setToolTip("Pindahkan semua akun dalam kategori ini ke kategori lain")
    self.btn_move.setStyleSheet("padding: 7px 12px; text-align: left; font-size: 12px;")
    self.btn_move.clicked.connect(self._move_category_accounts)

    self.btn_delete = QPushButton("🗑️ Hapus Kategori & Akun")
    self.btn_delete.setToolTip("Hapus kategori beserta seluruh akun di dalamnya secara permanen")
    self.btn_delete.setStyleSheet(
        "QPushButton { padding: 7px 12px; text-align: left; font-size: 12px; color: #d32f2f; }"
        "QPushButton:hover { background-color: #ffebee; border: 1px solid #d32f2f; }"
    )
    self.btn_delete.clicked.connect(self._delete_category)

    action_panel.addWidget(self.btn_rename)
    action_panel.addWidget(self.btn_move)
    action_panel.addWidget(self.btn_delete)
    action_panel.addStretch()

    content_layout.addLayout(action_panel)
    main_layout.addLayout(content_layout)

    # Footer
    footer_layout = QHBoxLayout()
    self.lbl_summary = QLabel("Memuat data...")
    self.lbl_summary.setStyleSheet("color: #666666; font-size: 11px;")
    footer_layout.addWidget(self.lbl_summary)
    footer_layout.addStretch()

    btn_close = QPushButton("Tutup")
    btn_close.setStyleSheet("padding: 6px 18px; border-radius: 4px;")
    btn_close.clicked.connect(self.accept)
    footer_layout.addWidget(btn_close)

    main_layout.addLayout(footer_layout)

    self._update_action_state()

  def _update_action_state(self):
    has_selection = len(self.table.selectedItems()) > 0
    self.btn_rename.setEnabled(has_selection)
    self.btn_move.setEnabled(has_selection)
    self.btn_delete.setEnabled(has_selection)

  def _on_selection_changed(self):
    self._update_action_state()

  def _get_selected_category_info(self):
    selected_rows = self.table.selectionModel().selectedRows()
    if not selected_rows:
      return None, 0
    row = selected_rows[0].row()
    name_item = self.table.item(row, 0)
    count_item = self.table.item(row, 1)
    cat_name = name_item.text().strip() if name_item else ""
    try:
      count = int(count_item.text()) if count_item else 0
    except ValueError:
      count = 0
    return cat_name, count

  def load_categories(self):
    """Mengambil daftar kategori beserta hitungan akun dari database dan mengisi tabel."""
    self.table.setRowCount(0)
    if not self.db:
      self.lbl_summary.setText("Database tidak tersedia.")
      return

    try:
      cat_counts = self.db.fetch_categories_with_counts()
    except Exception as e:
      self.lbl_summary.setText(f"Gagal memuat kategori: {e}")
      return

    total_cats = len(cat_counts)
    total_accs = sum(item["count"] for item in cat_counts)

    self.table.setRowCount(total_cats)
    for row_idx, item in enumerate(cat_counts):
      cat_name = item["category"]
      count = item["count"]

      item_name = QTableWidgetItem(cat_name)
      item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)

      item_count = QTableWidgetItem(str(count))
      item_count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      item_count.setFlags(item_count.flags() & ~Qt.ItemFlag.ItemIsEditable)
      item_count.setForeground(QBrush(QColor("#1a73e8")))

      self.table.setItem(row_idx, 0, item_name)
      self.table.setItem(row_idx, 1, item_count)

    self.lbl_summary.setText(f"Total: {total_cats} Kategori | {total_accs} Akun")
    self._update_action_state()

  def _rename_category(self):
    cat_name, _ = self._get_selected_category_info()
    if not cat_name:
      return

    new_name, ok = QInputDialog.getText(
        self,
        "Ubah Nama Kategori",
        f"Masukkan nama baru untuk kategori '{cat_name}':",
        text=cat_name,
    )
    if not ok:
      return

    new_name = new_name.strip()
    if not new_name:
      QMessageBox.warning(self, "Peringatan", "Nama kategori tidak boleh kosong!")
      return

    if new_name == cat_name:
      return

    try:
      affected = self.db.rename_category(cat_name, new_name)
      self.has_changes = True
      self.categories_updated.emit()
      self.load_categories()
      QMessageBox.information(
          self,
          "Sukses",
          f"Berhasil mengubah kategori '{cat_name}' menjadi '{new_name}' ({affected} akun diperbarui).",
      )
    except Exception as e:
      QMessageBox.critical(self, "Error", f"Gagal mengubah nama kategori:\n{e}")

  def _move_category_accounts(self):
    cat_name, count = self._get_selected_category_info()
    if not cat_name:
      return

    # Ambil kategori yang tersedia selain yang sedang dipilih
    all_cats = self.db.fetch_categories()
    other_cats = [c for c in all_cats if c != cat_name]

    new_target, ok = QInputDialog.getItem(
        self,
        "Pindah Semua Akun",
        f"Pindahkan seluruh ({count}) akun dari '{cat_name}' ke kategori:",
        other_cats,
        0,
        True,  # Editable agar user bisa mengetik kategori baru
    )
    if not ok:
      return

    new_target = new_target.strip()
    if not new_target:
      QMessageBox.warning(self, "Peringatan", "Kategori tujuan tidak boleh kosong!")
      return

    if new_target == cat_name:
      QMessageBox.information(self, "Info", "Kategori tujuan sama dengan kategori asal.")
      return

    try:
      affected = self.db.move_category_accounts(cat_name, new_target)
      self.has_changes = True
      self.categories_updated.emit()
      self.load_categories()
      QMessageBox.information(
          self,
          "Sukses",
          f"Berhasil memindahkan {affected} akun dari '{cat_name}' ke '{new_target}'.",
      )
    except Exception as e:
      QMessageBox.critical(self, "Error", f"Gagal memindahkan akun:\n{e}")

  def _delete_category(self):
    cat_name, count = self._get_selected_category_info()
    if not cat_name:
      return

    confirm_dialog = DeleteConfirmationDialog(cat_name, count, self)
    if confirm_dialog.exec() != QDialog.DialogCode.Accepted:
      return

    try:
      deleted = self.db.delete_category_and_accounts(cat_name)
      self.has_changes = True
      self.categories_updated.emit()
      self.load_categories()
      QMessageBox.information(
          self,
          "Berhasil Dihapus",
          f"Kategori '{cat_name}' beserta {deleted} akun di dalamnya telah berhasil dihapus secara permanen.",
      )
    except Exception as e:
      QMessageBox.critical(self, "Error", f"Gagal menghapus kategori dan akun:\n{e}")
