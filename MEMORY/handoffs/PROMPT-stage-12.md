# Prompt tahap 12 untuk agen sebelah: yang bisa dikerjakan tanpa host dan tanpa keputusan pemilik

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = 588acd7`; `origin/main` ada di `302aa30` (dua commit terakhir, `3852466` dan `588acd7`, belum di-push).
Agen utama (Claude) tidak mengimplementasi tugas-tugas ini; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Lima tugas utama (A sampai E) dan satu opsional (F). **Kamu tidak punya akses SSH ke VM, tidak membangun atau mendorong image, tidak men-deploy, dan tidak menyentuh produksi.** Semua yang menyentuh host dikerjakan agen utama atau pemilik.

## 0. Baca dulu
`CLAUDE.md` (tabel Traps), `AGENTS.md`, `MEMORY/handoffs/INDEX.md` dan `2026-11-17-V-W-X-offhost-backup-firewall-plan.md` (handoff-mu sendiri), `docs/10-OPERATIONS/08-HOST-FIREWALL-PLAN.md` (termasuk bagian "Owner decisions recorded"),
`MEMORY/records/2026-11-17-w2-firewall-stage1-answers.md`, `MEMORY/records/2026-11-17-host-port-inventory.md`, `deploy/host/firewall/docker-user.nft`, `deploy/trader/aidss-anchor.sh`, `deploy/trader/aidss-anchor.cron`,
`tests/trader/test_aidss_anchor_script.py`, `docs/10-OPERATIONS/09-MIGRATION-RUNBOOK.md`. Untuk Tugas F: `deploy/trader/import_owner_profile.py` dan `tests/trader/test_import_owner_profile.py`.

## 1. Keadaan (fakta)
- Produksi berjalan di VM `10.1.200.13`; Trader `HALTED`, tidak pernah menyentuh exchange. `audit-anchor` terpasang di host (cron per jam, `/var/lib/aidss-anchor/anchor.jsonl` append-only); eksekusi cron pertama belum teramati dan belum ada peringatan bila anchor gagal.
- Jawaban pemilik untuk firewall tahap 1 (2026-11-17, sudah dirender ke draf, **belum diterapkan dan belum divalidasi `nft`**): SSH (22) dan Portainer (8000, 9443) hanya dari `10.1.101.0/24` dan `wt0`; IPv6 remote baru ditolak; proyek lain tidak disentuh di tahap 1. Netbird dimasukkan lewat interface `wt0`, bukan CIDR. Pemilik adalah admin netbird.
- Docker tersedia di mesin ini (Docker Desktop, 29.x). `nft` tidak terpasang secara native.
- Lima tes `test_aidss_anchor_script.py` gagal di PATH Windows biasa karena memilih `C:\Windows\system32\bash.exe` (WSL); lulus bila Git Bash didahulukan.
- Tes yang gagal sejak lama dan **di luar lingkup**: `tests/test_output_language.py::test_translation_covers_every_prose_field` (di `src/aidss`, dilarang disentuh).

## 2. Aturan keras
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit; tidak ada passphrase atau password di argumen, variabel lingkungan, berkas, atau keluaran. Tidak ada panggilan ke Indodax atau layanan eksternal apa pun, termasuk Telegram. Artefak uji ke direktori sementara, bukan repo.
- Jangan edit `tests/test_architecture_constraints.py`, `docker-compose.yml`, `Dockerfile*`, `alembic*`, `src/`, `frontend/`. Jangan push. Stage per nama berkas (jangan `git add -A`). Jangan `ruff format` pada direktori; satu berkas boleh.
- Berkas `*.sh`, `*.cron`, `*.nft` harus LF; periksa dengan `file` atau `od -c` bahwa tidak ada CR.
- Kita memakai working tree yang sama: periksa `git status` dulu, jangan menjalankan tes saat agen utama sedang mengubah berkas.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan". Skrip yang mengubah firewall atau menyentuh host **tidak boleh dijalankan terhadap host**; cukup `sh -n` dan uji dengan stub.
- Kontainer Docker lokal hanya untuk validasi sintaks: tanpa `--network host`, tanpa `--privileged`, tanpa mount dari repo selain berkas draf `:ro`, dihapus (`--rm`) setelah selesai.
- Gaya tulisan: aturan antislop berlaku (tanpa em dash, tanpa angka karangan, komentar menjelaskan alasan).

## 3. Tugas A: tes anchor tidak boleh bergantung pada PATH pemilik
Berkas: `tests/trader/test_aidss_anchor_script.py` saja (tes, bukan skrip). Pilih Git Bash secara eksplisit seperti `tests/trader/test_host_firewall_drafts.py` (`C:/Program Files/Git/bin/bash.exe` bila ada, selain itu `shutil.which("bash")`), dan pastikan PATH yang diberikan ke subproses mengutamakan `usr/bin` Git agar `sed`, `head`, `cut` yang dipakai skrip tersedia.
Bukti: `python -m pytest tests/trader/test_aidss_anchor_script.py -q` lulus **tanpa** mengubah PATH shell dari luar. Jangan mengubah `aidss-anchor.sh`.

## 4. Tugas B: validasi sintaks draf firewall dengan `nft -c` di kontainer sementara
Berkas: `deploy/host/firewall/validate-draft.sh` (baru; hanya dijalankan di mesin pengembang), perbaikan `deploy/host/firewall/docker-user.nft` bila `nft` menemukan kesalahan, tes `tests/trader/test_host_firewall_drafts.py` (tambah, lewati bila tidak ada `docker`).
1. Skrip menjalankan `docker run --rm --cap-add NET_ADMIN --network none -v <draf>:/draft.nft:ro alpine:<tag> sh -c "apk add nftables && nft -c -f /draft.nft"`. Tag image dipin (bukan `latest`); `apk add` butuh jaringan, jadi gunakan `--network none` hanya bila image sudah berisi `nft`, atau bangun sekali dengan dua langkah (unduh paket dulu, jalankan cek tanpa jaringan). Pilih cara yang bisa kamu buktikan dan tulis alasannya.
2. `nft -c` hanya memeriksa, tidak memuat apa pun. Jangan pernah menjalankan `nft -f` tanpa `-c`, dan jangan `--privileged`.
3. Perhatikan dua hal yang bisa gagal karena kernel kontainer, bukan karena draf: dukungan `ct original proto-dst` dan set `flags interval`. Bila `nft -c` gagal karena kernel (bukan sintaks), katakan begitu dan jangan mengubah draf untuk mengakalinya; catat sebagai "tidak tervalidasi di lingkungan ini".
4. Hasil yang diharapkan di record: versi `nft`, versi kernel kontainer, keluaran asli, dan apakah draf lolos. Bila ada kesalahan sintaks nyata, perbaiki draf dengan perubahan minimal dan tes yang mereproduksinya.
5. Tambahkan juga pemeriksaan statis di tes: setiap `elements` di draf sama dengan jawaban pemilik, tidak ada `flush ruleset`, dan tidak ada CIDR `100.` (sudah ada; jangan duplikasi).

## 5. Tugas C: skrip inventaris klien host (hanya-baca, dijalankan agen utama atau pemilik nanti)
Berkas: `deploy/host/firewall/inventory-clients.sh`, `tests/trader/test_inventory_clients.py`, satu bagian di dokumen 08 ("Stage 2 inventory") yang menjelaskan cara memakainya.
Tujuan: bahan keputusan tahap 2 (proyek lain) tanpa menebak. Skrip hanya membaca; tidak mengubah apa pun, tidak mengirim apa pun keluar.
1. Untuk setiap port dari tabel dokumen 08 (daftar port dibaca dari argumen atau konstanta yang kamu jelaskan, bukan ditebak): proses pemilik (`ss -ltnp`), kontainer dan proyek Compose (`docker ps`/label `com.docker.compose.project`), dan **klien yang sedang tersambung** (`ss -tn state established`, dikelompokkan per alamat sumber dan per /24, dengan jumlah). IPv4 dan IPv6 dipisah.
2. **Identifikasi java di 6547:** cetak nama executable, PID, pengguna, `cwd` (`/proc/PID/cwd`), dan unit systemd bila ada. **Jangan cetak `cmdline` atau environ** (bisa memuat secret); cetak hanya panjangnya.
3. Keluaran tidak memuat isi paket, header, atau data aplikasi. Tulis di bantuan bahwa daftar klien bersifat sesaat: nol klien sekarang tidak berarti tidak dipakai; sarankan menjalankannya beberapa kali pada jam berbeda dan menyimpan hasilnya.
4. Tes dengan stub `ss`, `docker`, `ps`, `systemctl` di PATH sementara; periksa pengelompokan /24, pemisahan IPv4/IPv6, bahwa `cmdline` tidak pernah muncul di keluaran meski stub mengisinya dengan string bertanda, dan bahwa skrip tidak memanggil perintah lain yang mengubah keadaan.
Jangan menjalankannya terhadap host.

## 6. Tugas D: pemantau kesegaran anchor (tanpa Telegram, tanpa token)
Berkas: `deploy/trader/aidss-anchor-watch.sh`, `deploy/trader/aidss-anchor-watch.cron` (draf, tidak dipasang), `tests/trader/test_aidss_anchor_watch.py`, satu bagian di `docs/10-OPERATIONS/06-RUNBOOKS.md` (runbook singkat "anchor stale or failing").
Masalah: tidak ada yang memberi tahu bila cron anchor berhenti atau gagal terus. Skrip ini, dijalankan terpisah dari anchor, membaca `anchor.log` dan `anchor.jsonl` (jalur dari variabel lingkungan seperti `aidss-anchor.sh`) dan:
1. keluar `0` bila baris `rc=0` terakhir lebih baru dari ambang (`AIDSS_ANCHOR_MAX_AGE_S`, **tanpa default tersembunyi**: bila tidak diset, keluar `3` dengan pesan jelas; jangan mengarang angka, tulis di runbook bahwa ambang adalah keputusan pemilik, mis. pertanyaan pilihan ganda di handoff);
2. keluar `1` bila basi, `2` bila baris terakhir adalah `rc=2` (rantai audit rusak, perlakukan paling keras), `4` bila berkas tidak ada;
3. mencatat lewat `logger -p user.err`/`user.crit`, dan menjalankan kait opsional `AIDSS_ANCHOR_ALERT_CMD` **hanya bila diset** dengan pesan tetap sebagai satu argumen (tanpa shell, tanpa isi log di dalamnya). Tidak ada pengirim bawaan; token atau kanal notifikasi adalah keputusan pemilik.
4. tidak menulis ke `anchor.jsonl`, tidak memanggil Docker, tidak menyentuh database.
Tes dengan berkas log sintetis dan jam yang dikontrol (variabel `AIDSS_ANCHOR_NOW` khusus uji atau stub `date`): segar, basi, `rc=2`, berkas hilang, ambang tidak diset, kait terpanggil sekali dan tidak membawa isi log.

## 7. Tugas E: sinkronisasi dokumen
1. `docs/10-OPERATIONS/09-MIGRATION-RUNBOOK.md`: langkah B.4 masih menulis "when it exists"; `deploy/trader/backup_offhost.sh` sudah ada, ganti dengan pemakaian nyatanya (periksa opsi di skripnya, jangan menyalin dari ingatan). Langkah F.13 mengacu ke dokumen 08: tambahkan bahwa jawaban tahap 1 (SSH dan Portainer dari `10.1.101.0/24` dan `wt0`) harus dirender ulang untuk host baru karena subnet dan interface bisa berbeda.
2. `TASKS/PROGRESS.md`, `TASKS/BACKLOG.md`, `trader-document-catalog.md`, `MEMORY/MEMORY-INDEX.md`, `MEMORY/CHANGELOG.md`: catat jawaban firewall tahap 1, Tugas B sampai D, dan bahwa tahap 2 menunggu inventaris klien. Jangan menyatakan firewall diterapkan.
3. `CLAUDE.md`: ubah hanya bila fakta berubah (mis. baris "Remaining deployment risks" bila perlu); jangan menambah jebakan yang tidak kamu buktikan.

## 8. Tugas F (opsional, setelah A sampai E): tinjauan independen hanya-baca
Tinjau `deploy/trader/import_owner_profile.py`, `deploy/trader/aidss-anchor.sh`, dan skrip baru dari tugas B sampai D seperti penguji keamanan: jalur kebocoran password, token, atau URL database (argumen, log, pesan error, traceback); perilaku tidak aman secara default; apakah alat impor bisa menulis ke produksi tanpa gerbang `accepted` dan kata `APPLY`; kasus tepi (berkas profil rusak, respons server tak terduga, `Idempotency-Key` bertabrakan, ruang spasi di jalur `ENV_FILE`).
Laporkan temuan dengan berkas:baris dan skenario kegagalan konkret. Perbaiki hanya cacat yang jelas, dengan tes yang mereproduksinya.

## 9. Sebelum commit
`ruff check src tests alembic alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` (dengan Git Bash di depan PATH bila Tugas A belum membuatnya tak perlu; sebelum perubahanmu: 553 lulus, 15 dideselect).
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|dckr_pat_|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Setiap tugas menambah record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`, dan satu commit yang menyebut tugasnya.

## 10. Handoff (wajib, sembilan bagian lengkap)
`MEMORY/handoffs/2026-11-17-AA-anchor-tests-nft-validation-inventory-watch.md`, satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` diperbarui. Format (jangan lewati bagian mana pun):

```
Tanggal/jam, Agen, HEAD saat selesai (sha nyata), Status: SELESAI | DIBLOKIR
## 1. Ringkasan satu paragraf
## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti: [agen kedua] / [agen utama] / [pemilik]
## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, keluaran yang DIHARAPKAN)
## 5. DIVERIFIKASI vs DITULIS TAPI TIDAK DIJALANKAN
## 6. Temuan baru dan tindakannya
## 7. Keputusan yang menunggu pemilik (tulis sebagai pertanyaan pilihan ganda yang bisa saya ajukan)
## 8. Rollback: cara, diuji atau belum, waktu yang DIUKUR (perkiraan berlabel)
## 9. Risiko tersisa
```
Daftar commit yang belum di-push diambil dari `git log --oneline origin/main..HEAD`. Pertanyaan pilihan ganda yang diharapkan di bagian 7: ambang kesegaran anchor, kanal notifikasi (log saja, webhook, Telegram), dan frekuensi/retensi backup. Jika terblokir atau ragu apakah suatu aksi aman, berhenti dan tulis handoff; jangan memperluas lingkup.
