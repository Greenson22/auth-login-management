# SPEC — Integrasi Target OpenCode & Antigravity CLI

| Field | Nilai |
| --- | --- |
| Status | Siap implementasi (v1.0) |
| Sumber | `docs/PRD.md` v0.2 |
| Project | `auth-login-management` |
| Tanggal | 2026-11-19 |
| Cakupan | FR-01…FR-10, FR-13, FR-15, FR-16…FR-18 |
| Ditunda ke v1.1 | FR-11 (banner drift + Adopsi), FR-12 (impor file lama), FR-14 (salin perintah verifikasi) |

> Spesifikasi ini adalah turunan langsung PRD v0.2. Istilah domain mengikuti glosarium PRD §5.
> Detail teknis PRD §10 (daftar modul dan path) tetap menjadi rujukan struktur; dokumen ini
> menetapkan perilaku, batas modul, dan cara pengujiannya.

---

## Problem Statement

Pengguna menyimpan banyak akun Google di aplikasi, tetapi akun yang sama dipakai oleh dua
tempat berbeda: OpenCode (file `antigravity-accounts.json`) dan Antigravity CLI `agy`
(kredensial di GNOME Keyring, bukan di file). Saat ini aplikasi hanya bisa menulis ke file
OpenCode, dan cara menulisnya menimpa seluruh isi file sehingga akun lain hilang. Tidak ada
cara menerapkan akun ke CLI sama sekali, padahal menghapus `~/.gemini` atau mengedit
`oauth_creds.json` tidak mengganti akun CLI karena token sebenarnya ada di keyring.

Pengguna juga tidak tahu akun mana yang benar-benar sedang aktif. Indikator yang ada hanya
menunjukkan folder, database, dan status enkripsi. Akibatnya pengguna bisa mengira sudah
berganti akun padahal CLI masih memakai akun lama, atau sebaliknya. Mengganti token saat sesi
`agy` masih berjalan berbahaya karena proses itu dapat menulis ulang token lama ke keyring.

## Solution

Tambahkan konsep **Target** global yang dapat dipilih pengguna: `OpenCode` atau
`Antigravity CLI`. Pilihan disimpan dan bertahan antar sesi, ditampilkan sebagai chip di
ConfigBar, dan setiap akun di tabel mendapat kolom **“Aktif di”** yang dibaca dari kenyataan
(file/keyring), bukan dari setting.

Satu aksi **Apply** menerapkan akun terpilih ke target aktif. Apply ke OpenCode memakai
upsert sehingga akun lain tetap utuh, memperbarui `activeIndex`, dan membuat backup sebelum
menulis. Apply ke Antigravity CLI memvalidasi refresh token ke Google lebih dulu, menangani
proses `agy` yang masih hidup secara eksplisit (konfirmasi, `SIGCONT` → `SIGTERM` → `SIGKILL`,
verifikasi ulang), membuat snapshot, menulis keyring dan `~/.gemini` secara atomic, lalu
memverifikasi hasilnya. Kegagalan pada langkah mana pun memicu rollback otomatis, dan tidak
pernah ada penulisan keyring selama sesi `agy` masih hidup.

Semua fitur baru masuk ke elemen UI yang sudah ada: tanpa toolbar baru, tanpa dialog
bertumpuk, dan ukuran window default tetap 1100×700.

## User Stories

### Memilih target

1. Sebagai pengguna, saya ingin memilih target `OpenCode` atau `Antigravity CLI` dari ConfigBar, agar saya tidak perlu mengingat target mana yang sedang dipakai.
2. Sebagai pengguna, saya ingin pilihan target tersimpan setelah aplikasi ditutup, agar saya tidak memilih ulang setiap kali membuka aplikasi.
3. Sebagai pengguna, saya ingin chip target langsung berubah saat pilihan diganti, agar saya mendapat konfirmasi visual seketika.
4. Sebagai pengguna, saya ingin mengganti target tidak mengubah kredensial apa pun, agar memilih target terasa aman dan bukan aksi destruktif.
5. Sebagai pengguna Linux, saya ingin target Antigravity CLI tampil aktif, agar saya bisa menerapkan akun ke CLI.
6. Sebagai pengguna Windows/macOS, saya ingin target Antigravity CLI tampil nonaktif beserta alasannya, agar saya tidak mencoba aksi yang belum didukung.
7. Sebagai pengguna tanpa D-Bus atau dengan keyring terkunci, saya ingin melihat alasan target CLI tidak tersedia, agar saya tahu apa yang harus diperbaiki.
8. Sebagai pengguna yang menjalankan aplikasi sebagai root, saya ingin target CLI dinonaktifkan dengan peringatan, agar saya tidak menulis ke keyring milik user yang salah.

### Indikator status

9. Sebagai pengguna, saya ingin melihat target aktif di ConfigBar tanpa membuka menu, agar saya selalu tahu ke mana Apply akan diarahkan.
10. Sebagai pengguna, saya ingin melihat akun yang benar-benar terpasang di target, agar indikator tidak hanya mengulang setting.
11. Sebagai pengguna, saya ingin chip menampilkan email aktif bila akun itu ada di database, agar saya bisa mencocokkan target dengan daftar akun.
12. Sebagai pengguna, saya ingin chip menandai akun yang aktif di target tetapi tidak tercatat di database, agar saya tahu ada akun “liar”.
13. Sebagai pengguna, saya ingin chip menandai file OpenCode yang hilang atau rusak, agar saya tahu target sedang tidak sehat.
14. Sebagai pengguna, saya ingin chip menandai keyring yang kosong, terkunci, atau tidak sinkron dengan `~/.gemini`, agar saya bisa membedakan “belum login” dari “rusak”.
15. Sebagai pengguna, saya ingin kolom “Aktif di” menampilkan `OpenCode`, `Antigravity CLI`, atau `—` per akun, agar status terlihat langsung di baris yang relevan.
16. Sebagai pengguna, saya ingin akun yang aktif di kedua target ditampilkan sebagai `OpenCode + CLI`, agar saya tidak kehilangan informasi.
17. Sebagai pengguna, saya ingin status dibaca ulang setiap kali daftar akun dimuat dan setelah setiap Apply, agar perubahan dari terminal ikut terlihat.
18. Sebagai pengguna, saya ingin tooltip chip menampilkan detail status dan sesi `agy`, agar informasi tambahan tidak memakan ruang layout.
19. Sebagai pengguna, saya ingin melihat selisih antara keyring dan `~/.gemini` sebagai peringatan, agar saya tahu bila dua sumber tidak sinkron.

### Apply ke OpenCode

20. Sebagai pengguna, saya ingin menerapkan akun ke OpenCode lewat klik kanan pada baris akun, agar aksi cepat dijangkau tanpa tombol toolbar baru.
21. Sebagai pengguna, saya ingin Apply ke OpenCode menambahkan akun baru tanpa menghapus akun lain di file, agar koleksi akun saya tetap utuh.
22. Sebagai pengguna, saya ingin Apply ke akun yang emailnya sudah ada menggantikan entri itu saja, agar tidak muncul duplikat.
23. Sebagai pengguna, saya ingin `activeIndex` dan `activeIndexByFamily` menunjuk akun yang baru diterapkan, agar OpenCode langsung memakai akun tersebut.
24. Sebagai pengguna, saya ingin backup file OpenCode dibuat sebelum penulisan, agar saya bisa kembali ke kondisi sebelumnya.
25. Sebagai pengguna, saya ingin file ditulis secara atomic dan hanya bisa dibaca pemilik, agar file tidak korup saat aplikasi berhenti mendadak.
26. Sebagai pengguna, saya ingin field lain di file OpenCode yang tidak saya sentuh tetap dipertahankan, agar konfigurasi versi dan data lain tidak hilang.
27. Sebagai pengguna, saya ingin Apply ke OpenCode tidak memeriksa atau menghentikan proses `agy`, agar target yang tidak berhubungan tidak terganggu.
28. Sebagai pengguna, saya ingin dialog sukses menunjukkan email dan jumlah akun di file, agar saya yakin hasilnya benar.
29. Sebagai pengguna, saya ingin Apply ke OpenCode dibatalkan bila file target tidak ada atau JSON-nya rusak, agar aplikasi tidak menimpa file yang tidak bisa dipahami.

### Apply ke Antigravity CLI

30. Sebagai pengguna, saya ingin Apply ke CLI memvalidasi refresh token ke Google sebelum menyentuh apa pun, agar token mati tidak pernah ditulis ke keyring.
31. Sebagai pengguna, saya ingin email di `id_token` dicocokkan dengan email akun, agar token milik akun lain tidak terpasang.
32. Sebagai pengguna, saya ingin pesan spesifik saat token dicabut (`invalid_grant`), agar saya tahu harus login ulang.
33. Sebagai pengguna, saya ingin keyring item `service=gemini, username=antigravity` diperbarui, agar `agy` memakai akun yang saya pilih.
34. Sebagai pengguna, saya ingin `~/.gemini/oauth_creds.json` dan `google_accounts.json` ikut disinkronkan, agar file pendamping tidak menunjuk akun lama.
35. Sebagai pengguna, saya ingin email lama di `google_accounts.json` dipertahankan di daftar `old`, agar riwayat akun tidak hilang.
36. Sebagai pengguna, saya ingin Apply ke CLI tetap berjalan bila `~/.gemini` belum ada, agar instalasi baru tidak terblokir.
37. Sebagai pengguna, saya ingin bisa mematikan penulisan `~/.gemini` lewat Pengaturan, agar saya bisa hanya memperbarui keyring.
38. Sebagai pengguna, saya ingin hasil Apply diverifikasi dengan membaca ulang keyring dan file, agar “sukses” berarti benar-benar tertulis.
39. Sebagai pengguna, saya ingin aplikasi tidak menjalankan `agy` secara otomatis setelah Apply, agar TUI tidak muncul di dalam aplikasi GUI.

### Pengelolaan sesi `agy`

40. Sebagai pengguna, saya ingin aplikasi mendeteksi sesi `agy` yang masih hidup sebelum Apply CLI, agar token lama tidak ditimpa balik.
41. Sebagai pengguna, saya ingin melihat daftar PID, state, dan perintah sesi yang akan dihentikan, agar saya bisa memutuskan dengan sadar.
42. Sebagai pengguna, saya ingin tombol Batal menjadi fokus default dan tombol hentikan ditandai destruktif, agar tidak ada kecelakaan klik.
43. Sebagai pengguna, saya ingin opsi “Jangan tanya lagi” yang tersimpan, agar Apply berikutnya tidak selalu memunculkan dialog.
44. Sebagai pengguna, saya ingin sesi `stopped` (sisa Ctrl-Z) tetap bisa dihentikan lewat `SIGCONT` lalu `SIGTERM`/`SIGKILL`, agar kasus ini tidak menggantung.
45. Sebagai pengguna, saya ingin zombie diabaikan tetapi dilaporkan, agar tidak dianggap sesi hidup dan tidak memblokir Apply.
46. Sebagai pengguna, saya ingin proses `agy remote-control` ikut terdeteksi dan diberi label, agar saya tahu proses itu juga berhenti.
47. Sebagai pengguna, saya ingin Apply dibatalkan tanpa menulis apa pun bila `/proc` tidak bisa dibaca, agar kondisi sandbox tidak menghasilkan perubahan separuh.
48. Sebagai pengguna, saya ingin Apply dibatalkan bila proses tidak bisa dihentikan, dengan PID yang perlu ditutup manual, agar saya tidak menulis saat sesi lama masih hidup.
49. Sebagai pengguna, saya ingin aplikasi mendeteksi ulang tepat sebelum menulis keyring, agar sesi baru yang muncul di jendela waktu tidak terlewat.
50. Sebagai pengguna, saya ingin progres penghentian sesi terlihat tanpa membekukan UI, agar aplikasi tetap responsif sampai 5 detik.
51. Sebagai pengguna, saya ingin membatalkan penantian tanpa mengirim sinyal tambahan dan tanpa penulisan, agar saya tetap memegang kendali.

### Backup, rollback, dan pemulihan

52. Sebagai pengguna, saya ingin snapshot keyring dan file target dibuat sebelum penulisan, agar setiap Apply punya titik pulih.
53. Sebagai pengguna, saya ingin rollback otomatis bila salah satu langkah tulis gagal, agar tidak ada kombinasi keyring/file yang setengah jadi.
54. Sebagai pengguna, saya ingin rollback juga menghapus file yang baru dibuat bila sebelumnya tidak ada, agar kondisi kembali persis seperti semula.
55. Sebagai pengguna, saya ingin lokasi backup disebutkan saat terjadi kegagalan, agar saya bisa memeriksa atau memulihkan manual.
56. Sebagai pengguna, saya ingin menu “Pulihkan Backup Terakhir”, agar saya bisa membatalkan Apply terakhir tanpa mencari file sendiri.
57. Sebagai pengguna, saya ingin backup lama dibatasi 30 terbaru, agar disk tidak penuh.
58. Sebagai pengguna, saya ingin diberi tahu bahwa backup berisi kredensial dan hanya bisa dibaca pemilik, agar saya memperlakukannya dengan hati-hati.

### Database dan audit

59. Sebagai pengguna, saya ingin aplikasi mencatat target dan waktu Apply terakhir per akun, agar ada jejak audit ringan.
60. Sebagai pengguna, saya ingin migrasi kolom baru berjalan otomatis dan idempoten di SQLite maupun Turso, agar aplikasi lama tidak perlu di-reset.
61. Sebagai pengguna, saya ingin kolom audit tidak mengubah indeks data lama yang dipakai tabel, agar filter, sortir, dan kategori tetap berfungsi.
62. Sebagai pengguna, saya ingin status “Aktif di” tetap berasal dari kenyataan meskipun kolom audit berbeda, agar audit tidak pernah menutupi keadaan sebenarnya.

### Keamanan dan privasi

63. Sebagai pengguna, saya ingin token tidak pernah tampil utuh di UI atau log, agar kredensial tidak bocor lewat screenshot atau file log.
64. Sebagai pengguna, saya ingin Apply CLI tidak menyentuh item keyring lain, agar akun Chrome, GOA, atau aplikasi lain tidak berubah.
65. Sebagai pengguna, saya ingin file sensitif dan direktori backup dibatasi ke pemilik, agar user lain di mesin yang sama tidak bisa membacanya.
66. Sebagai pengguna, saya ingin password enkripsi tidak disimpan atau ditulis ulang oleh fitur ini, agar alur keamanan yang sudah ada tetap konsisten.

### Layout dan regresi

67. Sebagai pengguna, saya ingin chip Target berada di baris ConfigBar yang sama, agar tidak ada toolbar baru yang memakan ruang tabel.
68. Sebagai pengguna, saya ingin teks chip di-elide saat window menyempit, agar tombol Folder tetap terlihat pada lebar 900 px.
69. Sebagai pengguna, saya ingin kolom “Aktif di” tidak melebar berlebihan, agar kolom email dan kuota tetap terbaca.
70. Sebagai pengguna, saya ingin window tetap berukuran 1100×700 saat dibuka, agar kebiasaan dan posisi saya tidak berubah.
71. Sebagai pengguna, saya ingin Apply tersedia lewat klik kanan dan double-click, agar saya bisa memakai jalur cepat tanpa menu bertumpuk.
72. Sebagai pengguna, saya ingin filter kategori, pemisah grup, sortir, dan status enkripsi tetap berperilaku sama, agar fitur baru tidak merusak alur lama.
73. Sebagai pengguna, saya ingin dialog proses berukuran tetap dan daftar PID bisa di-scroll, agar dialog panjang tidak menggeser layout utama.
74. Sebagai pengguna, saya ingin semua pesan sukses/gagal memakai dialog standar, agar tidak ada panel permanen yang mengurangi area tabel.

## Implementation Decisions

### 1. Ruang lingkup v1.0

- Spesifikasi ini mencakup target global, Apply ke dua target, indikator dari kenyataan,
  pengelolaan sesi `agy`, backup/rollback/restore, migrasi DB, layout, dan setting integrasi.
- Banner drift dan aksi “Adopsi ke DB” (FR-11), impor file lama (FR-12), serta tombol salin
  perintah verifikasi (FR-14) **tidak** diimplementasikan pada v1.0. Deteksi ketidakcocokan
  tetap ada di level status dan tooltip, tetapi tidak memunculkan banner.
- Tidak ada penambahan dependensi pip. `python3-dbus` adalah dependensi sistem opsional yang
  hanya dipakai di Linux dan dideteksi saat runtime.

### 2. Domain dan nilai yang disimpan

- **Target** hanya dua nilai kanonik: `opencode` dan `antigravity_cli`.
- **Selected Target** disimpan di QSettings organisasi `OpenCodeApp`, aplikasi
  `AccountManager`, key `active_target`. Nilai tidak dikenal atau kosong dianggap `opencode`.
- **Active Account** selalu hasil pembacaan target (file/keyring), bukan QSettings.
- **Drift** berarti keyring dan `~/.gemini` tidak menunjuk akun yang sama, atau akun aktif di
  target tidak ada di DB. Drift hanya memengaruhi teks/tooltip status pada v1.0.
- **Apply Plan** adalah objek immutable berisi: snapshot akun terdekripsi, target, hasil
  validasi token (access token, expiry, email, refresh token hasil rotasi bila ada), daftar
  sesi `agy` yang terdeteksi, status availability target, dan apakah plan memerlukan
  konfirmasi kill.
- **Apply Result** memiliki tiga status: `SUCCESS`, `CANCELLED`, `FAILED`. Kegagalan membawa
  kode, pesan pengguna, saran tindakan, dan lokasi backup bila snapshot sudah dibuat.

### 3. Seam arsitektur: service facade dengan port yang disuntikkan

- Seluruh integrasi Antigravity berada di balik satu facade service. UI tidak pernah memanggil
  D-Bus, HTTP, atau menulis file target secara langsung.
- Facade menerima kumpulan **port** lewat konstruktor:
  - penyimpan akun (rekonstruksi JSON, tandai applied, update refresh token),
  - keyring (baca/tulis/hapus item),
  - file `~/.gemini` (baca/tulis atomic),
  - file OpenCode (baca/upsert/tulis atomic),
  - OAuth (tukar refresh token, decode email),
  - manajer proses (deteksi, hentikan, status),
  - lingkungan (OS, D-Bus, keyring terkunci, root),
  - jam/waktu.
- Implementasi produksi merakit port Linux/D-Bus, port file nyata, dan OAuth nyata. Test
  merakit fake untuk port yang sama. Ini satu-satunya seam baru yang ditambahkan; seam widget
  yang sudah ada dipakai ulang.
- Facade menyediakan empat operasi:
  - **build plan** — preflight, validasi token, deteksi sesi; tidak menulis apa pun.
  - **apply** — menghentikan sesi bila diizinkan, snapshot, tulis, verifikasi, tandai DB.
  - **read status** — email aktif per target, kondisi file/keyring, drift, availability.
  - **restore last backup** — memulihkan snapshot terakhir.
- **Perubahan dari PRD §10.1:** konfirmasi kill tidak lagi berupa callback di dalam `apply`.
  Plan membawa `requires_confirmation` dan daftar sesi; UI menampilkan dialog, lalu memanggil
  `apply` dengan izin kill. Pemisahan ini membuat alur bisa diuji tanpa UI dan menghindari
  callback lintas thread.
- Semua operasi facade dipanggil dari worker thread. `read status` tidak pernah melempar
  exception ke UI; kegagalan port dikembalikan sebagai status dengan field error.

### 4. Availability target

- `OpenCode` selalu tersedia sebagai pilihan; validasi folder/file dilakukan saat build plan.
- `Antigravity CLI` tersedia hanya bila seluruh kondisi berikut benar: OS Linux, Secret
  Service/D-Bus dapat dihubungi, keyring dapat dibuka, aplikasi bukan root.
- Alasan tidak tersedia dikembalikan sebagai kode + teks: `unsupported_os`, `no_dbus`,
  `keyring_locked`, `root`, `dbus_error`.
- Menu target tetap menampilkan CLI walau tidak tersedia, dalam keadaan disabled, dengan
  alasan di tooltip. Availability diperiksa ulang saat menu dibuka agar keyring yang baru
  dibuka user langsung terdeteksi.
- Di OS non-Linux, adapter keyring diganti implementasi null yang selalu melaporkan tidak
  tersedia. Aplikasi tetap berjalan penuh untuk target OpenCode.

### 5. Apply ke OpenCode

- Plan memvalidasi folder target, keberadaan file, dan bahwa isinya JSON objek dengan array
  `accounts`. File hilang atau rusak menggagalkan plan **sebelum** backup dan penulisan.
- Snapshot akun diambil dari rekonstruksi DB; service mengekstrak objek akun dari konfigurasi
  hasil rekonstruksi, bukan menulis konfigurasi satu-akun itu apa adanya.
- Upsert memakai email case-insensitive. Bila email sudah ada, entri lama diganti utuh dengan
  snapshot DB dan posisinya dipertahankan. Bila belum ada, entri ditambahkan di akhir.
- `activeIndex` diarahkan ke indeks hasil upsert. `activeIndexByFamily.gemini` dan
  `.claude` diubah hanya bila kunci itu sudah ada; kunci yang tidak ada tidak dibuat.
- Field top-level lain (misalnya `version`) dan akun lain dipertahankan.
- Backup file lama dibuat sebelum penulisan. Penulisan atomic: file sementara di direktori
  yang sama, `os.replace`, mode `0600`, tanpa mengikuti symlink.
- Apply OpenCode tidak memeriksa sesi `agy` dan tidak menyentuh keyring atau `~/.gemini`.
- Setelah sukses, DB ditandai `applied_target='opencode'` dan `last_applied_at` diisi waktu
  epoch detik. Dialog menampilkan email dan jumlah akun di file.

### 6. Apply ke Antigravity CLI

Urutan yang mengikat:

1. **Preflight** — availability target, akun ada di DB, `refresh_token` tidak kosong dan
   bentuknya wajar, password enkripsi (bila perlu) dapat mendekripsi akun. Tidak ada
   penulisan.
2. **Validasi token** — panggil endpoint token Google memakai client OAuth Antigravity dengan
   timeout 30 detik, tanpa retry otomatis. Wajib ada `access_token`. Email dari `id_token`
   harus ada dan sama (case-insensitive) dengan email akun; bila `id_token` atau emailnya
   tidak ada, Apply digagalkan. Pesan `invalid_grant` dan `unauthorized_client` dipetakan ke
   saran login ulang / token bukan milik client Antigravity.
3. **Deteksi sesi** — pindai proses; hasilnya masuk ke plan. Bila ada sesi hidup dan
   `auto_kill_agy` mati, plan mengembalikan `requires_confirmation`. Bila `auto_kill_agy`
   hidup, plan menandai boleh kill tanpa dialog; progres tetap ditampilkan.
4. **Apply** — deteksi ulang. Bila plan tidak mengizinkan kill tetapi ada sesi hidup, gagal
   tanpa menulis. Bila diizinkan, hentikan sesi sesuai state machine §7, lalu deteksi ulang
   dan pastikan tidak ada sesi hidup.
5. **Snapshot** — backup keyring dan file `~/.gemini` yang relevan, termasuk penanda file
   yang tidak ada. Backup dibuat setelah sesi bersih, sebelum tulis pertama.
6. **Tulis** — keyring, lalu `oauth_creds.json`, lalu `google_accounts.json` (bila
   `write_gemini_files` aktif), lalu tandai DB. Bila Google mengembalikan refresh token baru,
   token itu yang ditulis dan DB diperbarui agar tetap menjadi source of truth.
7. **Verifikasi** — baca ulang keyring dan file. Email dan refresh token harus cocok dengan
   plan; file `~/.gemini` harus sinkron dengan keyring. Kegagalan memicu rollback.
8. **Sukses** — dialog email, target, waktu, dan lokasi backup. Aplikasi tidak menjalankan
   `agy`. Tidak ada tombol salin perintah pada v1.0.

Detail data:

- Item keyring: `service=gemini`, `username=antigravity`, schema
  `org.freedesktop.Secret.Generic`. Payload mempertahankan `auth_method` yang ada (default
  `consumer`) dan `writer_id` yang ada; bila tidak ada, `writer_id` dibuat acak 32 byte
  base64url. Token menyimpan access token, token type, refresh token, expiry RFC3339 dengan
  skew 30 detik, dan `expires_in`.
- `oauth_creds.json` memuat access token, scope, token type, `id_token`, `expiry_date` dalam
  milidetik, dan refresh token.
- `google_accounts.json` memuat `active` = email baru dan `old` = gabungan unik dari daftar
  `old` lama + email aktif sebelumnya, dikurangi email baru. Email lama tidak dihapus.
- Bila `~/.gemini` belum ada, direktori dibuat dengan mode `0700`. Bila `write_gemini_files`
  mati, hanya keyring dan DB yang ditulis; verifikasi file dilewati dan status drift akan
  muncul sebagai konsekuensi wajar.

### 7. Pengelolaan proses `agy`

- Deteksi Linux membaca `/proc/<pid>/cmdline`, mengambil basename argumen pertama, dan
  mencocokkan **persis** `agy`. Berbeda dari tool lama, nama `antigravity` tidak lagi
  dicocokkan. `agy remote-control` terdeteksi karena binary-nya sama dan diberi label khusus.
- PID aplikasi sendiri dan parent-nya dikecualikan. Proses milik user lain tidak disentuh.
- State dibaca dari `/proc/<pid>/stat`:
  - `R`, `S`, `D` = hidup; `T`/`t` = stopped; `Z` = zombie.
  - Zombie tidak dianggap hidup, tidak memblokir Apply, dan hanya dilaporkan sebagai sisa.
  - Stopped dianggap hidup; sebelum `SIGTERM`, `SIGCONT` dikirim agar sinyal tidak menggantung.
- Kegagalan membaca `/proc` (sandbox/Flatpak) menggagalkan plan dengan pesan “periksa proses
  manual” dan tanpa penulisan apa pun.
- Sebelum setiap `kill`, `cmdline` diverifikasi ulang untuk menutup race PID reuse.
  `ProcessLookupError` dianggap proses sudah mati; `PermissionError` menandai PID itu gagal
  dan tidak dipaksa.
- State machine:
  - `DETECTING` → tidak ada sesi hidup ke `READY`; gagal baca ke `FAILED`; ada sesi hidup ke
    `AWAIT_CONFIRM` (kecuali auto-kill).
  - `AWAIT_CONFIRM` → Batal ke `CANCELLED`; setuju ke `CONT_SENT`.
  - `CONT_SENT` → `TERM_SENT`, poll 100 ms maksimum 3000 ms.
  - Bila belum kosong → `KILL_SENT`, poll 100 ms maksimum 2000 ms.
  - Bila masih hidup → `FAILED`; tidak ada penulisan.
  - Bila kosong → `READY`.
- Setelah `READY`, deteksi ulang dilakukan tepat sebelum menulis keyring. Sesi baru yang
  muncul menggagalkan Apply tanpa penulisan, termasuk ketika auto-kill aktif.
- Proses `D` yang tidak bisa dibunuh setelah timeout menghasilkan `FAILED` dengan saran
  menutup manual.
- Dialog konfirmasi berukuran tetap, berisi PID, state, dan perintah; default fokus pada
  Batal; tombol hentikan ditandai destruktif. Checkbox “Jangan tanya lagi” menulis
  `auto_kill_agy=true`.
- Progres kill dan penantian berjalan di worker thread; UI menampilkan dialog progres yang
  dapat dibatalkan. Membatalkan hanya menghentikan penantian, bukan mengirim sinyal tambahan,
  dan Apply berakhir `CANCELLED` tanpa penulisan.
- Pesan gagal menyebut PID yang perlu ditutup manual, perintah `pkill -9 -x agy` untuk
  disalin manual, dan penegasan bahwa tidak ada perubahan yang ditulis. Log hanya berisi PID,
  state, sinyal, dan hasil; tidak pernah token.

### 8. Indikator dan pembacaan status

- `read status` mengembalikan, per target: email aktif, kondisi (`active`, `none`,
  `unrecorded`, `invalid_file`, `drift_gemini`, `unavailable`, `locked`, `error`), dan pesan
  pendek. Untuk CLI juga menyertakan ringkasan sesi (jumlah hidup/stopped/zombie) dan alasan
  ketidaktersediaan.
- OpenCode: akun aktif ditentukan dari `activeIndex`, dengan fallback
  `activeIndexByFamily.gemini` bila `activeIndex` tidak ada. File hilang/rusak dilaporkan
  sebagai kondisi, bukan exception.
- CLI: email dibaca dari payload keyring. Bila keyring kosong → `none`. Bila email keyring
  tidak ada di DB → `unrecorded`. Bila keyring dan `~/.gemini` menunjuk email berbeda →
  `drift_gemini`; status tetap menampilkan email keyring sebagai Active Account.
- Chip ConfigBar menampilkan target + ikon status + email (di-elide) sesuai matriks PRD §13.
  Tooltip memuat teks penuh, email aktif, kondisi, alasan ketidaktersediaan, dan ringkasan
  sesi `agy`.
- Kolom “Aktif di” dihitung dengan membandingkan email baris dengan email aktif tiap target,
  case-insensitive. Bila aktif di keduanya → `OpenCode + CLI`. Bila tidak → `—`.
- Kolom audit DB (`applied_target`, `last_applied_at`) tidak dipakai untuk kolom “Aktif di”;
  nilainya hanya untuk audit dan tooltip kecil. Sumber kebenaran tampilan tetap pembacaan
  target.
- `reload_accounts` menjalankan query ringkasan DB dan `read status` dalam satu worker task.
  Kegagalan status tidak menggagalkan pemuatan tabel.
- Status diperbarui saat aplikasi start, setiap reload, setelah Apply, setelah kill, dan
  setelah restore.

### 9. Database dan migrasi

- Tambah dua kolom di tabel `accounts`: `applied_target TEXT NULL` dan
  `last_applied_at INTEGER NULL`. Nilai target memakai nilai kanonik yang sama dengan
  QSettings.
- Migrasi aditif dan idempoten: untuk SQLite, kolom dicek lewat `PRAGMA table_info`; untuk
  Turso, error “duplicate column” diabaikan. Tidak ada perubahan pada tabel
  `account_fingerprints`, `account_quotas`, atau `categories`.
- Query ringkasan akun menambahkan dua kolom di **akhir** hasil, sehingga indeks lama 0–10
  tidak bergeser dan tabel tetap kompatibel.
- Method baru untuk menandai akun telah diterapkan (target + waktu), dan untuk memperbarui
  refresh token hasil rotasi dengan tetap menghormati status enkripsi akun.
- Waktu audit adalah epoch detik UTC; ditampilkan dalam waktu lokal bila diperlukan.

### 10. Struktur UI dan layout

- Chip Target adalah `QToolButton` berteks dengan menu dropdown, gaya padding, border, dan
  font 11 px yang identik dengan chip DB/Enkripsi. Bukan `QComboBox` lebar dan bukan toolbar
  kedua.
- Urutan ConfigBar: DB, Enkripsi, Target, label Folder, lalu `QLineEdit` folder dengan
  `stretch=1` dan lebar minimum 120 px. Chip Target berukuran tetap dan tidak ikut melar.
- Teks chip di-elide berdasarkan lebar tersedia pada `resizeEvent`; tooltip selalu memuat
  teks penuh. Pada lebar 900 px tombol/field Folder tetap terlihat dan ConfigBar tetap satu
  baris.
- Kolom tabel menjadi 7: Email, Kategori, **Aktif di**, Status Enkripsi, Flash Quota, Pro
  Quota, Claude Quota. Kolom “Aktif di” memakai `ResizeToContents` dengan lebar maksimum
  ±110 px. Baris pemisah kategori di-span ke 7 kolom.
- Ukuran window default tetap 1100×700; tidak ada `resize()` baru. Kolom Email dan kuota tetap
  `Stretch`, sehingga saat sempit yang mengecil adalah kolom tersebut, bukan muncul scroll
  horizontal permanen.
- Menu konteks akun mendapat submenu “Terapkan ke…” berisi `OpenCode` dan
  `Antigravity CLI`. Item CLI disabled dengan alasan bila target tidak tersedia. Double-click
  pada baris akun menjalankan Apply ke Selected Target.
- Tidak ada tombol Apply di toolbar. Akses hanya lewat menu konteks dan double-click.
- Dialog konfirmasi proses berukuran tetap ±480×320 dengan daftar PID yang bisa di-scroll.
  Dialog progres memakai mekanisme loading yang sudah ada dengan mode opsional yang bisa
  dibatalkan; tidak menambah tinggi layout utama.
- Pesan sukses/gagal memakai `QMessageBox` standar. Tidak ada banner atau panel permanen pada
  v1.0.
- Pengaturan mendapat grup “Integrasi” berisi `auto_kill_agy` (default mati) dan
  `write_gemini_files` (default aktif). Tidak ada tombol impor pada v1.0.
- Menu Pengaturan mendapat aksi “Pulihkan Backup Terakhir…”. Konfirmasi menyebut waktu,
  target, dan email dari manifest sebelum memulihkan.

### 11. Backup, rollback, dan restore

- Direktori backup: `~/.local/state/auth-login-management/backups/<timestamp>/`.
  Direktori `0700`, file `0600`.
- Setiap backup berisi `meta.json` plus salinan item keyring dan file target yang ada pada
  saat itu. `meta.json` mencatat target, email, waktu, versi aplikasi, PID yang dihentikan,
  dan daftar artefak beserta status “ada”/“tidak ada”.
- Restore mengembalikan isi artefak yang ada, dan **menghapus** artefak yang sebelumnya tidak
  ada. Keyring yang sebelumnya tidak ada akan dihapus; file yang sebelumnya tidak ada akan
  dihapus.
- Restore tidak mengubah kolom audit DB. Indikator tetap jujur karena membaca kenyataan.
- Retensi 30 backup terbaru; pembersihan dilakukan setelah Apply sukses, bukan sebelum, agar
  backup yang baru dibuat tidak ikut terhapus.
- Bila kegagalan terjadi setelah snapshot dibuat, snapshot dipertahankan dan lokasinya
  disebutkan di dialog kegagalan.
- Rollback otomatis mengembalikan keyring dan file dari snapshot, lalu melaporkan kegagalan
  asli. Penandaan DB dilakukan paling akhir sehingga kegagalan sebelumnya tidak meninggalkan
  audit palsu.

### 12. Keamanan

- Token tidak pernah ditampilkan utuh dan tidak pernah masuk log. Nilai yang perlu disebut
  diredaksi dengan pola awal/akhir (misalnya `1//0gTw…Q4pM`).
- File sensitif ditulis `0600`, direktori `0700`, penulisan atomic, dan tidak mengikuti
  symlink.
- Apply CLI hanya menyentuh item keyring `gemini/antigravity`, tidak pernah item lain.
- Password enkripsi hanya dibaca dari alur QSettings yang sudah ada, dipakai sesaat untuk
  dekripsi, dan tidak disimpan atau ditulis ulang oleh fitur ini.
- Dialog dan pesan tidak pernah menampilkan isi payload keyring atau `oauth_creds.json`.
- Backup berisi kredensial; dialog kegagalan dan konfirmasi restore menyebutkan hal ini.

### 13. Perbedaan yang disengaja dari `agy_switch`

- Token selalu divalidasi ke Google sebelum menulis; tidak ada jalur “tulis dulu”.
- Apply OpenCode memakai upsert, bukan menimpa total.
- Kill memakai `SIGCONT` → `SIGTERM` → `SIGKILL` bertahap; bukan `SIGKILL` langsung dan bukan
  `pkill -f`.
- Hanya binary `agy` yang dicocokkan, bukan `antigravity`.
- Status dibaca ulang dan dibandingkan dengan DB; drift tidak disimpan sebagai kebenaran.
- Vault `accounts.json` tidak dipakai sebagai penyimpanan; DB adalah source of truth.
- Layout tidak menambah toolbar atau dialog bertumpuk.

### 14. Penanganan error dan pesan

- Kegagalan dibagi menjadi: preflight/availability, token, sesi, backup, tulis, verifikasi,
  restore, dan database. Masing-masing memetakan ke pesan pengguna yang menyebut langkah
  yang gagal dan tindakan berikutnya.
- Pesan kegagalan setelah ada potensi perubahan wajib menyatakan secara eksplisit apakah
  perubahan sudah di-rollback atau tidak.
- Kegagalan jaringan tidak di-retry otomatis; pengguna memilih Apply lagi.
- Kegagalan dekripsi memakai pesan yang sudah ada agar konsisten dengan fitur copy/update.
- Rate limit atau respons Google non-JSON dipetakan ke pesan “coba lagi” tanpa membocorkan
  respons mentah.

## Testing Decisions

### Prinsip

Test yang baik hanya memeriksa **perilaku yang terlihat dari luar** seam: hasil plan, isi
file/keyring setelah apply, status yang dikembalikan, pesan error, dan sinyal/teks widget.
Test tidak boleh mengunci detail implementasi seperti nama method privat, urutan pemanggilan
internal, atau struktur dict internal. Fake dipakai untuk sistem eksternal (keyring, OAuth,
proses, filesystem nyata), bukan untuk memalsukan modul aplikasi sendiri.

### Seam yang diuji

1. **Facade service dengan port palsu** — seam utama dan satu-satunya seam baru. Test merakit
   service produksi dengan fake keyring in-memory, root file sementara, file OpenCode
   sementara, stub OAuth, tabel proses palsu, dan jam palsu. Seluruh alur plan/apply/status/
   restore diuji di sini.
2. **`AccountDatabase` dengan SQLite sementara** — seam lama, dipakai untuk migrasi, query
   ringkasan, dan penandaan audit.
3. **Widget langsung** — `ConfigBarWidget`, `AccountTableWidget`, dialog proses, dan dialog
   pengaturan diinstansiasi langsung; diuji lewat teks, status enabled, sinyal, dan ukuran,
   bukan lewat `MainWindow`.
4. **Adapter nyata tidak diuji otomatis kecuali opt-in** — keyring Linux asli hanya diuji
   lewat integration test yang di-skip secara default dan memakai item `service=selftest`,
   tidak pernah `gemini`. OAuth nyata dan proses `agy` nyata tidak dipanggil di CI.

Wiring `MainWindow` (urutan dialog, pembacaan QSettings, refresh setelah Apply) tidak diuji
otomatis pada v1.0; itu ditutup dengan smoke test manual karena logikanya tipis dan harness-nya
mahal. Ini keputusan sadar, bukan kelalaian.

### Prior art

Repo belum memiliki test, pytest, maupun konfigurasi test. Spesifikasi ini menetapkan pola
pertama:

- `pytest` dan `pytest-qt` sebagai dependensi pengembangan, bukan runtime.
- Direktori `tests/` dengan `conftest.py` untuk fake dan fixture sementara.
- `QT_QPA_PLATFORM=offscreen` untuk test widget.
- Marker `integration` untuk test yang menyentuh keyring/D-Bus nyata; default skip kecuali
  diaktifkan lewat environment variable.
- Tidak ada test yang memakai database `accounts_manager.db` milik repo, folder OpenCode
  pengguna, atau `~/.gemini` pengguna.

### Cakupan test per modul

**Service — plan dan apply OpenCode**

- File berisi 3 akun, Apply akun ke-4 → file berisi 4 akun, akun lama utuh, `activeIndex`
  menunjuk indeks baru, `activeIndexByFamily` yang ada ikut diperbarui, kunci yang tidak ada
  tidak dibuat.
- Email sudah ada dengan kapitalisasi berbeda → entri diganti, tidak ada duplikat.
- Field top-level lain dipertahankan.
- File hilang / JSON rusak / `accounts` bukan array → plan gagal, tidak ada backup, tidak ada
  penulisan, pesan menyebut penyebab.
- Backup berisi salinan file lama; mode file hasil tulis `0600`.
- Apply OpenCode tidak memanggil port proses atau keyring.

**Service — plan dan apply CLI**

- Happy path: keyring menerima payload dengan email dan refresh token yang benar;
  `oauth_creds.json` dan `google_accounts.json` sinkron; `old` mempertahankan email lama;
  DB ditandai `antigravity_cli` dengan waktu.
- Refresh token kosong / format tidak wajar → plan gagal sebelum OAuth dan sebelum backup.
- `invalid_grant` dan `unauthorized_client` → pesan spesifik; tidak ada penulisan.
- `id_token` tanpa email atau email berbeda → plan gagal; tidak ada penulisan.
- Google mengembalikan refresh token baru → keyring dan DB memakai token baru.
- `write_gemini_files=false` → hanya keyring dan DB yang berubah; tidak ada file `~/.gemini`
  yang ditulis atau dibuat.
- `~/.gemini` belum ada → direktori dibuat `0700` dan file ditulis.
- Keyring terkunci / D-Bus mati / OS non-Linux / root → plan gagal dengan alasan availability;
  tidak ada penulisan.
- Verifikasi membaca ulang dan mendeteksi ketidakcocokan → rollback penuh dan pesan berisi
  lokasi backup.
- Kegagalan menulis `oauth_creds.json` setelah keyring berhasil → keyring dan file lain
  dipulihkan; DB tidak ditandai.
- Kegagalan menandai DB → keyring dan file dipulihkan.
- Pesan error dan log tidak memuat refresh token utuh.

**Service — status**

- OpenCode: akun aktif dari `activeIndex`; fallback `activeIndexByFamily.gemini`; file hilang;
  JSON rusak; email aktif tidak ada di DB → `unrecorded`.
- CLI: keyring kosong → `none`; email aktif; email tidak di DB → `unrecorded`; keyring dan
  `~/.gemini` berbeda → `drift_gemini` dengan email keyring tetap sebagai aktif; keyring
  terkunci; OS tidak didukung; `/proc` tidak terbaca untuk ringkasan sesi.
- Status tidak pernah melempar exception ke pemanggil.
- Perhitungan kolom “Aktif di”: satu target, dua target, tidak ada, case-insensitive.

**Manajer proses (dengan `/proc` palsu dan sinyal palsu)**

- Deteksi hanya basename `agy`, bukan `antigravity`, dan mengecualikan PID sendiri/parent.
- `agy remote-control` terdeteksi dan dilabeli.
- State `R/S/D` dianggap hidup; `Z` diabaikan tetapi dilaporkan; `T` memicu `SIGCONT` sebelum
  `SIGTERM`; `D` yang tak bisa dibunuh berakhir gagal setelah timeout.
- Tidak ada sesi → langsung siap.
- Ada sesi, auto-kill mati → plan `requires_confirmation`; apply tanpa izin gagal tanpa
  penulisan.
- Konfirmasi → urutan sinyal benar, polling berhenti saat kosong, apply lanjut.
- Kill gagal / `PermissionError` → gagal tanpa penulisan, PID dilaporkan.
- `ProcessLookupError` → dianggap sudah mati, lanjut.
- Sesi baru muncul setelah phase kill dan sebelum tulis → gagal tanpa penulisan, termasuk
  saat auto-kill aktif.
- `/proc` tidak bisa dibaca → gagal tanpa penulisan.
- Timeout menggunakan jam palsu; test tidak benar-benar menunggu 3–5 detik.

**Backup dan restore**

- Snapshot mencatat artefak yang ada dan tidak ada.
- Restore mengembalikan isi artefak dan menghapus artefak yang sebelumnya tidak ada
  (keyring maupun file).
- Retensi mempertahankan 30 terbaru dan tidak menghapus backup yang baru saja dibuat.
- Restore tidak mengubah kolom audit DB.
- Backup dan file sensitif memiliki mode `0600`; direktori `0700`.

**Database**

- Migrasi SQLite berjalan pada DB kosong dan pada DB lama; dijalankan dua kali tetap aman.
- Kolom baru muncul dan `mark_applied` menyimpan target serta waktu.
- Query ringkasan mengembalikan dua kolom baru di akhir; indeks 0–10 tetap sama.
- Penandaan audit tidak mengubah kategori atau data kuota.
- Pembaruan refresh token hasil rotasi menghormati status enkripsi akun (terenkripsi tetap
  terenkripsi, plaintext tetap plaintext).

**Widget**

- ConfigBar: chip Target ada, default `OpenCode`, memilih menu mengubah teks dan memancarkan
  sinyal; CLI disabled saat tidak tersedia dengan tooltip alasan; teks di-elide pada lebar
  sempit; ConfigBar tetap satu baris pada 900 px dan field folder tetap terlihat.
- Tabel: 7 kolom dengan urutan yang disepakati; kolom “Aktif di” berisi nilai yang benar;
  baris pemisah kategori men-span 7 kolom; filter, sortir, dan status enkripsi tetap berfungsi.
- Menu konteks: submenu “Terapkan ke…” memancarkan target yang dipilih; item CLI disabled saat
  tidak tersedia; double-click memancarkan target aktif.
- Dialog proses: daftar PID/state tampil, Batal fokus default, checkbox menulis
  `auto_kill_agy`, ukuran dialog tetap.
- Pengaturan: checkbox integrasi memuat dan menyimpan nilai yang benar; default
  `auto_kill_agy` mati dan `write_gemini_files` aktif.
- Layout: window 1100×700 tidak berubah ukuran saat dibuka; pada 900×600 tidak ada scroll
  horizontal permanen di ConfigBar dan tinggi tabel tidak menyusut karena elemen baru.

**Integration opt-in**

- Tulis/baca/hapus item keyring sementara `service=selftest`; tidak pernah `gemini`.
- Proses nyata `sleep` yang di-`SIGSTOP` dapat dihentikan lewat jalur `SIGCONT` → `SIGTERM` →
  `SIGKILL`, lalu dipastikan tidak ada proses tersisa.

### Pemetaan ke kriteria penerimaan PRD

| AC | Bukti test |
| --- | --- |
| AC-01 | Widget ConfigBar + QSettings persist (setelah reopen disimulasikan dengan instans baru) |
| AC-02 | Service OpenCode upsert 3 → 4 + backup |
| AC-03 | Service CLI dengan OAuth `invalid_grant`, tidak ada tulis/backup |
| AC-04 | Manajer proses + service, dua sesi hidup, konfirmasi, tulis setelah kosong |
| AC-05 | Manajer proses gagal kill → service gagal tanpa tulis |
| AC-06 | Service dengan kegagalan tulis `oauth_creds.json` → rollback |
| AC-07 | Service status membaca keyring/file, bukan setting |
| AC-08 | Widget/menu dengan lingkungan non-Linux |
| AC-09 | Manajer proses dengan state `T` dan jam palsu |
| AC-10 | Sesi baru muncul sebelum tulis → gagal tanpa tulis |
| AC-11 | Widget layout pada 1100×700 dan 900×600 |
| AC-12 | Service dengan port `/proc` yang gagal dibaca |

## Out of Scope

- **v1.1:** banner drift + tombol “Adopsi ke DB”, impor sekali dari vault/file lama, tombol
  “Salin perintah verifikasi log”, dan aksi “Logout dari CLI”.
- Backend keyring Windows (Credential Manager) dan macOS (Keychain). Target CLI hanya Linux;
  di OS lain ditampilkan nonaktif.
- Antigravity IDE (GUI) dan profil Chromium-nya.
- Otomasi login browser Google, consent, atau 2FA.
- Target per akun atau Apply ke dua target sekaligus dalam satu aksi.
- Menyimpan vault `~/.config/antigravity/accounts.json` sebagai source of truth.
- Menghapus atau mengubah tabel/kolom lama secara destruktif.
- Dependensi pip baru; `python3-dbus` tetap dependensi sistem opsional.
- Toolbar baru, panel permanen, atau perubahan ukuran window default.
- Menjalankan `agy` otomatis setelah Apply.
- Berbagi atau menjual akun; fitur ini hanya untuk akun milik pengguna sendiri.
- Test otomatis untuk wiring `MainWindow` dan test Turso nyata (keduanya manual).

## Further Notes

### Keputusan atas pertanyaan terbuka PRD §17

- **O1** — Memilih target hanya mengubah mode; tidak menerapkan ulang akun terakhir. Apply
  tetap aksi eksplisit.
- **O2** — Menu konteks selalu menampilkan kedua target lewat submenu “Terapkan ke…”; CLI
  disabled bila tidak tersedia. Tidak ada alur “ganti target dulu” yang memaksa.
- **O3** — `write_gemini_files` default aktif; Apply CLI menulis `~/.gemini` kecuali dimatikan.
- **O4** — Retensi 30 backup. Tombol “Bersihkan backup” tidak termasuk v1.0.
- **O5** — Logout dari CLI ditunda ke v1.1.
- **O6** — Apply OpenCode tidak mensyaratkan fingerprint/project; validasi hanya pada
  keberadaan `refresh_token`.
- **O7** — Nama kolom “Aktif di”.
- **O8** — Proyek `antigravity-switch` tetap dipertahankan sebagai referensi dan tool darurat;
  kode disalin ke aplikasi.

### Risiko yang diketahui

- **Flatpak/sandbox** dapat memblokir `/proc` atau D-Bus. Perilakunya sudah fail-safe
  (tidak menulis), tetapi pengguna harus menutup proses manual.
- **Keyring prompt** dapat muncul saat unlock; availability diperiksa ulang saat menu dibuka
  agar pengguna bisa mencoba lagi tanpa restart.
- **Proses `D`** tidak dapat dibunuh sampai I/O selesai; pesan harus jelas agar pengguna tidak
  mengira aplikasi hang.
- **Turso** menambah latensi pada penandaan audit. Karena penandaan DB adalah langkah terakhir,
  kegagalan jaringan di sini memicu rollback file/keyring; ini konsekuensi yang diterima.
- **Skema file OpenCode** dapat berubah di versi mendatang. Upsert mempertahankan field yang
  tidak dikenal dan tidak mengubah `version`, sehingga perubahan kecil tidak merusak file.
- **Rotasi refresh token** oleh Google jarang terjadi; bila terjadi, DB diperbarui agar tidak
  ada dua kebenaran.

### Definition of done v1.0

- Seluruh FR v1.0 dan AC-01…AC-12 terpenuhi.
- Test service, manajer proses, backup/restore, database, dan widget lulus; integration test
  opt-in tidak wajib di CI.
- Smoke test manual: Apply OpenCode pada file 3 akun, Apply CLI dengan 0/2/3 sesi `agy`
  (termasuk satu `SIGSTOP`), kegagalan token, kegagalan tulis yang dipaksa, restore backup,
  dan layout pada 1100×700 serta 900×600.
- Tidak ada token utuh di log, dialog, atau pesan error.
- Packaging Linux mencantumkan `python3-dbus` sebagai dependensi; aplikasi tetap berjalan
  tanpa paket itu dengan target CLI nonaktif.

### Catatan proses

Spec ini ditulis dari PRD v0.2 tanpa wawancara tambahan. Issue tracker dan kosakata label
triage belum dikonfigurasi pada sesi ini, sehingga spec belum dipublikasikan sebagai issue
dengan label `ready-for-agent`. Jalankan `/setup-matt-pocock-skills` bila publikasi ke tracker
diinginkan.
