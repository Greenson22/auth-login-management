# 04: Facade service, status OpenCode, dan kolom "Aktif di"

**What to build:** Satu facade service menjadi satu-satunya pintu antara UI dan sistem eksternal (file, keyring, OAuth, proses). Lewat facade, aplikasi membaca akun yang benar-benar aktif di target OpenCode — dari file, bukan dari setting — lalu menampilkannya di chip ConfigBar dan kolom baru "Aktif di".

**Blocked by:** 01, 02

**Status:** completed

- [x] Facade menerima port lewat konstruktor: penyimpan akun, keyring, file `~/.gemini`, file OpenCode, OAuth, manajer proses, lingkungan, dan jam/waktu.
- [x] Facade menyediakan empat operasi: build plan, apply, read status, restore last backup. Implementasi apply/restore boleh belum berfungsi pada tiket ini, tetapi bentuk operasinya sudah ada.
- [x] Terdapat perakitan produksi (port Linux/D-Bus, file nyata, OAuth nyata) dan perakitan test memakai fake untuk port yang sama.
- [x] `read status` OpenCode menentukan akun aktif dari `activeIndex`, dengan fallback `activeIndexByFamily.gemini` bila `activeIndex` tidak ada.
- [x] `read status` mengembalikan email aktif, kondisi (`active`, `none`, `unrecorded`, `invalid_file`, `error`), dan pesan pendek; file hilang atau JSON rusak dilaporkan sebagai kondisi, bukan exception.
- [x] `read status` tidak pernah melempar exception ke UI; kegagalan port dikembalikan sebagai status dengan field error.
- [x] Chip Target menampilkan ikon kondisi dan email aktif (ter-elide) untuk OpenCode, dengan tooltip memuat teks penuh, email, dan kondisi.
- [x] Tabel memiliki 7 kolom berurutan: Email, Kategori, Aktif di, Status Enkripsi, Flash Quota, Pro Quota, Claude Quota; kolom "Aktif di" memakai `ResizeToContents` dengan lebar maksimum sekitar 110 px.
- [x] Baris pemisah kategori di-span ke 7 kolom.
- [x] Kolom "Aktif di" berisi `OpenCode` untuk akun yang emailnya cocok case-insensitive dengan akun aktif target, dan `—` bila tidak.
- [x] Filter kategori, pemisah grup, sortir, dan status enkripsi tetap berperilaku sama.
- [x] Pemuatan ulang akun menjalankan query ringkasan DB dan `read status` dalam satu worker task; kegagalan status tidak menggagalkan pemuatan tabel.

---

## Catatan implementasi

**Waktu build:** 2026-11-21 14:31 WITA

**Ringkasan perubahan:**

1. **Paket Integrasi & Port Seams (`src/integrations/antigravity/`):**
   - `ports.py`: Mendefinisikan kontrak protocol port (`AccountStoragePort`, `KeyringPort`, `GeminiFilesPort`, `OpenCodeFilePort`, `OAuthPort`, `ProcessManagerPort`, `EnvironmentPort`, `ClockPort`) serta dataclass model (`ApplyPlan`, `ApplyResult`, `TargetStatus`, `OverallStatus`, `RestoreResult`) dan enum (`ApplyStatus`, `TargetCondition`).
   - `service.py`: Mengimplementasikan `AntigravityFacade` dengan 4 operasi (`build_plan`, `apply`, `read_status`, `restore_last_backup`) serta helper `compute_active_di()`. Membaca status OpenCode dari file `antigravity-accounts.json` melalui `activeIndex` (fallback `activeIndexByFamily.gemini`), mendeteksi kondisi `active`, `none`, `unrecorded`, `invalid_file`, `error` tanpa pernah melempar exception ke UI.
   - `opencode_file.py`: Adaptor nyata `RealOpenCodeFilePort` untuk membaca dan menulis atomic file konfigurasi OpenCode dengan izin mode `0600`.
   - `factory.py`: Perakitan produksi `create_facade(db, folder_provider)` yang menginjeksi port nyata (storage DB, clock, env Linux/D-Bus, file OpenCode).
   - `constants.py` & `errors.py`: Konstanta identitas OAuth dan hierarki exception integrasi.

2. **Pembaruan UI Komponen:**
   - `src/ui/components/target_badge.py`: Menambahkan method `set_status(status)` untuk menampilkan indikator visual kondisi sesuai matriks status PRD §13 (`🟢 email`, `🟡 Tidak tercatat`, `🔴 File tidak valid`, dsb.), elide adaptif saat sempit, serta tooltip lengkap dengan email aktif dan kondisi.
   - `src/ui/components/config_bar.py`: Menambahkan `set_target_status(status)` untuk meneruskan pembaruan status ke chip `TargetBadge`.
   - `src/ui/components/account_table.py`:
     - Memperluas tabel menjadi 7 kolom dengan urutan: `Email`, `Kategori`, `Aktif di`, `Status Enkripsi`, `Flash Quota`, `Pro Quota`, `Claude Quota`.
     - Kolom "Aktif di" (indeks 2) dikonfigurasi `ResizeToContents` dengan lebar maksimum 110 px.
     - Baris pemisah kategori disesuaikan melakukan span penuh ke 7 kolom.
     - Menghitung nilai kolom "Aktif di" case-insensitive dari status keterpasangan akun.
     - Menjaga filter kategori, pemisah grup, sortir, dan status enkripsi tetap bekerja identik seperti sebelumnya.
   - `src/ui/main_window.py`:
     - Menginisialisasi `self.facade` melalui perakitan produksi `create_facade`.
     - Mengintegrasikan query ringkasan DB dan `read status` dalam satu worker task pada `reload_accounts()`, dengan penanganan fail-safe sehingga kegagalan pembacaan status tidak menggagalkan pemuatan tabel.
     - Memperbarui status chip target secara reaktif saat target diganti.

3. **Pengujian (`tests/test_facade_and_opencode_status.py`):**
   - Menambahkan 13 skenario pengujian komprehensif: injeksi port konstruktor, keberadaan 4 operasi, perakitan test/produksi, pembacaan `activeIndex`, fallback `activeIndexByFamily.gemini`, deteksi akun `unrecorded`, penanganan file hilang/rusak (`invalid_file`), jaminan anti-exception port error, logika per-email `compute_active_di`, 7 kolom tabel dengan batasan lebar 110 px, span pemisah kategori ke 7 kolom, pengisian nilai "Aktif di", serta tampilan badge chip target.
   - Seluruh suite pytest (51 passed, 2 skipped) berhasil tanpa regresi.
