import os
import random
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QDesktopServices,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class AboutDialog(QDialog):
  """Dialog 'Tentang Aplikasi' yang menampilkan fitur sistem dan profil pengembang."""

  VERSES = [
      {
          "text": (
              '"Serahkanlah perbuatanmu kepada TUHAN,\n'
              'maka terlaksanalah segala rencanamu."'
          ),
          "ref": "— Amsal 16:3 —",
      },
      {
          "text": (
              '"Bukan kepada kami, ya TUHAN, bukan kepada kami,\n'
              'tetapi kepada nama-Mulah beri kemuliaan,\n'
              'oleh karena kasih-Mu, oleh karena setia-Mu!"'
          ),
          "ref": "— Mazmur 115:1 —",
      },
      {
          "text": (
              '"Apapun juga yang kamu perbuat,\n'
              'perbuatlah dengan segenap hatimu\n'
              'seperti untuk Tuhan dan bukan untuk manusia."'
          ),
          "ref": "— Kolose 3:23 —",
      },
      {
          "text": (
              '"Percayalah kepada TUHAN dengan segenap hatimu,\n'
              'dan janganlah bersandar kepada pengertianmu sendiri.\n'
              'Akuilah Dia dalam segala lakumu,\n'
              'maka Ia akan meluruskan jalanmu."'
          ),
          "ref": "— Amsal 3:5-6 —",
      },
  ]

  def __init__(self, parent=None):
    super().__init__(parent)
    self.current_verse_index = random.randint(0, len(self.VERSES) - 1)
    self.base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    self.assets_dir = os.path.join(self.base_dir, "assets", "images")

    self.init_ui()
    self.start_verse_timer()

  def init_ui(self):
    self.setWindowTitle("Tentang Aplikasi - JSON Account Manager")
    self.resize(650, 680)
    self.setMinimumSize(560, 580)

    # Set Window Icon jika ada
    icon_path = os.path.join(self.assets_dir, "app_icon.png")
    if os.path.exists(icon_path):
      self.setWindowIcon(QIcon(icon_path))

    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(16, 16, 16, 16)
    main_layout.setSpacing(12)

    self.tabs = QTabWidget()
    self.tabs.setStyleSheet("""
        QTabWidget::pane {
            border: 1px solid #d0d7de;
            background: #ffffff;
            border-radius: 8px;
        }
        QTabBar::tab {
            background: #f6f8fa;
            border: 1px solid #d0d7de;
            border-bottom: none;
            padding: 8px 24px;
            margin-right: 4px;
            font-weight: bold;
            font-size: 13px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
        }
        QTabBar::tab:selected {
            background: #3949ab;
            color: #ffffff;
            border-color: #3949ab;
        }
        QTabBar::tab:!selected:hover {
            background: #eaeef2;
        }
    """)

    self.tab_features = self._create_features_tab()
    self.tab_developer = self._create_developer_tab()

    self.tabs.addTab(self.tab_features, "Fitur Aplikasi")
    self.tabs.addTab(self.tab_developer, "Pengembang")

    main_layout.addWidget(self.tabs)

    # Tombol Tutup di bagian bawah
    btn_box = QHBoxLayout()
    btn_box.addStretch()
    btn_close = QPushButton("Tutup")
    btn_close.setFixedWidth(100)
    btn_close.setStyleSheet("""
        QPushButton {
            background-color: #3949ab;
            color: white;
            font-weight: bold;
            padding: 6px 14px;
            border-radius: 6px;
        }
        QPushButton:hover {
            background-color: #283593;
        }
    """)
    btn_close.clicked.connect(self.accept)
    btn_box.addWidget(btn_close)

    main_layout.addLayout(btn_box)

  # ─── TAB 1: Fitur Aplikasi ───

  def _create_features_tab(self) -> QWidget:
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)

    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(16, 16, 16, 16)
    container_layout.setSpacing(12)

    features = [
        {
            "icon": "⚡",
            "title": "Manajemen Akun JSON Terpusat",
            "subtitle": (
                "Simpan, organisir, dan kelola akun multi-kredensial format"
                " JSON Antigravity / OpenCode dengan validasi format instan dan"
                " tampilan tabel terstruktur."
            ),
        },
        {
            "icon": "☁️",
            "title": "Sinkronisasi Turso Database & SQLite Lokal",
            "subtitle": (
                "Dukungan fleksibel penyimpanan offline lokal"
                " (accounts_manager.db) serta sinkronisasi cloud database Turso"
                " (libSQL) dengan pengujian koneksi langsung."
            ),
        },
        {
            "icon": "🔒",
            "title": "Enkripsi Kredensial AES-256",
            "subtitle": (
                "Keamanan tingkat tinggi dengan enkripsi standar militer"
                " AES-256-CBC dan derivasi PBKDF2 untuk melindungi token dan"
                " data sensitif di database."
            ),
        },
        {
            "icon": "🔄",
            "title": "Hot-Swap File Antigravity",
            "subtitle": (
                "Terapkan dan suntikkan konfigurasi akun terpilih langsung ke"
                " berkas aktif target Antigravity secara real-time hanya dengan"
                " satu klik tombol."
            ),
        },
        {
            "icon": "📥",
            "title": "Sinkronisasi Balik (Reverse Sync)",
            "subtitle": (
                "Perbarui catatan database langsung dari berkas aktif"
                " Antigravity saat ini, memastikan konsistensi konfigurasi yang"
                " sedang digunakan."
            ),
        },
        {
            "icon": "📋",
            "title": "Penyalinan JSON Satu Klik",
            "subtitle": (
                "Salin seluruh objek JSON akun secara rapi dan instan ke system"
                " clipboard untuk kebutuhan debug, otomasi, maupun backup."
            ),
        },
        {
            "icon": "🔍",
            "title": "Pencarian Cepat & Pengurutan Adaptif",
            "subtitle": (
                "Urutkan daftar akun berdasarkan ID, nama akun, waktu update"
                " terbaru/terlama, serta filter pencarian cepat tanpa lag."
            ),
        },
        {
            "icon": "⚙️",
            "title": "Konfigurasi Direktori Fleksibel",
            "subtitle": (
                "Atur direktori path folder Antigravity bebas di mana saja,"
                " memudahkan integrasi di sistem Linux, Windows, maupun"
                " multi-environment."
            ),
        },
    ]

    for item in features:
      card = QFrame()
      card.setStyleSheet("""
          QFrame {
              background-color: #fafbfc;
              border: 1px solid #e1e4e8;
              border-radius: 8px;
              padding: 10px;
          }
          QFrame:hover {
              background-color: #f1f4f8;
              border: 1px solid #c8d1d9;
          }
      """)
      c_layout = QHBoxLayout(card)
      c_layout.setContentsMargins(8, 8, 8, 8)
      c_layout.setSpacing(14)

      # Icon visual
      lbl_icon = QLabel(item["icon"])
      lbl_icon.setStyleSheet("""
          font-size: 26px;
          background-color: #e8eaf6;
          border-radius: 8px;
          padding: 6px 10px;
      """)
      lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
      c_layout.addWidget(lbl_icon)

      # Teks
      text_col = QVBoxLayout()
      text_col.setSpacing(4)
      lbl_title = QLabel(item["title"])
      lbl_title.setStyleSheet(
          "font-weight: bold; font-size: 14px; color: #1a237e;"
      )
      lbl_sub = QLabel(item["subtitle"])
      lbl_sub.setStyleSheet("font-size: 12px; color: #555555;")
      lbl_sub.setWordWrap(True)
      text_col.addWidget(lbl_title)
      text_col.addWidget(lbl_sub)
      c_layout.addLayout(text_col, 1)

      container_layout.addWidget(card)

    container_layout.addStretch()
    scroll_area.setWidget(container)
    return scroll_area

  # ─── TAB 2: Pengembang ───

  def _create_developer_tab(self) -> QWidget:
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)

    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(20, 20, 20, 20)
    container_layout.setSpacing(16)
    container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    # 1. Card Dedikasi & Rotasi Ayat Alkitab
    self.verse_card = QFrame()
    self.verse_card.setStyleSheet("""
        QFrame {
            background-color: #f3f4fd;
            border: 1.5px solid #c5cae9;
            border-radius: 12px;
            padding: 14px;
        }
    """)
    verse_layout = QVBoxLayout(self.verse_card)
    verse_layout.setSpacing(8)
    verse_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    quote_icon = QLabel("❝")
    quote_icon.setStyleSheet(
        "font-size: 24px; color: #7986cb; font-weight: bold;"
    )
    quote_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    verse_layout.addWidget(quote_icon)

    self.lbl_verse_text = QLabel()
    self.lbl_verse_text.setStyleSheet(
        "font-size: 13px; font-style: italic; font-weight: bold; color:"
        " #283593; line-height: 1.4;"
    )
    self.lbl_verse_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.lbl_verse_text.setWordWrap(True)
    verse_layout.addWidget(self.lbl_verse_text)

    self.lbl_verse_ref = QLabel()
    self.lbl_verse_ref.setStyleSheet(
        "font-size: 12px; font-weight: bold; color: #3949ab;"
    )
    self.lbl_verse_ref.setAlignment(Qt.AlignmentFlag.AlignCenter)
    verse_layout.addWidget(self.lbl_verse_ref)

    # Garis pemisah tipis
    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.HLine)
    divider.setStyleSheet("color: #d1d5db; margin: 4px 40px;")
    verse_layout.addWidget(divider)

    lbl_thanks = QLabel(
        "Puji dan syukur yang tak terhingga kepada TUHAN atas hikmat, kekuatan,"
        " dan tuntunan-Nya yang sempurna dari awal perancangan hingga"
        " terselesaikannya aplikasi ini. Segala kemuliaan hanya bagi nama-Nya."
    )
    lbl_thanks.setStyleSheet("font-size: 12px; color: #4b5563; line-height: 1.4;")
    lbl_thanks.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_thanks.setWordWrap(True)
    verse_layout.addWidget(lbl_thanks)

    container_layout.addWidget(self.verse_card)
    self._update_verse_display()

    # 2. Foto Profil Bulat
    profile_layout = QHBoxLayout()
    profile_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    profile_img_path = os.path.join(self.assets_dir, "profile.jpg")
    lbl_avatar = QLabel()
    lbl_avatar.setFixedSize(120, 120)

    if os.path.exists(profile_img_path):
      avatar_pixmap = self._get_circular_pixmap(profile_img_path, 120)
      lbl_avatar.setPixmap(avatar_pixmap)
    else:
      lbl_avatar.setText("👤")
      lbl_avatar.setStyleSheet(
          "font-size: 60px; background: #e0e0e0; border-radius: 60px;"
      )
      lbl_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    profile_layout.addWidget(lbl_avatar)
    container_layout.addLayout(profile_layout)

    # 3. Identitas Pengembang
    lbl_name = QLabel("Frendy Rikal Gerung, S.Kom.")
    lbl_name.setStyleSheet(
        "font-size: 18px; font-weight: bold; color: #1a237e;"
    )
    lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    container_layout.addWidget(lbl_name)

    lbl_degree = QLabel(
        "Lulusan Sarjana Komputer dari Universitas Negeri Manado"
    )
    lbl_degree.setStyleSheet(
        "font-size: 13px; font-weight: 500; color: #424242;"
    )
    lbl_degree.setAlignment(Qt.AlignmentFlag.AlignCenter)
    container_layout.addWidget(lbl_degree)

    lbl_desc = QLabel(
        "Dibuat dengan semangat untuk menyediakan alat bantu produktivitas yang"
        " personal dan efisien. Menggabungkan kemudahan manajemen kredensial,"
        " sinkronisasi database lokal & cloud, serta perlindungan enkripsi data"
        " akun secara aman dan terintegrasi."
    )
    lbl_desc.setStyleSheet(
        "font-size: 12px; color: #616161; line-height: 1.5; margin-top: 4px;"
    )
    lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_desc.setWordWrap(True)
    container_layout.addWidget(lbl_desc)

    # 4. Tombol Kontak (LinkedIn & Email)
    btn_links_layout = QHBoxLayout()
    btn_links_layout.setSpacing(12)
    btn_links_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    btn_linkedin = QPushButton("🔗 LinkedIn")
    btn_linkedin.setStyleSheet("""
        QPushButton {
            background-color: #0077b5;
            color: white;
            font-weight: bold;
            padding: 8px 18px;
            border-radius: 6px;
            font-size: 12px;
        }
        QPushButton:hover {
            background-color: #005f93;
        }
    """)
    btn_linkedin.clicked.connect(lambda: QDesktopServices.openUrl(
        QUrl("https://linkedin.com/in/frendy-rikal-gerung-bb450b38a/")
    ))

    btn_email = QPushButton("✉️ Email")
    btn_email.setStyleSheet("""
        QPushButton {
            background-color: #d93025;
            color: white;
            font-weight: bold;
            padding: 8px 18px;
            border-radius: 6px;
            font-size: 12px;
        }
        QPushButton:hover {
            background-color: #b3261e;
        }
    """)
    btn_email.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl("mailto:frendydev1@gmail.com"))
    )

    btn_links_layout.addWidget(btn_linkedin)
    btn_links_layout.addWidget(btn_email)
    container_layout.addLayout(btn_links_layout)

    # 5. Versi Aplikasi
    lbl_version = QLabel("Versi 1.0.0 (Build 2026)")
    lbl_version.setStyleSheet(
        "font-size: 11px; color: #888888; margin-top: 10px;"
    )
    lbl_version.setAlignment(Qt.AlignmentFlag.AlignCenter)
    container_layout.addWidget(lbl_version)

    container_layout.addStretch()
    scroll_area.setWidget(container)
    return scroll_area

  # ─── Helper: Rotasi Ayat ───

  def start_verse_timer(self):
    self.verse_timer = QTimer(self)
    self.verse_timer.setInterval(15000)  # Rotasi setiap 15 detik
    self.verse_timer.timeout.connect(self._rotate_verse)
    self.verse_timer.start()

  def _rotate_verse(self):
    self.current_verse_index = (self.current_verse_index + 1) % len(self.VERSES)
    self._update_verse_display()

  def _update_verse_display(self):
    verse = self.VERSES[self.current_verse_index]
    self.lbl_verse_text.setText(verse["text"])
    self.lbl_verse_ref.setText(verse["ref"])

  # ─── Helper: Avatar Sirkular ───

  def _get_circular_pixmap(self, image_path: str, size: int) -> QPixmap:
    src_pixmap = QPixmap(image_path)
    if src_pixmap.isNull():
      return QPixmap()

    # Scale gambar ke square size
    scaled = src_pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )

    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)

    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    path = QPainterPath()
    path.addEllipse(2, 2, size - 4, size - 4)
    painter.setClipPath(path)

    # Center crop draw
    x = (scaled.width() - size) // 2
    y = (scaled.height() - size) // 2
    painter.drawPixmap(0, 0, scaled.copy(x, y, size, size))

    # Border lingkaran
    painter.setClipping(False)
    from PyQt6.QtGui import QPen, QColor
    pen = QPen(QColor("#3949ab"), 3)
    painter.setPen(pen)
    painter.drawEllipse(2, 2, size - 4, size - 4)

    painter.end()
    return out
