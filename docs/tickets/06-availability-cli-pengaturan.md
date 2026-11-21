# 06: Availability Antigravity CLI dan grup Pengaturan Integrasi

**What to build:** Target Antigravity CLI hanya ditawarkan saat lingkungan memang mendukung, dan saat tidak mendukung pengguna melihat alasannya alih-alih mencoba aksi yang pasti gagal. Pengaturan mendapat dua saklar integrasi yang tersimpan.

**Blocked by:** 02, 04

**Status:** done

- [x] Availability OpenCode selalu tersedia; validasi folder/file baru dilakukan saat build plan.
- [x] Availability Antigravity CLI hanya benar bila OS Linux, Secret Service/D-Bus dapat dihubungi, keyring dapat dibuka, dan aplikasi bukan root.
- [x] Alasan tidak tersedia dikembalikan sebagai kode + teks: `unsupported_os`, `no_dbus`, `keyring_locked`, `root`, `dbus_error`.
- [x] Menu target tetap menampilkan Antigravity CLI dalam keadaan disabled dengan alasan di tooltip.
- [x] Availability diperiksa ulang setiap kali menu dibuka, sehingga keyring yang baru dibuka pengguna langsung terdeteksi tanpa restart.
- [x] Item Antigravity CLI di submenu "Terapkan ke…" juga disabled dengan alasan yang sama.
- [x] Di OS non-Linux adapter keyring memakai implementasi null yang selalu melaporkan tidak tersedia; aplikasi tetap berjalan penuh untuk OpenCode.
- [x] Pengaturan memiliki grup "Integrasi" berisi `auto_kill_agy` (default mati) dan `write_gemini_files` (default aktif), keduanya memuat dan menyimpan nilai dengan benar.
- [x] Tidak ada tombol impor file lama pada v1.0.

---

## Catatan implementasi

**Waktu build:** 2026-11-21 14:48 WITA

**Ringkasan perubahan:**

- `src/integrations/antigravity/factory.py` — Menambahkan:
  * `_ensure_dbus_importable()` dan `_try_import_dbus()` — fallback ke system path (`/usr/lib/python3/dist-packages`) agar `python3-dbus` dapat dipakai dari dalam virtualenv.
  * `ProductionEnvironmentPort.is_keyring_locked()` — implementasi nyata via D-Bus: membaca properti `Locked` dari seluruh koleksi Secret Service; True hanya bila ada koleksi dan semuanya terkunci.
  * `ProductionEnvironmentPort.is_dbus_available()` — verifikasi penuh: import dbus, buka SessionBus, panggil `OpenSession` ke Secret Service.
  * `NullKeyringPort` — port keyring null untuk OS non-Linux: `read()` selalu `None`, `write()` melempar `RuntimeError`, `delete()` tidak melakukan apa-apa.
  * `ProductionKeyringPort.read()` — implementasi nyata membaca item `service/username` via D-Bus Secret Service.
  * `check_cli_availability()` — fungsi publik yang mengembalikan `(available: bool, reason_code: str)` tanpa melempar exception; dipanggil UI saat menu dibuka.
  * `create_facade()` — memilih `NullKeyringPort` di OS non-Linux secara otomatis.

- `src/ui/components/target_badge.py` — Menambahkan:
  * `_UNAVAIL_REASON_TEXT` — kamus kode → teks ramah pengguna.
  * `_get_cli_unavailable_reason()` — memanggil `check_cli_availability()`, dikembalikan sebagai kode atau `None`.
  * `_on_menu_about_to_show()` — slot yang terhubung ke sinyal `menu.aboutToShow`; recheck availability setiap kali menu dibuka.
  * `_apply_cli_availability(reason)` — nonaktifkan/aktifkan item CLI dan setel tooltip alasan.
  * Import `TARGET_ANTIGRAVITY_CLI` untuk dapat merujuk item menu CLI.

- `src/ui/components/settings_dialog.py` — Menambahkan grup "Integrasi" berisi:
  * `chk_auto_kill_agy` — checkbox default unchecked, key `auto_kill_agy`.
  * `chk_write_gemini_files` — checkbox default checked, key `write_gemini_files`.
  * Load di `load_settings()` dengan penanganan nilai string dari QSettings.
  * Save di `_save_settings()` setelah nilai Turso.
  * Tidak ada tombol impor file lama.

- `tests/test_availability_cli_pengaturan.py` — 25 test baru:
  * Availability per kondisi (Linux, root, D-Bus, keyring locked, semua OK).
  * `NullKeyringPort` behavior.
  * `check_cli_availability()` dengan mock setiap kondisi.
  * `TargetBadge`: item CLI disabled + tooltip, item OpenCode selalu enabled, `aboutToShow` memanggil ulang recheck.
  * `SettingsDialog`: default values, load saved values, save ke QSettings, tidak ada tombol impor.

**Keputusan teknis:**

- `python3-dbus` adalah dependensi sistem opsional; jika tidak tersedia di venv, `_try_import_dbus()` mencoba jalur sistem dan mengembalikan `None` jika tetap tidak ditemukan.
- `is_keyring_locked()` mengembalikan `False` (bukan `True`) bila D-Bus error — agar `is_dbus_available()` yang melaporkan ketidaktersediaan lebih dulu tanpa double-report.
- Recheck availability dilakukan lewat sinyal `menu.aboutToShow` sehingga keyring yang baru dibuka pengguna di seahorse langsung terdeteksi pada buka-menu berikutnya, tanpa polling dan tanpa restart.
- `NullKeyringPort` dipilih di `create_facade()` berdasarkan `env_port.is_linux()`, memastikan OS check hanya dilakukan satu kali saat startup.

**Test:** 83 passed, 2 skipped (integration opt-in). Tidak ada regresi dari tiket sebelumnya.
