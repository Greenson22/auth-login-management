# 07: Pengelolaan sesi `agy`

**What to build:** Sebelum menulis kredensial CLI, aplikasi mendeteksi sesi `agy` yang masih hidup, memberi tahu pengguna PID/state/perintahnya, dan menghentikannya dengan urutan sinyal yang aman. Pengguna bisa membatalkan, dan aplikasi tidak pernah menulis selama sesi lama masih hidup.

**Blocked by:** 04, 06

**Status:** ready-for-agent

- [ ] Deteksi Linux membaca `/proc/<pid>/cmdline`, mengambil basename argumen pertama, dan mencocokkan persis `agy`; nama `antigravity` tidak lagi dicocokkan.
- [ ] `agy remote-control` terdeteksi dan diberi label khusus.
- [ ] PID aplikasi sendiri dan parent-nya dikecualikan; proses milik user lain tidak disentuh.
- [ ] State dibaca dari `/proc/<pid>/stat`: `R`/`S`/`D` hidup, `T`/`t` stopped, `Z` zombie.
- [ ] Zombie tidak dianggap hidup, tidak memblokir Apply, dan dilaporkan sebagai sisa.
- [ ] Stopped dianggap hidup dan menerima `SIGCONT` sebelum `SIGTERM`.
- [ ] `/proc` tidak bisa dibaca (sandbox/Flatpak) menggagalkan plan dengan pesan "periksa proses manual", tanpa penulisan.
- [ ] Build plan memasukkan daftar sesi ke dalam plan; tanpa sesi hidup → siap; ada sesi hidup dan `auto_kill_agy` mati → `requires_confirmation`; `auto_kill_agy` hidup → boleh kill tanpa dialog.
- [ ] Apply tanpa izin kill saat ada sesi hidup gagal tanpa menulis.
- [ ] State machine berjalan: `SIGCONT` → `SIGTERM` (poll 100 ms, maks 3000 ms) → `SIGKILL` (poll 100 ms, maks 2000 ms); masih hidup setelah itu → gagal tanpa penulisan.
- [ ] Sebelum setiap kill, `cmdline` diverifikasi ulang untuk menutup race PID reuse.
- [ ] `ProcessLookupError` dianggap sudah mati; `PermissionError` menandai PID gagal tanpa dipaksa.
- [ ] Proses `D` yang tidak bisa dibunuh setelah timeout menghasilkan kegagalan dengan saran menutup manual.
- [ ] Pesan gagal menyebut PID yang perlu ditutup manual, perintah `pkill -9 -x agy` untuk disalin manual, dan penegasan tidak ada perubahan tertulis.
- [ ] Dialog konfirmasi berukuran tetap sekitar 480×320, memuat PID, state, dan perintah dalam daftar yang bisa di-scroll; Batal fokus default; tombol hentikan ditandai destruktif; checkbox "Jangan tanya lagi" menulis `auto_kill_agy=true`.
- [ ] Progres penghentian dan penantian berjalan di worker thread dengan dialog progres yang bisa dibatalkan; membatalkan hanya menghentikan penantian, tidak mengirim sinyal tambahan, dan Apply berakhir `CANCELLED` tanpa penulisan.
- [ ] UI tetap responsif sampai batas waktu 3–5 detik; test memakai jam palsu dan tidak benar-benar menunggu.
- [ ] Tooltip chip target memuat ringkasan sesi `agy` (jumlah hidup/stopped/zombie).
- [ ] Log hanya berisi PID, state, sinyal, dan hasil; tidak pernah token.
