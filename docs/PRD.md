# PRD — Integrasi Target OpenCode & Antigravity CLI

| Field | Nilai |
| --- | --- |
| Status | **DRAF v0.2** — siap implementasi; keputusan §6 masih bisa dikoreksi |
| Pemilik | lemon-manis-22 |
| Project | `auth-login-management` |
| Tanggal | 2026-11-19 |
| Versi dokumen | 0.2 |
| Fitur | Pemilihan target penerapan akun + indikator + penggantian akun Antigravity CLI |

> Dokumen ini adalah hasil `grill-with-docs` (skill `grilling` + `domain-modeling`).
> Keputusan pada §6 diambil dari **rekomendasi** karena jawaban eksplisit belum diberikan.
> Semua keputusan masih murah untuk diubah **sebelum implementasi**; setelah implementasi
> biayanya naik (lihat kolom "Biaya berubah").

---

## 1. Ringkasan

`auth-login-management` saat ini menyimpan akun Google (email, refresh token, fingerprint,
kuota) di SQLite/Turso dan menulis satu akun ke `antigravity-accounts.json` milik OpenCode.
Namun akun yang sama juga dipakai oleh **Antigravity CLI (`agy`)**, yang menyimpan
kredensialnya di **GNOME Keyring (Secret Service D-Bus)**, bukan di file.

Fitur ini menambahkan:

1. **Target** global yang bisa dipilih dan disimpan: `OpenCode` atau `Antigravity CLI`.
2. Aksi **Apply** yang menerapkan akun dari DB ke target terpilih.
3. **Indikator** yang menunjukkan target aktif dan akun yang benar-benar sedang terpasang.
4. **Pengelolaan proses `agy`** yang aman sebelum mengganti kredensial CLI.

---

## 2. Masalah

| # | Masalah | Bukti |
| --- | --- | --- |
| M1 | Menghapus `~/.gemini` atau mengedit `oauth_creds.json` tidak mengganti akun CLI | Token CLI ada di keyring item `service=gemini, username=antigravity` |
| M2 | Aplikasi hanya bisa menulis ke file OpenCode; tidak ada jalur ke CLI | `update_antigravity_file()` hanya menulis `antigravity-accounts.json` |
| M3 | Menimpa total file OpenCode menghapus akun lain di file tersebut | `open(target_file, "w")` dengan satu akun |
| M4 | Tidak ada indikator akun mana yang benar-benar aktif di tiap target | `ConfigBarWidget` hanya menampilkan folder, DB, enkripsi |
| M5 | Mengganti token saat sesi `agy` masih hidup bisa ditimpa balik oleh proses tersebut | Token di-refresh & disimpan ulang oleh `agy` yang berjalan |

---

## 3. Tujuan

- **G1** Pengguna dapat memilih target (`OpenCode` / `Antigravity CLI`) dari UI, dan pilihan
  itu bertahan setelah aplikasi ditutup.
- **G2** Satu aksi **Apply** menerapkan akun terpilih ke target aktif, dengan validasi token,
  backup, dan rollback otomatis.
- **G3** UI selalu menunjukkan target aktif **dan** akun yang nyata-nyata terpasang di target
  tersebut (dibaca dari keyring/file, bukan hanya dari setting).
- **G4** Apply ke CLI tidak pernah merusak sesi lain: proses `agy` ditangani secara eksplisit,
  aman, dan terverifikasi.
- **G5** File OpenCode tidak lagi kehilangan akun lain saat Apply (upsert + `activeIndex`).

## 4. Non-tujuan

- Tidak mengelola login browser Google (tidak ada otomasi consent/2FA).
- Tidak menyentuh **Antigravity IDE (GUI)** — login IDE di profil Chromium terenkripsi
  dan tetap dikelola dari UI IDE.
- Tidak menyimpan password enkripsi di tempat baru; mekanisme password yang ada dipakai ulang.
- Tidak menghapus/mengubah tabel yang sudah ada secara destruktif (hanya `ALTER TABLE` aditif).
- Tidak (v1) mendukung Windows/macOS untuk target CLI — lihat §6 D9.
- Tidak menjadi tool untuk berbagi/menjual akun; lihat §12.

---

## 5. Glosarium (domain)

| Istilah | Definisi | Catatan |
| --- | --- | --- |
| **Account** | Satu identitas Google yang tersimpan di DB: `email` + `refresh_token` + metadata proyek/fingerprint/kuota. | Sudah ada di skema `accounts`. |
| **Target** | Tujuan pemasangan kredensial sebuah Account. Nilai: `OpenCode` \| `Antigravity CLI`. | Istilah baru; menggantikan kalimat ambigu "pakai untuk opencode". |
| **Selected Target** | Target global yang dipilih pengguna dan disimpan di `QSettings`. | Hanya memengaruhi Apply & indikator; tidak mengubah data akun. |
| **Apply** | Tindakan menulis kredensial Account ke Target (file OpenCode / keyring CLI). | Bukan sinonim "pilih". Satu Account bisa di-Apply ke target mana pun. |
| **Active Account** | Account yang kredensialnya sedang terpasang di sebuah Target. | Ditentukan oleh kenyataan (keyring/`activeIndex`), bukan oleh setting. |
| **Session** | Proses `agy` yang sedang berjalan dan memegang token di memori. | Objek yang dikelola oleh Process Manager. |
| **Source of truth** | Database aplikasi (SQLite/Turso) sebagai satu-satunya penyimpan akun. | Vault `accounts.json` lama tidak lagi ditulis. |
| **Apply Plan** | Rencana langkah Apply yang sudah divalidasi (token valid, target siap, proses aman) sebelum ada penulisan. | Dasar rollback. |
| **Drift** | Keadaan saat Active Account di Target ≠ Account yang tercatat di DB. | Ditampilkan sebagai peringatan indikator. |

---

## 6. Keputusan desain

| ID | Keputusan | Alasan | Alternatif yang ditolak | Biaya berubah |
| --- | --- | --- | --- | --- |
| **D1** | Target adalah **satu pilihan global** (mode), disimpan di `QSettings("OpenCodeApp","AccountManager")` key `active_target`. | Indikator "sedang pakai yang mana" harus tunggal dan jelas. | Target per akun / hybrid → indikator ambigu, kompleksitas UI naik. | Rendah |
| **D2** | Kode integrasi **di-vendor** ke `src/integrations/antigravity/` (keyring D-Bus, OAuth, file `~/.gemini`), tanpa subprocess. | Menjaga packaging PyInstaller (.deb/.exe) dan menghindari ketergantungan pada binary eksternal. | `subprocess` ke `agy-switch`; package pip terpisah. | Sedang |
| **D3** | DB menjadi **source of truth**; vault `~/.config/antigravity/accounts.json` tidak lagi dipakai (hanya dibaca sekali untuk impor). | Menghindari dua kebenaran yang bisa berbeda. | Sinkron dua arah; salinan vault setiap Apply. | Sedang |
| **D4** | Apply ke OpenCode = **upsert + set `activeIndex`/`activeIndexByFamily`** (tidak menimpa total), dengan backup file sebelum menulis. | File memang multi-akun (`accounts[]`). Menimpa total menghapus akun lain (M3). | Tetap timpa total; timpa + backup saja. | Rendah |
| **D5** | Pengelolaan proses: hanya proses bernama persis `agy`; dialog konfirmasi berisi PID; `SIGTERM` → tunggu ≤3 s → `SIGKILL`; verifikasi kosong; batal bila gagal. Detail §9. | Aman, tidak salah sasaran, dan tidak menulis keyring saat sesi lama masih hidup (M5). | `pkill -f`; auto-kill tanpa dialog. | Rendah |
| **D6** | Indikator: **chip di ConfigBar** (target + status) **dan kolom tabel "Aktif di"**. | Target perlu terlihat tanpa membuka menu; status per akun perlu terlihat di tabel. | Hanya salah satu. | Rendah |
| **D7** | Status Active Account **selalu dibaca dari kenyataan** (keyring + file), bukan dari setting; setting hanya untuk mode target. | Mencegah indikator "bohong" saat akun diganti dari terminal (M1). | Percaya QSettings. | Rendah |
| **D8** | Tambah kolom DB `applied_target TEXT NULL` dan `last_applied_at INTEGER NULL` (migrasi aditif, idempoten untuk SQLite & Turso). | Audit ringan & badge per akun. | Tabel riwayat penuh. | Sedang |
| **D9** | Target Antigravity CLI hanya aktif di **Linux** (Secret Service). Di Windows/macOS target ditampilkan **nonaktif** dengan penjelasan. | Backend keyring berbeda per OS (Credential Manager / Keychain) dan belum diuji. | Dukungan penuh lintas OS di v1. | Sedang |
| **D10** | Setelah Apply, aplikasi **tidak** menjalankan `agy` otomatis; hanya menampilkan instruksi + perintah verifikasi. | Menghindari membuka TUI di dalam proses GUI. | Auto-launch terminal. | Rendah |
| **D11** | Password enkripsi memakai alur yang sudah ada (`_get_encryption_password()`); tidak disimpan/ditulis ulang oleh fitur ini. | Konsistensi & keamanan. | Prompt baru / menyimpan password. | Rendah |
| **D12** | Backup ditulis ke `~/.local/state/auth-login-management/backups/<timestamp>/` (keyring JSON + file target + `meta.json`), retensi 30 terbaru. | Rollback cepat dan audit. | Tanpa backup / retensi tak terbatas. | Rendah |

---

## 7. Alur UX

### 7.1 Memilih target

1. Di `ConfigBarWidget` ada chip baru: `🎯 Target: OpenCode` (klik → menu: `OpenCode`, `Antigravity CLI`).
2. Pilihan disimpan ke `QSettings` dan chip langsung berubah.
3. Perubahan target **tidak** mengubah kredensial apa pun; hanya mengubah tujuan Apply dan
   konteks indikator.
4. Bila target `Antigravity CLI` tidak tersedia (OS selain Linux / D-Bus mati / keyring terkunci),
   chip menampilkan `⛔ Target: Antigravity CLI (tidak tersedia)` + tooltip alasan, dan aksi Apply
   ke CLI dinonaktifkan.

### 7.2 Apply ke OpenCode

Pemicu: menu konteks akun → **"Terapkan ke OpenCode"**.

1. Validasi: folder OpenCode + file `antigravity-accounts.json` ada.
2. Decrypt Account (password bila perlu).
3. Bangun objek akun dari DB (`reconstruct_json_by_id`) → objek JSON siap tulis.
4. Backup file lama → `<backup_dir>/antigravity-accounts.json`.
5. Upsert: ganti entri dengan email sama (case-insensitive) atau tambah entri baru.
6. Set `activeIndex` ke indeks akun tsb; set `activeIndexByFamily.gemini` dan `.claude` ke indeks
   yang sama *jika* kunci tersebut ada.
7. Tulis atomic (`mkstemp` + `os.replace`, `0600`).
8. Update DB: `applied_target='opencode'`, `last_applied_at=now`.
9. Refresh indikator. Dialog sukses berisi email + jumlah akun di file.

### 7.3 Apply ke Antigravity CLI

Pemicu: menu konteks akun → **"Terapkan ke Antigravity CLI"**.

```
[1] Preflight
     ├─ OS didukung? (Linux + Secret Service)      → tidak: batalkan + jelaskan (D9)
     ├─ Keyring dapat diakses / tidak terkunci?    → tidak: minta buka keyring
     └─ Account punya refresh_token?               → tidak: batalkan

[2] Validasi token (sebelum menyentuh apa pun)
     └─ POST oauth2.googleapis.com/token (client OAuth Antigravity)
         ├─ gagal (invalid_grant/unauthorized_client) → batalkan, pesan spesifik
         └─ sukses → email di id_token harus == email Account, jika tidak → batalkan

[3] Tangani Session
     ├─ deteksi proses `agy` (state R/S/D/T; zombie diabaikan)
     ├─ ada & auto_kill=off → dialog daftar PID + state [Hentikan Sesi] [Batal]
     │     ├─ Batal → selesai tanpa perubahan
     │     └─ Hentikan → SIGCONT → SIGTERM → tunggu ≤3s → SIGKILL ≤2s → verifikasi
     └─ masih hidup setelah verifikasi → batalkan (JANGAN tulis keyring)

[4] Snapshot
     └─ backup: item keyring (JSON), oauth_creds.json, google_accounts.json, file OpenCode, meta.json

[5] Tulis (semua atau rollback)
     ├─ keyring: service=gemini, username=antigravity
     ├─ ~/.gemini/oauth_creds.json
     ├─ ~/.gemini/google_accounts.json (active + old)
     └─ DB: applied_target='antigravity_cli', last_applied_at=now

[6] Verifikasi
     ├─ baca ulang keyring: email & refresh token harus cocok
     └─ baca ulang ~/.gemini: harus sinkron
         └─ gagal → rollback otomatis dari [4] + tampilkan lokasi backup

[7] Sukses
     └─ dialog: email aktif, target, waktu, tombol "Salin perintah verifikasi log"
```

### 7.4 Indikator

Chip `ConfigBar` (kiri ke kanan): `📁 DB`, `🔒 Enkripsi`, **`🎯 Target`**, `📂 Folder`.

Kolom tabel baru setelah "Kategori": **"Aktif di"**.

### 7.5 Deteksi drift

Saat `reload_accounts()` dan setelah setiap Apply, app membaca kenyataan lalu membandingkan
dengan DB. Bila beda, tampilkan **satu baris banner** (bukan dialog) di antara `ConfigBar` dan
tabel:
`⚠️ Antigravity CLI aktif sebagai x@y.com, berbeda dengan DB. [Adopsi ke DB] [Tutup]`

Banner hanya muncul bila ada drift, tingginya ±28 px, dan bisa ditutup. Saat tidak ada drift,
banner **tidak memakan ruang sama sekali** (`setVisible(False)`), sehingga layout tidak bergeser.

### 7.6 Spesifikasi layout (wajib pas, tidak merepotkan)

Prinsip: **tidak menambah baris toolbar baru, tidak menambah dialog bertumpuk, tidak mengubah
ukuran window default.** Semua fitur baru masuk ke elemen yang sudah ada.

```
┌─ ConfigBarWidget (1 baris, tinggi tetap ±33 px) ──────────────────────────────┐
│ [📁 DB: Local] [🔒 Enkripsi: Nonaktif] [🎯 Target: OpenCode ▾]  Folder Aktif: │
│                                                    [ /path/ke/opencode      ] │
└──────────────────────────────────────────────────────────────────────────────┘
```
*(QLineEdit folder tetap `Stretch` mengisi sisa lebar, seperti sekarang.)*

```
┌─ Banner drift (hanya saat drift, tinggi 28 px, bisa ditutup) ────────────────┐
│ ⚠️ …                                                       [Adopsi] [Tutup] │
└──────────────────────────────────────────────────────────────────────────────┘
┌─ JsonInputWidget (tinggi awal 150 px, splitter tetap bisa digeser) ──────────┐
├─ AccountTableWidget ─────────────────────────────────────────────────────────┤
│ No │ Email │ Kategori │ Filter │ Kuota… │ Enkripsi │ Aktif di │  ← 7 kolom   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Aturan layout yang mengikat implementasi:

| # | Aturan | Alasan |
| --- | --- | --- |
| L1 | Chip Target adalah `QLabel`/`QToolButton` berteks + menu dropdown, tinggi & padding **identik** dengan chip DB/Enkripsi yang sudah ada (`padding: 4px 10px; font-size: 11px`), **bukan** `QComboBox` lebar atau toolbar kedua. | Menjaga ConfigBar tetap 1 baris. |
| L2 | Teks chip di-*elide* (`Target: Antigravity…`) bila window menyempit; tooltip menampilkan teks penuh + email aktif + status sesi `agy`. | Tidak memaksa window melebar. |
| L3 | Urutan: `[DB] [Enkripsi] [Target]` lalu `Folder Aktif:` + `QLineEdit` dengan `stretch=1` dan `minimumWidth=120`. Chip Target berukuran tetap (`sizeHint`), tidak ikut melar. | Tombol/field folder tetap terlihat di layar kecil. |
| L4 | Kolom **"Aktif di"** `ResizeToContents`, lebar maksimal ±110 px, isi hanya `OpenCode` / `Antigravity CLI` / `—`. | Kolom baru tidak mendominasi tabel. |
| L5 | Ukuran window default tetap **1100×700**; tidak ada `resize()` baru. Bila 7 kolom tidak muat, yang mengecil adalah kolom Email/Filter (sudah `Stretch`), bukan muncul scroll horizontal permanen. | Perilaku lama tidak berubah. |
| L6 | Apply **tidak** lewat dialog bertumpuk: akses lewat **klik kanan akun → "Terapkan ke…"** dan **double-click** untuk target aktif. Tidak ada tombol Apply tambahan di toolbar. | Satu jalur aksi, cepat dipakai. |
| L7 | Dialog kill proses (`process_dialog.py`) ukuran tetap ±480×320, daftar PID di `QListWidget` yang bisa scroll; **tidak** memaksa window utama berubah ukuran. | Dialog panjang tidak menggeser layout. |
| L8 | Pesan sukses/gagal memakai `QMessageBox` standar (bukan panel permanen), sehingga tidak menambah tinggi layout. | Tidak mengurangi area tabel. |
| L9 | Semua label status memakai font 11 px seperti chip yang sudah ada; tidak ada ikon besar/gambar baru selain emoji 1 karakter. | Konsistensi visual. |
| L10 | Layout harus tetap bisa dipakai pada lebar minimum **900 px** tanpa scroll horizontal pada ConfigBar. | Laptop 1366×768 tetap nyaman. |

---

## 8. Kebutuhan fungsional

| ID | Kebutuhan | Prioritas |
| --- | --- | --- |
| FR-01 | Memilih Target global; pilihan persist antar sesi (`QSettings.active_target`). | Wajib |
| FR-02 | Chip indikator Target di ConfigBar, ikut berubah saat pilihan diganti. | Wajib |
| FR-03 | Kolom "Aktif di" di tabel akun. | Wajib |
| FR-04 | Status Active Account per target dibaca dari keyring/file (bukan setting). | Wajib |
| FR-05 | Apply Account → OpenCode sebagai upsert + `activeIndex`, dengan backup. | Wajib |
| FR-06 | Apply Account → Antigravity CLI (keyring + `~/.gemini`), dengan validasi token lebih dulu. | Wajib |
| FR-07 | Deteksi & hentikan proses `agy` sesuai §9 (termasuk `T`/stopped → `SIGCONT`+`SIGTERM`+`SIGKILL`); default selalu konfirmasi. | Wajib |
| FR-08 | Simpan `applied_target` + `last_applied_at` di DB (migrasi aditif). | Wajib |
| FR-09 | Backup sebelum menulis + tombol/menu **Restore Backup Terakhir**. | Wajib |
| FR-10 | Rollback otomatis bila salah satu langkah tulis gagal. | Wajib |
| FR-11 | Deteksi drift + aksi "Adopsi ke DB" (opsional, bisa v1.1). | Sebaiknya |
| FR-12 | Impor sekali dari `~/.config/antigravity/accounts.json` dan/atau `antigravity-accounts.json`. | Sebaiknya |
| FR-13 | Pengaturan: `auto_kill_agy` (default OFF), `write_gemini_files` (default ON). | Wajib |
| FR-14 | Tombol "Salin perintah verifikasi" (`grep 'authenticated successfully as' ...`). | Sebaiknya |
| FR-15 | Tampilkan target CLI nonaktif di OS yang tidak didukung. | Wajib |
| FR-16 | Layout mengikuti §7.6 (L1–L10): tanpa toolbar baru, window default tetap 1100×700, ConfigBar tetap 1 baris pada lebar ≥900 px. | Wajib |
| FR-17 | Status sesi `agy` terlihat tanpa membuka dialog (tooltip chip Target) dan diperbarui setelah kill/Apply. | Wajib |
| FR-18 | Kegagalan baca `/proc` atau kegagalan kill → Apply dibatalkan **tanpa menulis** apa pun (fail-safe). | Wajib |

---

## 9. Spesifikasi pengelolaan proses `agy`

Bagian ini wajib: **tidak boleh ada penulisan keyring selama masih ada proses `agy` hidup.**
Pengelolaan proses hanya berlaku untuk **Apply ke Antigravity CLI**; Apply ke OpenCode tidak
pernah memeriksa, apalagi menghentikan, proses `agy`.

### 9.1 Deteksi

- Linux: baca `/proc/<pid>/cmdline`, ambil `basename(argv[0])`, cocokkan **persis** `agy`.
  **Tidak** memakai `pkill -f` (rawan mencocokkan perintah lain yang mengandung `/agy`,
  termasuk editor/script yang menyebut path tersebut).
- Kecualikan PID aplikasi sendiri dan parent-nya.
- Baca juga `/proc/<pid>/stat` untuk state:
  `R/S/D` = berjalan/tidur, `T/t` = **stopped**, `Z` = zombie (sudah mati, menunggu reaper).
- `Z` (zombie) **tidak dianggap sesi hidup**: tidak bisa dikirimi sinyal dan tidak memegang token.
  Zombie dilaporkan terpisah sebagai informasi (`PID x zombie, akan hilang sendiri`), tidak
  memblokir Apply.
- `T` (stopped) **dianggap hidup dan berbahaya**: proses stopped menahan `SIGTERM` sampai
  di-resume, jadi `pkill` biasa tampak "tidak berefek". Karena itu:
  - kirim `SIGCONT` sebelum/bersamaan `SIGTERM`, lalu
  - tetap eskalasi ke `SIGKILL` bila belum mati setelah timeout.
- Kembalikan `list[ProcessInfo(pid, argv, state, is_remote_control)]` untuk ditampilkan.
- Proses `agy remote-control` (binary sama, argumen berbeda) ikut terdeteksi dan diberi label
  di dialog karena ikut berhenti.
- Deteksi dijalankan: (a) saat aplikasi start (read-only, tanpa dialog), (b) sebelum Apply,
  (c) tepat sebelum menulis keyring (verifikasi ulang). Total biaya tiap deteksi < 100 ms.

### 9.2 Status sesi yang ditampilkan

| Kondisi | Label | Aksi |
| --- | --- | --- |
| 0 proses | `⚪ Tidak ada sesi agy` | Apply boleh lanjut |
| ≥1 proses `R/S/D` | `🟢 N sesi berjalan` | perlu konfirmasi / kill |
| ≥1 proses `T` | `🟠 N sesi stopped (perlu SIGKILL)` | perlu konfirmasi, kill wajib eskalasi |
| hanya zombie | `⚪ Sisa zombie (tidak aktif)` | Apply boleh lanjut |
| tidak bisa baca `/proc` | `🔒 Tidak dapat memeriksa proses` | Apply **dibatalkan** (fail-safe) |

Status ini muncul di **tooltip chip Target** dan di dialog, bukan sebagai chip baru
(lihat L1/L2 pada §7.6), supaya layout tidak bertambah.

### 9.3 Dialog konfirmasi

Judul: **"Sesi Antigravity CLI masih berjalan"**

```
┌──────────────────────────────────────────────────────┐
│  Masih ada 3 sesi `agy` yang memegang token lama.    │
│  Token baru tidak ditulis sampai semua sesi berhenti.│
│                                                      │
│  PID    Status     Perintah                          │
│  52801  berjalan   agy                                │
│  52824  berjalan   agy                                │
│  53300  stopped    agy  (akan di-SIGKILL)            │
│                                                      │
│  [ ] Jangan tanya lagi (hentikan otomatis)           │
│                          [Batal]  [Hentikan Sesi]    │
└──────────────────────────────────────────────────────┘
```

- Tombol **Batal** adalah default fokus (aman); **Hentikan Sesi** ditandai destruktif.
- Checkbox menulis `auto_kill_agy=true` ke QSettings; saat aktif, dialog konfirmasi dilewati
  tetapi dialog progres tetap tampil.
- Dialog tidak menampilkan token/kredensial apa pun.

### 9.4 State machine

```
IDLE → DETECTING
        ├─ tidak ada / hanya zombie ────────────────────────→ READY_TO_WRITE
        ├─ gagal baca /proc ───────────────────────────────→ FAILED (fail-safe)
        └─ ada sesi hidup
              ↓
          AWAIT_CONFIRM ──(Batal)──────────────────────────→ CANCELLED
              ↓ (Hentikan / auto_kill)
          CONT_SENT → TERM_SENT
              ↓ poll 100 ms, maks 3000 ms
              ├─ kosong ───────────────────────────────────→ READY_TO_WRITE
              └─ masih ada → KILL_SENT → poll 100 ms, maks 2000 ms
                       ├─ kosong ──────────────────────────→ READY_TO_WRITE
                       └─ masih ada ───────────────────────→ FAILED
                                                             (jangan menulis)
```

Aturan tambahan:

- Setelah `READY_TO_WRITE`, **deteksi ulang** tepat sebelum menulis keyring. Bila proses baru
  muncul di jendela waktu itu → kembali ke `FAILED` tanpa menulis.
- Yang dikirimi sinyal **hanya PID yang terdeteksi sebagai `agy`** (verifikasi ulang
  `cmdline` sebelum `kill`, untuk menutup race PID reuse).
- Bila `os.kill` mengembalikan `ProcessLookupError` → proses sudah mati, lanjut.
- Bila `PermissionError` → tandai PID itu gagal, tampilkan saran, jangan paksa.
- Bila `auto_kill_agy=true` → lompati `AWAIT_CONFIRM`, tetap tampilkan progres dan hasil.
- Semua langkah dicatat ke log aplikasi **tanpa** token (hanya PID, state, sinyal, hasil).

### 9.5 Kasus tepi yang wajib ditangani

| Kasus | Perilaku |
| --- | --- |
| Proses `T` (stopped, sisa Ctrl-Z) | `SIGCONT` + `SIGTERM`, lalu `SIGKILL` bila perlu. Ini kasus nyata yang membuat `pkill` biasa gagal. |
| Proses `D` (uninterruptible sleep, mis. I/O) | Tidak bisa dibunuh; setelah timeout → `FAILED`, minta tutup manual. |
| PID reuse saat menunggu | Verifikasi `cmdline` sebelum setiap `kill`. |
| Proses baru muncul setelah kill | Deteksi ulang sebelum tulis; bila ada → `FAILED`. |
| Zombie | Diabaikan (tidak memblokir). |
| `/proc` tidak bisa dibaca (sandbox/Flatpak) | `FAILED` dengan pesan "periksa proses manual". |
| Proses milik user lain | Tidak terlihat/bukan urusan; hanya proses user sendiri. |
| Aplikasi dijalankan sebagai root | Peringatkan: keyring root berbeda; Apply CLI dinonaktifkan. |
| Aplikasi crash saat menunggu | Tidak ada penulisan parsial: semua tulis terjadi setelah `READY_TO_WRITE`. |

### 9.6 Threading & UI

- Deteksi/kill berjalan di **worker thread** (`run_async_task`), bukan di GUI thread, sehingga
  aplikasi tidak freeze sampai 5 detik.
- Progres ditampilkan lewat dialog kecil non-modal atau `LoadingDialog` yang sudah ada:
  `Menghentikan 3 sesi… (SIGTERM)`, lalu `… (SIGKILL)`.
- Tombol **Batal** pada dialog progres hanya membatalkan **penungguan**, bukan mengirim sinyal
  tambahan; Apply berakhir `CANCELLED` tanpa menulis.
- Setelah selesai, UI melakukan refresh status target (chip + kolom "Aktif di").

### 9.7 Pesan gagal & pemulihan

```
Tidak dapat menghentikan 2 sesi agy (PID 123, 456).
Tutup manual dari terminal (`/quit`), atau jalankan:
    pkill -9 -x agy
lalu ulangi Apply. Tidak ada perubahan yang ditulis.
```

- Pesan menyebut **perubahan tidak terjadi** agar pengguna tenang.
- Tombol **Salin perintah** menyalin `pkill -9 -x agy`.
- Bila kegagalan terjadi setelah backup dibuat (mis. gagal verifikasi), backup tetap disimpan
  dan ditawarkan lewat **Restore Backup Terakhir**.

---

## 10. Perubahan teknis

### 10.1 Modul baru

```
src/integrations/__init__.py
src/integrations/antigravity/__init__.py
src/integrations/antigravity/constants.py        # client OAuth, path, atribut keyring
src/integrations/antigravity/errors.py           # ApplyError, KeyringError, OAuthError
src/integrations/antigravity/keyring_linux.py    # Secret Service via python3-dbus
src/integrations/antigravity/keyring_base.py     # Protocol + NullKeyring (OS lain)
src/integrations/antigravity/oauth.py            # refresh token -> access/id token
src/integrations/antigravity/gemini_files.py     # ~/.gemini/oauth_creds.json + google_accounts.json
src/integrations/antigravity/opencode_file.py    # upsert + activeIndex
src/integrations/antigravity/process_manager.py  # deteksi & kill `agy`
src/integrations/antigravity/backup.py           # snapshot & restore
src/integrations/antigravity/service.py          # orkestrasi: build_plan() / apply() / status()
src/ui/components/target_badge.py                # chip target + menu (ringkas, §7.6 L1)
src/ui/components/drift_banner.py                # banner drift 1 baris, hidden saat normal
src/ui/components/process_dialog.py              # dialog konfirmasi + progres kill
```

`src/integrations/antigravity/service.py` adalah satu-satunya pintu yang dipanggil UI:

```python
build_apply_plan(account_id, target, *, password) -> ApplyPlan
apply(plan, *, confirm_kill_cb) -> ApplyResult
read_status() -> TargetStatus   # active email per target + drift
restore_last_backup() -> RestoreResult
```

UI **tidak** memanggil `dbus`, `urllib`, atau menulis file secara langsung.

### 10.2 Perubahan file yang ada

| File | Perubahan |
| --- | --- |
| `src/database.py` | Migrasi `ALTER TABLE accounts ADD COLUMN applied_target/last_applied_at`; `fetch_accounts_summary()` menambah 2 kolom; method `mark_applied(account_id, target)`. |
| `src/ui/main_window.py` | Simpan/muat `active_target`; handler Apply per target; refresh indikator; cek drift; menu Restore Backup. |
| `src/ui/components/config_bar.py` | Tambah chip Target + `set_target_status()`. |
| `src/ui/components/account_table.py` | Kolom ke-7 "Aktif di"; menu konteks "Terapkan ke…"; sinyal `apply_requested(account_id, target)`. |
| `src/ui/components/settings_dialog.py` | Group baru "Integrasi": `auto_kill_agy`, `write_gemini_files`, tombol "Impor dari file lama". |
| `requirements.txt` | Tidak berubah (stdlib + PyQt6 + cryptography; `python3-dbus` hanya Linux, dideteksi runtime). |
| `packaging/linux/*` | Tambah dependency `python3-dbus` pada `.deb` (Recommends/Depends). |

### 10.3 Migrasi DB

```sql
ALTER TABLE accounts ADD COLUMN applied_target TEXT DEFAULT NULL;
ALTER TABLE accounts ADD COLUMN last_applied_at INTEGER DEFAULT NULL;
```

- Dijalankan idempoten: abaikan error "duplicate column name".
- Untuk Turso, jalankan `ALTER` yang sama; kolom baru berada di tabel yang sama.
- Tidak ada perubahan pada tabel `account_fingerprints`, `account_quotas`, `categories`.

### 10.4 Format data

Keyring item (`service=gemini`, `username=antigravity`):

```json
{
  "token": {
    "access_token": "ya29...",
    "token_type": "Bearer",
    "refresh_token": "1//...",
    "expiry": "2026-11-19T01:43:23.478972+08:00",
    "expires_in": 3599
  },
  "auth_method": "consumer",
  "id_token_email": "user@example.com",
  "writer_id": "<43 char base64url>"
}
```

`~/.gemini/oauth_creds.json`: `{access_token, scope, token_type, id_token, expiry_date, refresh_token}`.

`~/.gemini/google_accounts.json`: `{active: email, old: [emails]}` (email lama ditambahkan, tidak dihapus).

---

## 11. Kebutuhan non-fungsional

| ID | Kebutuhan |
| --- | --- |
| NFR-01 | Token tidak pernah ditulis ke log/UI dalam bentuk utuh; selalu diredaksi (`1//0gTw…Q4pM`). |
| NFR-02 | File sensitif `0600`, direktori `0700`; penulisan atomic; tidak mengikuti symlink. |
| NFR-03 | Apply CLI tidak boleh menyentuh item keyring lain (Chrome, GOA, Obsidian, dll.). |
| NFR-04 | Operasi jaringan (refresh token) berjalan di worker thread; UI tidak freeze (pakai `run_async_task`/`LoadingDialog`). |
| NFR-05 | Semua kegagalan tulis harus menghasilkan rollback atau meninggalkan backup yang bisa dipulihkan. |
| NFR-06 | Fitur tetap berfungsi (dengan target CLI nonaktif) bila `python3-dbus` tidak ada. |
| NFR-07 | Waktu Apply CLI yang wajar: < 5 detik tanpa sesi `agy`, < 7 detik bila perlu kill (≤3 s TERM + ≤2 s KILL + overhead). |
| NFR-08 | Tidak ada dependensi pip baru; `python3-dbus` bersifat opsional-runtime (Linux). |
| NFR-09 | Deteksi proses max 100 ms dan berjalan di worker thread; GUI thread tidak pernah menunggu `sleep`. |
| NFR-10 | Layout tidak boleh menambah tinggi/lebar yang membuat tabel akun menyusut; lihat §7.6 (L1–L10). Diuji pada 1100×700 dan 900×600. |
| NFR-11 | Tidak ada dialog modal yang muncul saat idle; dialog hanya pada aksi pengguna atau kegagalan drift. |

---

## 12. Keamanan & kepatuhan

- Gunakan hanya untuk akun milik pengguna sendiri; berbagi/menjual akun melanggar ToS Google.
- Password enkripsi tidak pernah disimpan oleh fitur ini; hanya dipakai untuk dekripsi sesaat.
- Jangan menampilkan refresh token di UI; bila perlu verifikasi, tampilkan prefix/suffix.
- Backup berisi kredensial → harus `0600` dan disebutkan di dialog agar pengguna sadar.
- Menghapus akun dari DB tidak otomatis logout dari target; sediakan aksi terpisah (lihat §15).

---

## 13. Matriks status indikator

| Target | Kondisi | Chip ConfigBar | Kolom "Aktif di" |
| --- | --- | --- | --- |
| OpenCode | file terbaca, email cocok DB | `🎯 Target: OpenCode` + `🟢 user@x` | `OpenCode` |
| OpenCode | file terbaca, email tidak ada di DB | `🟡 Tidak tercatat` | `—` + tooltip email |
| OpenCode | file tidak ada/rusak | `🔴 File tidak valid` | `—` |
| CLI | keyring email cocok DB | `🎯 Target: Antigravity CLI` + `🟢 user@x` | `Antigravity CLI` |
| CLI | keyring kosong | `⚪ Belum login` | `—` |
| CLI | keyring ≠ `~/.gemini` | `🟡 Drift (~/.gemini)` | `Antigravity CLI` |
| CLI | OS ≠ Linux / D-Bus mati | `⛔ Tidak tersedia` | `—` |
| CLI | keyring terkunci | `🔒 Keyring terkunci` | `—` |

---

## 14. Kriteria penerimaan

**AC-01 — Pilihan target bertahan**
```
Given aplikasi terbuka
When pengguna memilih Target = Antigravity CLI
Then chip berubah dan QSettings.active_target == "antigravity_cli"
When aplikasi ditutup dan dibuka lagi
Then chip tetap Antigravity CLI
```

**AC-02 — Apply OpenCode tidak menghapus akun lain**
```
Given file antigravity-accounts.json berisi 3 akun
When pengguna Apply akun ke-4 ke OpenCode
Then file berisi 4 akun, activeIndex menunjuk akun ke-4, akun lain utuh
And backup file lama tersimpan
```

**AC-03 — Apply CLI menolak bila token invalid**
```
Given refresh token akun sudah dicabut
When pengguna Apply ke Antigravity CLI
Then proses dibatalkan sebelum backup/keyring ditulis
And pesan menyebut invalid_grant + saran /login
```

**AC-04 — Apply CLI dengan sesi berjalan**
```
Given ada 2 proses agy
When pengguna Apply ke CLI dan memilih "Hentikan Sesi"
Then kedua proses menerima SIGTERM, lalu SIGKILL bila perlu
And keyring baru ditulis hanya setelah verifikasi tidak ada proses agy
```

**AC-05 — Kill gagal → tidak menulis**
```
Given proses agy menolak berhenti (tidak bisa di-kill)
When Apply ke CLI
Then aplikasi membatalkan tanpa menulis keyring/`~/.gemini`
And menampilkan PID yang perlu ditutup manual
```

**AC-06 — Rollback**
```
Given penulisan keyring berhasil tetapi penulisan oauth_creds.json gagal
When Apply ke CLI
Then keyring + file dipulihkan dari backup
And dialog menyebut lokasi backup
```

**AC-07 — Indikator dari kenyataan**
```
Given pengguna mengganti akun CLI dari terminal (agy-switch / login manual)
When aplikasi di-refresh
Then chip dan kolom "Aktif di" menampilkan akun baru dari keyring
And drift ditandai bila berbeda dengan DB
```

**AC-08 — OS tidak didukung**
```
Given aplikasi berjalan di Windows
Then Target Antigravity CLI tampil nonaktif dengan tooltip alasan
And aksi Apply ke CLI tidak bisa dipilih
```

**AC-09 — Proses stopped (`T`) tetap bisa dihentikan**
```
Given ada 3 proses agy berstatus T (sisa Ctrl-Z)
When pengguna Apply ke CLI dan memilih "Hentikan Sesi"
Then aplikasi mengirim SIGCONT + SIGTERM
And setelah ≤3 s masih ada, aplikasi mengirim SIGKILL
And Apply lanjut hanya bila deteksi ulang menunjukkan tidak ada proses hidup
```

**AC-10 — Deteksi ulang menutup race**
```
Given semua sesi sudah dihentikan
And pengguna membuka `agy` lagi tepat sebelum penulisan keyring
When aplikasi melakukan deteksi ulang sebelum menulis
Then Apply dibatalkan (FAILED) dan tidak ada keyring/file yang ditulis
```

**AC-11 — Layout tetap pas**
```
Given window default 1100×700
When fitur target ditambahkan
Then ConfigBar tetap 1 baris, tidak ada toolbar baru
And tabel tetap menampilkan 7 kolom tanpa scroll horizontal permanen
And window tidak berubah ukuran saat aplikasi dibuka
Given window dikecilkan ke 900×600
Then ConfigBar tetap terbaca (teks chip di-elide + tooltip)
And tombol Folder tetap terlihat
```

**AC-12 — Tidak ada penulisan saat proses tidak bisa diperiksa**
```
Given /proc tidak dapat dibaca (sandbox)
When pengguna Apply ke Antigravity CLI
Then aplikasi berhenti dengan pesan "periksa proses manual"
And tidak ada keyring/file/DB yang berubah
```

---

## 15. Rencana pengujian

- **Unit**: `oauth` (parsing id_token, error mapping), `opencode_file` (upsert & activeIndex),
  `gemini_files` (atomic + old-email), `backup` (create/restore), `process_manager`
  (parsing `/proc` + state `T`/`Z`, state machine dengan PID tiruan, verifikasi ulang sebelum kill).
- **Integrasi (Linux, manual/CI)**: keyring item sementara (`service=selftest`) untuk write/read/delete;
  tidak pernah memakai item `gemini` asli. Uji kill nyata dengan proses `sleep` yang di-`SIGSTOP`
  lalu dipastikan tetap bisa dihentikan lewat jalur TERM→KILL.
- **UI**: QTest untuk chip target & kolom baru; smoke test Apply dengan folder/file fixture;
  uji ukuran 1100×700 dan 900×600 (tidak ada scroll horizontal ConfigBar, tinggi tabel tidak turun).
- **Regresi**: 6 kolom lama tetap berfungsi; filter/sortir/kategori tidak berubah.

---

## 16. Rencana rilis

| Tahap | Isi |
| --- | --- |
| v1.0 | FR-01…FR-10, FR-13, FR-15, **FR-16…FR-18** (target global, apply 2 target, kill aman termasuk `T`, layout §7.6, backup/rollback, migrasi DB) |
| v1.1 | FR-11 drift + adopsi, FR-12 impor file lama, FR-14 salin perintah verifikasi |
| v2.0 | Backend keyring Windows (Credential Manager) & macOS (Keychain) |

---

## 17. Pertanyaan terbuka (ronde berikutnya)

| # | Pertanyaan | Rekomendasi |
| --- | --- | --- |
| O1 | Apakah memilih target juga otomatis menerapkan ulang akun terakhir di target itu? | **Tidak**; pilih target hanya mengubah mode. Apply tetap aksi eksplisit. |
| O2 | Saat target = OpenCode, apakah menu "Terapkan ke Antigravity CLI" tetap muncul? | **Ya**, tetapi diberi label "ganti target dulu" bila target berbeda, atau langsung menawarkan pindah target. Pilih salah satu. |
| O3 | Apakah Apply ke CLI selalu menulis `~/.gemini` (bisa dimatikan di Pengaturan)? | **Ya**, default ON, sesuai permintaan awal. |
| O4 | Retensi backup 30 cukup? | **Ya**, 30, dengan tombol "Bersihkan backup". |
| O5 | Perlu aksi "Logout dari CLI" (hapus item keyring) di UI? | **Ya**, di v1.1, dengan konfirmasi. |
| O6 | Kalau akun di DB belum punya fingerprint/project, apakah Apply ke OpenCode tetap boleh? | **Ya**, tulis apa adanya; validasi hanya pada `refresh_token`. |
| O7 | Nama kolom: "Aktif di" vs "Target Aktif"? | **"Aktif di"**, lebih singkat. |
| O8 | Apakah project `antigravity-switch` (CLI mandiri) dipertahankan? | **Ya**, sebagai referensi & tool darurat; kode disalin ke app. |

---

## 18. Lampiran — pemetaan dari `antigravity-switch`

| Modul lama (`~/Projects/Python3/antigravity-switch/agy_switch/`) | Tujuan di app |
| --- | --- |
| `keyring.py` | `src/integrations/antigravity/keyring_linux.py` |
| `oauth.py` | `src/integrations/antigravity/oauth.py` |
| `gemini_files.py` | `src/integrations/antigravity/gemini_files.py` |
| `backup.py` + `storage.py` | `src/integrations/antigravity/backup.py` (+ util atomic) |
| `process.py` | `src/integrations/antigravity/process_manager.py` (ditingkatkan: TERM→KILL) |
| `vault.py` | **Tidak dipindahkan** (digantikan DB); hanya dipakai untuk impor sekali |
| `cli.py` | Dipecah: alur → `service.py`, tampilan → UI PyQt6 |
| `constants.py` | `src/integrations/antigravity/constants.py` |

Perbedaan perilaku yang disengaja:
1. Token **selalu** divalidasi ke Google sebelum menulis (tidak ada jalur "tulis dulu").
2. OpenCode memakai upsert, bukan timpa total.
3. Kill proses: `SIGCONT` → `SIGTERM` → `SIGKILL` bertahap (menangani sesi `T`/stopped),
   bukan `SIGKILL` langsung dan bukan `pkill -f`.
4. Status dibaca ulang dan dibandingkan dengan DB (drift detection).
5. Layout tidak ditambah toolbar/dialog baru (§7.6).

---

## 19. Riwayat dokumen

| Versi | Tanggal | Perubahan |
| --- | --- | --- |
| 0.1 | 2026-11-19 | Draf awal hasil grill ronde 1 (D1–D12, alur, FR/NFR, AC). |
| 0.2 | 2026-11-19 | Tambah §7.6 spesifikasi layout (L1–L10, AC-11), perluas §9 pengelolaan proses `agy` (state `T`/`Z`, `SIGCONT`, state machine, kasus tepi, threading, pesan gagal), tambah FR-16…FR-18, NFR-09…NFR-11, AC-09…AC-12, modul `drift_banner.py` & `process_dialog.py`. |
