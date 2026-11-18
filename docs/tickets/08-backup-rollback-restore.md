# 08: Backup, rollback, dan restore

**What to build:** Setiap Apply punya titik pulih. Snapshot keyring dan file target dibuat sebelum penulisan, kegagalan memicu rollback otomatis, dan pengguna bisa memulihkan backup terakhir lewat menu tanpa mencari file sendiri.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Direktori backup `~/.local/state/auth-login-management/backups/<timestamp>/` bermode `0700` dan file di dalamnya `0600`.
- [ ] Setiap backup berisi salinan item keyring dan file target yang ada pada saat itu.
- [ ] `meta.json` mencatat target, email, waktu, versi aplikasi, PID yang dihentikan, dan daftar artefak beserta status "ada"/"tidak ada".
- [ ] Restore mengembalikan isi artefak yang ada, dan menghapus artefak yang sebelumnya tidak ada — baik item keyring maupun file.
- [ ] Restore tidak mengubah kolom audit DB; indikator tetap membaca kenyataan.
- [ ] Retensi menyisakan 30 backup terbaru dan dilakukan setelah Apply sukses, sehingga backup yang baru dibuat tidak ikut terhapus.
- [ ] Rollback otomatis mengembalikan keyring dan file dari snapshot lalu melaporkan kegagalan asli; penandaan DB tidak pernah terjadi lebih dulu.
- [ ] Bila kegagalan terjadi setelah snapshot dibuat, snapshot dipertahankan dan lokasinya disebutkan di dialog kegagalan.
- [ ] Menu Pengaturan memiliki aksi "Pulihkan Backup Terakhir…" dengan konfirmasi yang menyebut waktu, target, dan email dari manifest, serta menyatakan bahwa backup berisi kredensial.
- [ ] Tidak ada backup, keyring, atau file lain yang dibaca/ditulis ketika tidak ada backup.
