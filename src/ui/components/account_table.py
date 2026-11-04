from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from src.crypto import verify_encryption_canary
from src.ui.utils import parse_quota_info


class AccountTableWidget(QWidget):
  """Komponen tabel daftar akun lengkap dengan filter kategori, pemisah data, pengurutan, dan menu konteks."""

  # Sinyal untuk aksi context menu
  copy_requested = pyqtSignal(str)
  update_file_requested = pyqtSignal(str, str)
  update_db_requested = pyqtSignal(str, str)
  delete_requested = pyqtSignal(str, str)
  change_category_requested = pyqtSignal(str, str, str)  # account_id, email, current_category
  sort_mode_changed = pyqtSignal(int)
  category_filter_changed = pyqtSignal(str)

  SEPARATOR_ROLE_VALUE = "__CATEGORY_SEPARATOR__"

  def __init__(self, parent=None):
    super().__init__(parent)
    self._raw_account_rows = []
    self._current_password = ""
    self.init_ui()

  def init_ui(self):
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 5, 0, 0)

    # Bar Kontrol (Filter Kategori & Pengurutan)
    control_layout = QHBoxLayout()
    label_table = QLabel(
        "<b>Daftar Akun:</b> (Klik kanan pada baris untuk menu aksi)"
    )

    # Filter Kategori
    label_filter = QLabel("<b>Kategori:</b>")
    self.cmb_category_filter = QComboBox()
    self.cmb_category_filter.setMinimumWidth(180)
    self.cmb_category_filter.addItem("Semua (Full - Dengan Pemisah)", "__ALL__")
    self.cmb_category_filter.currentIndexChanged.connect(self._on_category_filter_changed)

    # Urutkan Berdasarkan
    label_sort = QLabel("<b>Urutkan:</b>")
    self.cmb_sort_mode = QComboBox()
    self.cmb_sort_mode.addItems([
        "Email (A-Z)",
        "Email (Z-A)",
        "Reset Time Tercepat",
        "Token Terbanyak (Flash)",
        "Token Tersedikit (Flash)",
        "Token Terbanyak (Pro)",
        "Token Tersedikit (Pro)",
        "Token Terbanyak (Claude)",
        "Token Tersedikit (Claude)",
    ])
    self.cmb_sort_mode.currentIndexChanged.connect(self._on_sort_changed)

    control_layout.addWidget(label_table)
    control_layout.addStretch()
    control_layout.addWidget(label_filter)
    control_layout.addWidget(self.cmb_category_filter)
    control_layout.addWidget(label_sort)
    control_layout.addWidget(self.cmb_sort_mode)

    # Tabel Akun (6 Kolom)
    self.table = QTableWidget()
    self.table.setColumnCount(6)
    self.table.setHorizontalHeaderLabels([
        "Email",
        "Kategori",
        "Status Enkripsi",
        "Flash Quota (Reset)",
        "Pro Quota (Reset)",
        "Claude Quota (Reset)",
    ])
    header = self.table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

    self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.table.customContextMenuRequested.connect(self._show_context_menu)

    layout.addLayout(control_layout)
    layout.addWidget(self.table)

  def _on_sort_changed(self, index: int):
    self.sort_mode_changed.emit(index)
    self._render_table()

  def _on_category_filter_changed(self, _index: int):
    current_data = self.cmb_category_filter.currentData()
    self.category_filter_changed.emit(str(current_data))
    self._render_table()

  def get_sort_index(self) -> int:
    return self.cmb_sort_mode.currentIndex()

  def set_sort_index(self, index: int):
    if 0 <= index < self.cmb_sort_mode.count():
      self.cmb_sort_mode.setCurrentIndex(index)

  def get_selected_filter_category(self) -> str:
    return str(self.cmb_category_filter.currentData() or "__ALL__")

  def update_filter_categories(self, categories: list):
    """Memperbarui daftar kategori di dropdown filter dan mempertahankan seleksi jika masih ada."""
    current_selected = self.get_selected_filter_category()
    self.cmb_category_filter.blockSignals(True)
    self.cmb_category_filter.clear()
    self.cmb_category_filter.addItem("Semua (Full - Dengan Pemisah)", "__ALL__")
    self.cmb_category_filter.addItem("— Tanpa Kategori —", "__NONE__")

    has_selected = False
    for cat in categories:
      if cat:
        self.cmb_category_filter.addItem(f"📁 {cat}", cat)
        if cat == current_selected:
          has_selected = True

    if current_selected == "__ALL__":
      self.cmb_category_filter.setCurrentIndex(0)
    elif current_selected == "__NONE__":
      self.cmb_category_filter.setCurrentIndex(1)
    elif has_selected:
      idx = self.cmb_category_filter.findData(current_selected)
      if idx >= 0:
        self.cmb_category_filter.setCurrentIndex(idx)
    else:
      # Jika kategori yang dipilih sebelumnya sudah tidak ada (semua akunnya dipindah), kembali ke Semua
      self.cmb_category_filter.setCurrentIndex(0)

    self.cmb_category_filter.blockSignals(False)

  def set_accounts_data(self, rows, current_password: str = ""):
    """Menyimpan data mentah dari fetch_accounts_summary() dan memperbarui tampilan."""
    self._raw_account_rows = rows or []
    self._current_password = current_password

    # Otomatis perbarui kategori unik yang aktif ada di data
    active_cats = sorted(list({
        str(r[10]).strip()
        for r in self._raw_account_rows
        if len(r) > 10 and r[10] and str(r[10]).strip()
    }), key=lambda s: s.lower())
    self.update_filter_categories(active_cats)

    self._render_table()

  def _sort_items(self, item_list: list):
    """Mengurutkan list akun berdasarkan mode pengurutan yang aktif."""
    sort_mode = self.cmb_sort_mode.currentText()
    if sort_mode == "Email (A-Z)":
      item_list.sort(key=lambda x: x["email"].lower())
    elif sort_mode == "Email (Z-A)":
      item_list.sort(key=lambda x: x["email"].lower(), reverse=True)
    elif sort_mode == "Reset Time Tercepat":
      item_list.sort(key=lambda x: x["min_reset_ts"])
    elif sort_mode == "Token Terbanyak (Flash)":
      item_list.sort(
          key=lambda x: (x["flash"][3] if x["flash"][3] is not None else -1),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Flash)":
      item_list.sort(
          key=lambda x: (x["flash"][3] if x["flash"][3] is not None else 999)
      )
    elif sort_mode == "Token Terbanyak (Pro)":
      item_list.sort(
          key=lambda x: (x["pro"][3] if x["pro"][3] is not None else -1),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Pro)":
      item_list.sort(
          key=lambda x: (x["pro"][3] if x["pro"][3] is not None else 999)
      )
    elif sort_mode == "Token Terbanyak (Claude)":
      item_list.sort(
          key=lambda x: (x["claude"][3] if x["claude"][3] is not None else -1),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Claude)":
      item_list.sort(
          key=lambda x: (x["claude"][3] if x["claude"][3] is not None else 999)
      )

  def _render_table(self):
    parsed_list = []

    for row_data in self._raw_account_rows:
      acc_id = row_data[0]
      email = row_data[1]
      flash_reset = row_data[2]
      flash_frac = row_data[3]
      pro_reset = row_data[4]
      pro_frac = row_data[5]
      claude_reset = row_data[6]
      claude_frac = row_data[7]
      is_enc = bool(row_data[8]) if len(row_data) > 8 else False
      enc_check = row_data[9] if len(row_data) > 9 else None
      cat = str(row_data[10]).strip() if len(row_data) > 10 and row_data[10] else ""

      # Evaluasi status enkripsi dan validasi password
      if not is_enc:
        enc_status_text = "🔓 Plaintext"
        enc_status_color = "#5f6368"
        enc_status_tooltip = "Akun tersimpan dalam kondisi plaintext (tidak dienkripsi)."
      else:
        if not self._current_password:
          enc_status_text = "🔒 Terkunci"
          enc_status_color = "#e37400"
          enc_status_tooltip = (
              "Akun terenkripsi AES-256. Masukkan password enkripsi di Pengaturan untuk membuka."
          )
        else:
          if enc_check:
            is_valid = verify_encryption_canary(enc_check, self._current_password)
            if is_valid:
              enc_status_text = "🟢 Enkripsi Valid"
              enc_status_color = "#137333"
              enc_status_tooltip = (
                  "Kata verifikasi canary cocok! Password enkripsi benar dan data valid."
              )
            else:
              enc_status_text = "🔴 Password Salah"
              enc_status_color = "#c5221f"
              enc_status_tooltip = (
                  "Gagal mendekripsi kata verifikasi canary! Password enkripsi salah atau data korup."
              )
          else:
            enc_status_text = "🔒 Terenkripsi (Lama)"
            enc_status_color = "#1a73e8"
            enc_status_tooltip = "Akun terenkripsi AES-256 (format data sebelum verifikasi canary)."

      p_flash = parse_quota_info(flash_frac, flash_reset)
      p_pro = parse_quota_info(pro_frac, pro_reset)
      p_claude = parse_quota_info(claude_frac, claude_reset)

      min_reset_ts = min(p_flash[4], p_pro[4], p_claude[4])

      parsed_list.append({
          "acc_id": acc_id,
          "email": email or "-",
          "category": cat,
          "enc_status_text": enc_status_text,
          "enc_status_color": enc_status_color,
          "enc_status_tooltip": enc_status_tooltip,
          "flash": p_flash,
          "pro": p_pro,
          "claude": p_claude,
          "min_reset_ts": min_reset_ts,
      })

    filter_val = self.get_selected_filter_category()

    # Bersihkan tabel sebelum mengisi ulang
    self.table.clearSpans()
    self.table.setRowCount(0)

    if filter_val == "__ALL__":
      # ── Mode Full: Kelompokkan berdasarkan kategori & sisipkan pemisah antar data ──
      grouped = {}
      for item in parsed_list:
        cat_key = item["category"]
        grouped.setdefault(cat_key, []).append(item)

      # Urutkan grup: kategori bernama dulu (A-Z), lalu tanpa kategori di akhir
      sorted_keys = sorted([k for k in grouped.keys() if k], key=lambda s: s.lower())
      if "" in grouped:
        sorted_keys.append("")

      current_row = 0
      for cat_key in sorted_keys:
        items_in_group = grouped[cat_key]
        self._sort_items(items_in_group)

        # Sisipkan Baris Pemisah (Group Separator Row)
        self.table.insertRow(current_row)
        cat_title = f"📁 Kategori: {cat_key}" if cat_key else "📁 Tanpa Kategori"
        sep_label = f"  {cat_title} ({len(items_in_group)} Akun)"

        sep_item = QTableWidgetItem(sep_label)
        sep_item.setData(Qt.ItemDataRole.UserRole, self.SEPARATOR_ROLE_VALUE)
        sep_font = QFont()
        sep_font.setBold(True)
        sep_font.setPointSize(sep_font.pointSize() + 1)
        sep_item.setFont(sep_font)
        sep_item.setBackground(QBrush(QColor("#334155")))
        sep_item.setForeground(QBrush(QColor("#ffffff")))
        sep_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        sep_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # Bukan untuk diedit / diseleksi

        self.table.setItem(current_row, 0, sep_item)
        for c in range(1, 6):
          empty_sep = QTableWidgetItem("")
          empty_sep.setData(Qt.ItemDataRole.UserRole, self.SEPARATOR_ROLE_VALUE)
          empty_sep.setBackground(QBrush(QColor("#334155")))
          empty_sep.setFlags(Qt.ItemFlag.ItemIsEnabled)
          self.table.setItem(current_row, c, empty_sep)

        self.table.setSpan(current_row, 0, 1, 6)
        self.table.setRowHeight(current_row, 32)
        current_row += 1

        # Tambahkan baris-baris data akun di grup ini
        for item_data in items_in_group:
          self.table.insertRow(current_row)
          self._populate_account_row(current_row, item_data)
          current_row += 1

    else:
      # ── Mode Kategori Tertentu ──
      target_cat = "" if filter_val == "__NONE__" else filter_val
      filtered_list = [item for item in parsed_list if item["category"].lower() == target_cat.lower()]
      self._sort_items(filtered_list)

      for current_row, item_data in enumerate(filtered_list):
        self.table.insertRow(current_row)
        self._populate_account_row(current_row, item_data)

  def _populate_account_row(self, row_idx: int, item_data: dict):
    """Mengisi satu baris akun dengan 6 kolom."""
    p_flash = item_data["flash"]
    p_pro = item_data["pro"]
    p_claude = item_data["claude"]
    row_has_reset = p_flash[1] or p_pro[1] or p_claude[1]

    # 0: Email
    item_email = QTableWidgetItem(item_data["email"])
    item_email.setData(Qt.ItemDataRole.UserRole, item_data["acc_id"])

    # 1: Kategori
    cat_text = item_data["category"] if item_data["category"] else "—"
    item_cat = QTableWidgetItem(cat_text)
    item_cat.setData(Qt.ItemDataRole.UserRole, item_data["category"])
    item_cat.setForeground(QBrush(QColor("#1a73e8" if item_data["category"] else "#888888")))

    # 2: Status Enkripsi
    item_enc_status = QTableWidgetItem(item_data["enc_status_text"])
    item_enc_status.setForeground(QBrush(QColor(item_data["enc_status_color"])))
    item_enc_status.setToolTip(item_data["enc_status_tooltip"])
    font_status = item_enc_status.font()
    font_status.setBold(True)
    item_enc_status.setFont(font_status)

    # 3: Flash Quota
    item_flash = QTableWidgetItem(p_flash[0])
    item_flash.setForeground(QBrush(QColor(p_flash[2])))

    # 4: Pro Quota
    item_pro = QTableWidgetItem(p_pro[0])
    item_pro.setForeground(QBrush(QColor(p_pro[2])))

    # 5: Claude Quota
    item_claude = QTableWidgetItem(p_claude[0])
    item_claude.setForeground(QBrush(QColor(p_claude[2])))

    items = [item_email, item_cat, item_enc_status, item_flash, item_pro, item_claude]

    for c, item in enumerate(items):
      item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
      if row_has_reset:
        item.setBackground(QBrush(QColor("#ffcdd2")))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
      self.table.setItem(row_idx, c, item)

  def _show_context_menu(self, pos):
    item = self.table.itemAt(pos)
    if not item:
      return

    row = item.row()
    first_item = self.table.item(row, 0)
    if not first_item:
      return

    role_data = first_item.data(Qt.ItemDataRole.UserRole)
    # Jangan tampilkan menu pada baris pemisah kategori
    if role_data == self.SEPARATOR_ROLE_VALUE:
      return

    account_id = role_data
    email = first_item.text()

    # Ambil kategori saat ini dari kolom 1
    cat_item = self.table.item(row, 1)
    current_category = str(cat_item.data(Qt.ItemDataRole.UserRole) or "") if cat_item else ""

    menu = QMenu(self)
    action_copy = menu.addAction("  📋 Copy JSON")
    action_update_file = menu.addAction("  💾 Update ke antigravity-accounts.json")
    action_update_db = menu.addAction(
        "  🔄 Update Database dari antigravity-accounts.json"
    )
    menu.addSeparator()
    action_change_cat = menu.addAction("  🏷️ Ubah Kategori...")
    menu.addSeparator()
    action_delete = menu.addAction("  🗑️ Hapus Akun")

    chosen_action = menu.exec(self.table.viewport().mapToGlobal(pos))
    if chosen_action == action_copy:
      self.copy_requested.emit(account_id)
    elif chosen_action == action_update_file:
      self.update_file_requested.emit(account_id, email)
    elif chosen_action == action_update_db:
      self.update_db_requested.emit(account_id, email)
    elif chosen_action == action_change_cat:
      self.change_category_requested.emit(account_id, email, current_category)
    elif chosen_action == action_delete:
      self.delete_requested.emit(account_id, email)
