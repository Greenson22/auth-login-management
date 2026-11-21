# 05: Apply ke OpenCode end-to-end

**What to build:** Pengguna bisa menerapkan satu akun ke target OpenCode lewat klik kanan atau double-click. Akun baru ditambahkan tanpa menghapus akun lain, entri dengan email sama diganti di tempat, `activeIndex` menunjuk akun yang baru, backup dibuat sebelum menulis, dan file ditulis atomic dengan mode `0600`. Apply OpenCode tidak pernah menyentuh keyring atau proses `agy`.

**Blocked by:** 03, 04

**Status:** completed

- [x] Build plan gagal — sebelum backup dan penulisan — bila folder target tidak valid, file tidak ada, isinya bukan objek JSON, atau `accounts` bukan array.
- [x] File berisi 3 akun lalu Apply akun ke-4 menghasilkan 4 akun; akun lama utuh, akun baru berada di akhir.
- [x] Email yang sudah ada dengan kapitalisasi berbeda menggantikan entri lama di posisi yang sama, tanpa duplikat.
- [x] Snapshot akun diambil dari rekonstruksi DB, bukan dengan menulis konfigurasi hasil rekonstruksi satu akun apa adanya.
- [x] `activeIndex` menunjuk indeks hasil upsert; `activeIndexByFamily.gemini` dan `.claude` diubah hanya bila kuncinya sudah ada, dan kunci yang tidak ada tidak dibuat.
- [x] Field top-level lain (misalnya `version`) dan seluruh akun lain dipertahankan.
- [x] Backup file lama dibuat sebelum penulisan; kegagalan plan tidak menghasilkan backup.
- [x] Penulisan atomic lewat file sementara di direktori yang sama + `os.replace`, mode `0600`, tanpa mengikuti symlink.
- [x] Apply sukses menandai DB `applied_target='opencode'` dan `last_applied_at` waktu epoch detik.
- [x] Dialog sukses standar menampilkan email dan jumlah akun di file.
- [x] Apply OpenCode tidak memanggil port proses maupun keyring, dan tidak membaca/menulis `~/.gemini`.
- [x] Menu konteks akun memiliki submenu "Terapkan ke…" berisi OpenCode dan Antigravity CLI; item CLI disabled dengan alasan saat target tidak tersedia.
- [x] Double-click pada baris akun menjalankan Apply ke Selected Target; tidak ada tombol Apply baru di toolbar.

---

### Catatan Implementasi & Waktu Build

- **Waktu Selesai Build:** `2026-11-21T14:42:36+08:00`
- **Modul yang dibangun & diperbarui:**
  1. `src/integrations/antigravity/backup.py`: Modul pembuatan backup otomatis ke `~/.local/state/auth-login-management/backups/<timestamp>/` dengan mode direktori `0700`, mode file `0600`, manifes `meta.json`, serta retensi 30 backup terbaru.
  2. `src/integrations/antigravity/opencode_file.py`: Penulisan atomic via file temporer di direktori yang sama (`os.replace`, mode `0600`) serta pencegahan penulisan dan pembacaan melalui symlink (`is_symlink()`).
  3. `src/integrations/antigravity/service.py`:
     - `build_plan`: Preflight validasi keberadaan folder/file, tipe data objek JSON, dan pemeriksaan array `accounts`. Gagal sebelum backup/penulisan bila file hilang atau tidak valid.
     - `apply` / `_apply_opencode`: Snapshot backup pra-tulis, upsert akun (case-insensitive email matching, pertahankan posisi bila sudah ada atau append di akhir jika baru), perbarui `activeIndex` dan `activeIndexByFamily` (`.gemini` dan `.claude` diperbarui hanya jika sudah ada kuncinya), penulisan atomic mode 0600, dan penandaan audit ke database (`applied_target='opencode'` & `last_applied_at` epoch detik).
     - Isolasi port: Apply OpenCode terisolasi sepenuhnya dari keyring, proses `agy`, dan `~/.gemini`.
  4. `src/ui/components/account_table.py`:
     - Penambahan submenu konteks "Terapkan ke…" berisi OpenCode dan Antigravity CLI (dengan pemeriksaan availability CLI dari status target).
     - Handler double-click pada baris akun untuk langsung memicu Apply ke Selected Target tanpa tombol toolbar tambahan.
  5. `src/ui/main_window.py`: Wiring sinyal `apply_requested` ke `apply_account_to_target` dengan eksekusi background `WorkerThread` dan dialog informasi/peringatan standar.
  6. `tests/test_apply_opencode.py`: 7 skenario pengujian komprehensif yang memverifikasi seluruh kriteria tiket 05. Seluruh 60 test di test suite lulus (58 passed, 2 skipped integration).
