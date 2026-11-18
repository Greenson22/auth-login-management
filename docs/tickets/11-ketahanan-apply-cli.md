# 11: Ketahanan Apply CLI — error, rollback, rotasi token, toggle file

**What to build:** Apply ke Antigravity CLI gagal dengan aman. Token mati atau milik akun lain tidak pernah ditulis, setiap kegagalan setelah penulisan pertama di-rollback penuh, refresh token hasil rotasi disimpan agar tidak ada dua kebenaran, dan pengguna bisa memilih hanya memperbarui keyring tanpa menyentuh `~/.gemini`.

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] `invalid_grant` dipetakan ke pesan "login ulang" dan `unauthorized_client` ke pesan token bukan milik client Antigravity; tidak ada penulisan maupun backup.
- [ ] `id_token` tanpa email atau email berbeda dari akun menggagalkan Apply sebelum backup dan tanpa penulisan.
- [ ] Bila Google mengembalikan refresh token baru, keyring dan DB memakai token baru; konfigurasi akun di DB tetap source of truth.
- [ ] `write_gemini_files=false` hanya menulis keyring dan DB; tidak ada file `~/.gemini` yang ditulis atau dibuat, dan verifikasi file dilewati.
- [ ] Kegagalan menulis `oauth_creds.json` setelah keyring berhasil memicu pemulihan keyring dan file lain; DB tidak ditandai.
- [ ] Ketidakcocokan saat verifikasi memicu rollback penuh dan pesan memuat lokasi backup.
- [ ] Kegagalan menandai DB memicu rollback keyring dan file.
- [ ] Pesan kegagalan menyebut langkah yang gagal, tindakan berikutnya, dan secara eksplisit apakah perubahan sudah di-rollback atau belum.
- [ ] Kegagalan jaringan tidak di-retry otomatis; pengguna memilih Apply lagi.
- [ ] Rate limit atau respons Google non-JSON dipetakan ke pesan "coba lagi" tanpa membocorkan respons mentah.
- [ ] Kegagalan dekripsi memakai pesan yang sudah ada agar konsisten dengan fitur copy/update.
- [ ] Tidak ada token utuh di dialog, pesan error, atau log; nilai yang perlu disebut diredaksi dengan pola awal/akhir.
- [ ] Password enkripsi hanya dipakai sesaat untuk dekripsi dan tidak disimpan atau ditulis ulang oleh fitur ini.
