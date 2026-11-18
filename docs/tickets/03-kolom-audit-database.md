# 03: Kolom audit database dan migrasi aditif

**What to build:** Database menyimpan jejak audit ringan per akun — target terakhir yang dipakai untuk Apply dan waktunya — tanpa merusak data, indeks kolom tabel, kategori, atau kuota yang sudah ada. Migrasi berjalan otomatis dan idempoten di SQLite maupun Turso.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Tabel `accounts` mendapat kolom `applied_target TEXT NULL` dan `last_applied_at INTEGER NULL`.
- [ ] Migrasi idempoten: pada SQLite kolom dicek lewat `PRAGMA table_info`; pada Turso error "duplicate column" diabaikan. Dijalankan dua kali tetap aman.
- [ ] Migrasi berhasil pada database kosong maupun database lama yang sudah berisi akun, kategori, dan kuota.
- [ ] Query ringkasan akun mengembalikan dua kolom baru di akhir hasil sehingga indeks lama 0–10 tidak bergeser.
- [ ] Tersedia operasi penandaan audit yang menyimpan target kanonik dan waktu epoch detik UTC.
- [ ] Tersedia operasi pembaruan refresh token hasil rotasi yang menghormati status enkripsi akun (terenkripsi tetap terenkripsi, plaintext tetap plaintext).
- [ ] Penandaan audit tidak mengubah kategori, data kuota, maupun tabel `account_fingerprints`.
