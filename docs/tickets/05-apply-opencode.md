# 05: Apply ke OpenCode end-to-end

**What to build:** Pengguna bisa menerapkan satu akun ke target OpenCode lewat klik kanan atau double-click. Akun baru ditambahkan tanpa menghapus akun lain, entri dengan email sama diganti di tempat, `activeIndex` menunjuk akun yang baru, backup dibuat sebelum menulis, dan file ditulis atomic dengan mode `0600`. Apply OpenCode tidak pernah menyentuh keyring atau proses `agy`.

**Blocked by:** 03, 04

**Status:** ready-for-agent

- [ ] Build plan gagal — sebelum backup dan penulisan — bila folder target tidak valid, file tidak ada, isinya bukan objek JSON, atau `accounts` bukan array.
- [ ] File berisi 3 akun lalu Apply akun ke-4 menghasilkan 4 akun; akun lama utuh, akun baru berada di akhir.
- [ ] Email yang sudah ada dengan kapitalisasi berbeda menggantikan entri lama di posisi yang sama, tanpa duplikat.
- [ ] Snapshot akun diambil dari rekonstruksi DB, bukan dengan menulis konfigurasi hasil rekonstruksi satu akun apa adanya.
- [ ] `activeIndex` menunjuk indeks hasil upsert; `activeIndexByFamily.gemini` dan `.claude` diubah hanya bila kuncinya sudah ada, dan kunci yang tidak ada tidak dibuat.
- [ ] Field top-level lain (misalnya `version`) dan seluruh akun lain dipertahankan.
- [ ] Backup file lama dibuat sebelum penulisan; kegagalan plan tidak menghasilkan backup.
- [ ] Penulisan atomic lewat file sementara di direktori yang sama + `os.replace`, mode `0600`, tanpa mengikuti symlink.
- [ ] Apply sukses menandai DB `applied_target='opencode'` dan `last_applied_at` waktu epoch detik.
- [ ] Dialog sukses standar menampilkan email dan jumlah akun di file.
- [ ] Apply OpenCode tidak memanggil port proses maupun keyring, dan tidak membaca/menulis `~/.gemini`.
- [ ] Menu konteks akun memiliki submenu "Terapkan ke…" berisi OpenCode dan Antigravity CLI; item CLI disabled dengan alasan saat target tidak tersedia.
- [ ] Double-click pada baris akun menjalankan Apply ke Selected Target; tidak ada tombol Apply baru di toolbar.
