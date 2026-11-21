# 07: Pengelolaan sesi `agy`

**What to build:** Sebelum menulis kredensial CLI, aplikasi mendeteksi sesi `agy` yang masih hidup, memberi tahu pengguna PID/state/perintahnya, dan menghentikannya dengan urutan sinyal yang aman. Pengguna bisa membatalkan, dan aplikasi tidak pernah menulis selama sesi lama masih hidup.

**Blocked by:** 04, 06

**Status:** completed

- [x] Deteksi Linux membaca `/proc/<pid>/cmdline`, mengambil basename argumen pertama, dan mencocokkan persis `agy`; nama `antigravity` tidak lagi dicocokkan.
- [x] `agy remote-control` terdeteksi dan diberi label khusus.
- [x] PID aplikasi sendiri dan parent-nya dikecualikan; proses milik user lain tidak disentuh.
- [x] State dibaca dari `/proc/<pid>/stat`: `R`/`S`/`D` hidup, `T`/`t` stopped, `Z` zombie.
- [x] Zombie tidak dianggap hidup, tidak memblokir Apply, dan dilaporkan sebagai sisa.
- [x] Stopped dianggap hidup dan menerima `SIGCONT` sebelum `SIGTERM`.
- [x] `/proc` tidak bisa dibaca (sandbox/Flatpak) menggagalkan plan dengan pesan "periksa proses manual", tanpa penulisan.
- [x] Build plan memasukkan daftar sesi ke dalam plan; tanpa sesi hidup → siap; ada sesi hidup dan `auto_kill_agy` mati → `requires_confirmation`; `auto_kill_agy` hidup → boleh kill tanpa dialog.
- [x] Apply tanpa izin kill saat ada sesi hidup gagal tanpa menulis.
- [x] State machine berjalan: `SIGCONT` → `SIGTERM` (poll 100 ms, maks 3000 ms) → `SIGKILL` (poll 100 ms, maks 2000 ms); masih hidup setelah itu → gagal tanpa penulisan.
- [x] Sebelum setiap kill, `cmdline` diverifikasi ulang untuk menutup race PID reuse.
- [x] `ProcessLookupError` dianggap sudah mati; `PermissionError` menandai PID gagal tanpa dipaksa.
- [x] Proses `D` yang tidak bisa dibunuh setelah timeout menghasilkan kegagalan dengan saran menutup manual.
- [x] Pesan gagal menyebut PID yang perlu ditutup manual, perintah `pkill -9 -x agy` untuk disalin manual, dan penegasan tidak ada perubahan tertulis.
- [x] Dialog konfirmasi berukuran tetap sekitar 480×320, memuat PID, state, dan perintah dalam daftar yang bisa di-scroll; Batal fokus default; tombol hentikan ditandai destruktif; checkbox "Jangan tanya lagi" menulis `auto_kill_agy=true`.
- [x] Progres penghentian dan penantian berjalan di worker thread dengan dialog progres yang bisa dibatalkan; membatalkan hanya menghentikan penantian, tidak mengirim sinyal tambahan, dan Apply berakhir `CANCELLED` tanpa penulisan.
- [x] UI tetap responsif sampai batas waktu 3–5 detik; test memakai jam palsu dan tidak benar-benar menunggu.
- [x] Tooltip chip target memuat ringkasan sesi `agy` (jumlah hidup/stopped/zombie).
- [x] Log hanya berisi PID, state, sinyal, dan hasil; tidak pernah token.

---

### Catatan Implementasi & Waktu Build

- **Waktu Selesai Build / Pengujian:** 2026-11-21T15:08:30+08:00
- **Modul yang dibangun:**
  - `src/integrations/antigravity/process.py`: Implementasi `LinuxProcessManager` membaca `/proc`, mendeteksi hanya basename `agy`, melabeli `remote-control`, mengabaikan zombie, mengecualikan PID sendiri & parent, membaca state dari `stat`, dan state machine sinyal bertahap `SIGCONT` -> `SIGTERM` (3000 ms max) -> `SIGKILL` (2000 ms max) dengan verifikasi ulang `cmdline` (PID reuse guard).
  - `src/integrations/antigravity/service.py`: Integrasi deteksi sesi ke `build_plan` dan `apply`. Jika ada sesi hidup dan `auto_kill_agy=False` mengembalikan `requires_confirmation=True`. Apply tanpa `allow_kill` menolak penulisan. Mengintegrasikan ringkasan sesi (`alive`, `stopped`, `zombie`) ke `read_status` untuk tooltip target.
  - `src/integrations/antigravity/factory.py`: Menghubungkan `ProductionProcessManagerPort` dengan implementasi `LinuxProcessManager`.
  - `src/ui/components/agy_session_dialog.py`: Dialog konfirmasi berukuran tetap 480×320 dengan daftar sesi scrollable, default fokus Batal, tombol destruktif Hentikan Sesi, checkbox persistensi `auto_kill_agy=True`, dan `KillWorkerThread`.
  - `tests/test_agy_session_management.py`: Pengujian unit dan widget komprehensif (11 test cases) menggunakan jam palsu dan tabel proses in-memory.
- **Hasil Verifikasi:**
  - `tests/test_agy_session_management.py`: 11 passed (0.34s)
  - `tests/integration/test_real_process.py`: 1 passed (0.08s)
  - Seluruh test suite: 94 passed, 2 skipped (3.02s)
