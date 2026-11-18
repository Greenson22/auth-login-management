# 04: Facade service, status OpenCode, dan kolom "Aktif di"

**What to build:** Satu facade service menjadi satu-satunya pintu antara UI dan sistem eksternal (file, keyring, OAuth, proses). Lewat facade, aplikasi membaca akun yang benar-benar aktif di target OpenCode — dari file, bukan dari setting — lalu menampilkannya di chip ConfigBar dan kolom baru "Aktif di".

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Facade menerima port lewat konstruktor: penyimpan akun, keyring, file `~/.gemini`, file OpenCode, OAuth, manajer proses, lingkungan, dan jam/waktu.
- [ ] Facade menyediakan empat operasi: build plan, apply, read status, restore last backup. Implementasi apply/restore boleh belum berfungsi pada tiket ini, tetapi bentuk operasinya sudah ada.
- [ ] Terdapat perakitan produksi (port Linux/D-Bus, file nyata, OAuth nyata) dan perakitan test memakai fake untuk port yang sama.
- [ ] `read status` OpenCode menentukan akun aktif dari `activeIndex`, dengan fallback `activeIndexByFamily.gemini` bila `activeIndex` tidak ada.
- [ ] `read status` mengembalikan email aktif, kondisi (`active`, `none`, `unrecorded`, `invalid_file`, `error`), dan pesan pendek; file hilang atau JSON rusak dilaporkan sebagai kondisi, bukan exception.
- [ ] `read status` tidak pernah melempar exception ke UI; kegagalan port dikembalikan sebagai status dengan field error.
- [ ] Chip Target menampilkan ikon kondisi dan email aktif (ter-elide) untuk OpenCode, dengan tooltip memuat teks penuh, email, dan kondisi.
- [ ] Tabel memiliki 7 kolom berurutan: Email, Kategori, Aktif di, Status Enkripsi, Flash Quota, Pro Quota, Claude Quota; kolom "Aktif di" memakai `ResizeToContents` dengan lebar maksimum sekitar 110 px.
- [ ] Baris pemisah kategori di-span ke 7 kolom.
- [ ] Kolom "Aktif di" berisi `OpenCode` untuk akun yang emailnya cocok case-insensitive dengan akun aktif target, dan `—` bila tidak.
- [ ] Filter kategori, pemisah grup, sortir, dan status enkripsi tetap berperilaku sama.
- [ ] Pemuatan ulang akun menjalankan query ringkasan DB dan `read status` dalam satu worker task; kegagalan status tidak menggagalkan pemuatan tabel.
