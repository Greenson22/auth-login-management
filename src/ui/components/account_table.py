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
  """Komponen tabel daftar akun lengkap dengan kontrol pengurutan dan menu konteks."""

  # Sinyal untuk aksi context menu (account_id, email)
  copy_requested = pyqtSignal(str)
  update_file_requested = pyqtSignal(str, str)
  update_db_requested = pyqtSignal(str, str)
  delete_requested = pyqtSignal(str, str)
  sort_mode_changed = pyqtSignal(int)

  def __init__(self, parent=None):
    super().__init__(parent)
    self._raw_account_rows = []
    self._current_password = ""
    self.init_ui()

  def init_ui(self):
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 5, 0, 0)

    # Bar Pengurutan (Sorting Bar)
    sort_layout = QHBoxLayout()
    label_table = QLabel(
        "<b>Daftar Akun:</b> (Klik kanan pada baris untuk menu aksi)"
    )

    label_sort = QLabel("<b>Urutkan Berdasarkan:</b>")
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

    sort_layout.addWidget(label_table)
    sort_layout.addStretch()
    sort_layout.addWidget(label_sort)
    sort_layout.addWidget(self.cmb_sort_mode)

    # Tabel Akun
    self.table = QTableWidget()
    self.table.setColumnCount(5)
    self.table.setHorizontalHeaderLabels([
        "Email",
        "Status Enkripsi",
        "Flash Quota (Reset)",
        "Pro Quota (Reset)",
        "Claude Quota (Reset)",
    ])
    self.table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Stretch
    )
    self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.table.customContextMenuRequested.connect(self._show_context_menu)

    layout.addLayout(sort_layout)
    layout.addWidget(self.table)

  def _on_sort_changed(self, index: int):
    self.sort_mode_changed.emit(index)
    self._render_table()

  def get_sort_index(self) -> int:
    return self.cmb_sort_mode.currentIndex()

  def set_sort_index(self, index: int):
    if 0 <= index < self.cmb_sort_mode.count():
      self.cmb_sort_mode.setCurrentIndex(index)

  def set_accounts_data(self, rows, current_password: str = ""):
    """Menyimpan data mentah dari fetch_accounts_summary() dan memperbarui tampilan."""
    self._raw_account_rows = rows
    self._current_password = current_password
    self._render_table()

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
              "Akun terenkripsi AES-256. Atur/masukkan password enkripsi di Pengaturan untuk membuka."
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
          "enc_status_text": enc_status_text,
          "enc_status_color": enc_status_color,
          "enc_status_tooltip": enc_status_tooltip,
          "flash": p_flash,
          "pro": p_pro,
          "claude": p_claude,
          "min_reset_ts": min_reset_ts,
      })

    # Logika Pengurutan
    sort_mode = self.cmb_sort_mode.currentText()
    if sort_mode == "Email (A-Z)":
      parsed_list.sort(key=lambda x: x["email"].lower())
    elif sort_mode == "Email (Z-A)":
      parsed_list.sort(key=lambda x: x["email"].lower(), reverse=True)
    elif sort_mode == "Reset Time Tercepat":
      parsed_list.sort(key=lambda x: x["min_reset_ts"])
    elif sort_mode == "Token Terbanyak (Flash)":
      parsed_list.sort(
          key=lambda x: (
              x["flash"][3] if x["flash"][3] is not None else -1
          ),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Flash)":
      parsed_list.sort(
          key=lambda x: (
              x["flash"][3] if x["flash"][3] is not None else 999
          )
      )
    elif sort_mode == "Token Terbanyak (Pro)":
      parsed_list.sort(
          key=lambda x: (x["pro"][3] if x["pro"][3] is not None else -1),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Pro)":
      parsed_list.sort(
          key=lambda x: (x["pro"][3] if x["pro"][3] is not None else 999)
      )
    elif sort_mode == "Token Terbanyak (Claude)":
      parsed_list.sort(
          key=lambda x: (
              x["claude"][3] if x["claude"][3] is not None else -1
          ),
          reverse=True,
      )
    elif sort_mode == "Token Tersedikit (Claude)":
      parsed_list.sort(
          key=lambda x: (
              x["claude"][3] if x["claude"][3] is not None else 999
          )
      )

    # Tampilkan ke QTableWidget
    self.table.setRowCount(0)
    for row_idx, item_data in enumerate(parsed_list):
      self.table.insertRow(row_idx)

      p_flash = item_data["flash"]
      p_pro = item_data["pro"]
      p_claude = item_data["claude"]

      row_has_reset = p_flash[1] or p_pro[1] or p_claude[1]

      item_email = QTableWidgetItem(item_data["email"])
      item_email.setData(Qt.ItemDataRole.UserRole, item_data["acc_id"])

      item_enc_status = QTableWidgetItem(item_data["enc_status_text"])
      item_enc_status.setForeground(QBrush(QColor(item_data["enc_status_color"])))
      item_enc_status.setToolTip(item_data["enc_status_tooltip"])
      font_status = item_enc_status.font()
      font_status.setBold(True)
      item_enc_status.setFont(font_status)

      item_flash = QTableWidgetItem(p_flash[0])
      item_flash.setForeground(QBrush(QColor(p_flash[2])))

      item_pro = QTableWidgetItem(p_pro[0])
      item_pro.setForeground(QBrush(QColor(p_pro[2])))

      item_claude = QTableWidgetItem(p_claude[0])
      item_claude.setForeground(QBrush(QColor(p_claude[2])))

      items = [item_email, item_enc_status, item_flash, item_pro, item_claude]

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
    account_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
    email = self.table.item(row, 0).text()

    menu = QMenu(self)
    action_copy = menu.addAction("  Copy JSON")
    action_update_file = menu.addAction("  Update ke antigravity-accounts.json")
    action_update_db = menu.addAction(
        "  Update Database dari antigravity-accounts.json"
    )
    menu.addSeparator()
    action_delete = menu.addAction("  Hapus Akun")

    chosen_action = menu.exec(self.table.viewport().mapToGlobal(pos))
    if chosen_action == action_copy:
      self.copy_requested.emit(account_id)
    elif chosen_action == action_update_file:
      self.update_file_requested.emit(account_id, email)
    elif chosen_action == action_update_db:
      self.update_db_requested.emit(account_id, email)
    elif chosen_action == action_delete:
      self.delete_requested.emit(account_id, email)
