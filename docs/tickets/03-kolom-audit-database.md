# 03: Kolom audit database dan migrasi aditif

**What to build:** Database menyimpan jejak audit ringan per akun — target terakhir yang dipakai untuk Apply dan waktunya — tanpa merusak data, indeks kolom tabel, kategori, atau kuota yang sudah ada. Migrasi berjalan otomatis dan idempoten di SQLite maupun Turso.

**Blocked by:** 01

**Status:** completed

- [x] Tabel `accounts` mendapat kolom `applied_target TEXT NULL` dan `last_applied_at INTEGER NULL`.
- [x] Migrasi idempoten: pada SQLite kolom dicek lewat `PRAGMA table_info`; pada Turso error "duplicate column" diabaikan. Dijalankan dua kali tetap aman.
- [x] Migrasi berhasil pada database kosong maupun database lama yang sudah berisi akun, kategori, dan kuota.
- [x] Query ringkasan akun mengembalikan dua kolom baru di akhir hasil sehingga indeks lama 0–10 tidak bergeser.
- [x] Tersedia operasi penandaan audit yang menyimpan target kanonik dan waktu epoch detik UTC.
- [x] Tersedia operasi pembaruan refresh token hasil rotasi yang menghormati status enkripsi akun (terenkripsi tetap terenkripsi, plaintext tetap plaintext).
- [x] Penandaan audit tidak mengubah kategori, data kuota, maupun tabel `account_fingerprints`.

## Catatan Implementasi & Waktu Build

- **Waktu Build:** 2026-11-21T14:18:36+08:00
- **Modul Diubah:**
  - `src/database.py`:
    - Menambahkan kolom `applied_target TEXT NULL` dan `last_applied_at INTEGER NULL` ke skema pembuatan tabel `accounts`.
    - Menambahkan migrasi aditif idempoten pada `init_db()`: pemeriksaan `PRAGMA table_info(accounts)` untuk SQLite dan penanganan exception alter table untuk Turso.
    - Menyesuaikan query `fetch_accounts_summary` untuk mengembalikan dua kolom audit di akhir hasil (indeks 11 dan 12), menjaga kompatibilitas indeks lama 0–10.
    - Menyesuaikan `reconstruct_json_by_id` agar menyertakan `appliedTarget` dan `lastAppliedAt` pada objek akun yang direkonstruksi.
    - Menambahkan method `mark_applied(account_id, target, applied_at=None)` untuk mencatat target kanonik (`opencode` / `antigravity_cli`) dan epoch detik UTC.
    - Menambahkan method `update_refresh_token(account_id, new_refresh_token, password="")` untuk memperbarui refresh token hasil rotasi secara aman dengan tetap menghormati status akun (`is_encrypted`).
- **Pengujian:**
  - Menambahkan rangkaian unit test komprehensif di `tests/test_database_audit.py` (8 test skenario: migrasi database baru, migrasi idempoten 2x, migrasi database legacy dengan data, integritas indeks summary, penandaan audit kanonik & waktu epoch, pengawetan kuota/kategori/fingerprint, rotasi refresh token plaintext, serta rotasi refresh token terenkripsi).
  - Seluruh 38 test otomatis di suite pytest berhasil (passed).

