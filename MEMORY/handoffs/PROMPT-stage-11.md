# Prompt tahap 11 untuk agen sebelah: backup luar-host terenkripsi, rencana firewall host, dan perapian CLAUDE.md

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = b1612ef` (dua commit terakhir, `a247720` dan `b1612ef`, belum di-push; `origin/main` ada di `f883426`).
Agen utama (Claude) tidak mengimplementasi tugas-tugas ini; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Tiga tugas utama (V, W, X) dan satu opsional (Y). **Kamu tidak punya akses SSH ke VM, tidak membangun atau mendorong image, tidak men-deploy, dan tidak menyentuh produksi.** Semua yang menyentuh host dikerjakan agen utama atau pemilik.

## 0. Baca dulu
`CLAUDE.md` (tabel Traps, terutama baris `--no-deps`), `AGENTS.md`, `MEMORY/handoffs/INDEX.md` dan handoff terakhir, `MEMORY/records/2026-11-16-host-backup-pg-dumpall.md` (langkah 1 sampai 6),
`MEMORY/records/2026-11-17-host-port-inventory.md`, `docs/10-OPERATIONS/04-BACKUP-RESTORE-AND-RECOVERY.md`, `docs/10-OPERATIONS/06-RUNBOOKS.md` (R9, R10, R13, R15), `deploy/trader/aidss-anchor.sh`, `tests/trader/test_aidss_anchor_script.py`.
Untuk Tugas Y baca juga `deploy/trader/import_owner_profile.py` dan `tests/trader/test_import_owner_profile.py`.

## 1. Keadaan (fakta)
- Produksi `https://aidss.zedth.my.id` berjalan di VM `10.1.200.13` (pengguna `infra`, Ubuntu 26.04): `aidss-api:latest` dan `aidss-frontend:latest` (= `603e606`), `aidss-trader:7d03693`, PostgreSQL 16.16. Trader `HALTED`, tidak pernah menyentuh exchange.
- Hardening host sudah dilakukan (langkah 1 sampai 6 di record): api dan worker memakai role `aidss_app`, password superuser dirotasi, 5432 dan 7153 tidak dipublikasikan, 5173 diikat ke `127.0.0.1`, `docker-compose.yml` di host dikeraskan, `~/stocks/.env` jadi `infra:infra 600`.
  Yang masih terbuka: host **tanpa firewall**, backup **satu host** dengan database, dan belum ada salinan di luar host.
- Backup yang ada: `~/aidss-backups/pg_dumpall-20261116T100117Z.sql.gz` di VM, dibuat dengan `docker exec stocks-postgres-1 pg_dumpall -U aidss --quote-all-identifiers | gzip -6`. Di dalam kontainer, socket lokal dan `127.0.0.1` memakai `trust`, jadi perintah itu tidak butuh password.
- Keputusan pemilik hari ini (2026-11-17): (a) firewall: **susun rencana dulu, jangan diterapkan**; (b) backup luar-host: **salin ke komputer pemilik, terenkripsi, dengan passphrase pemilik**; (c) ADR-052 ditunda; (d) `audit-anchor` dipasang di host oleh agen utama (bukan tugasmu).
- Pemilik mengerjakan di Windows (Git Bash) dan menyimpan `HOST_PW`/password SSH sendiri. Komputer pemilik `10.1.101.50` berada di subnet berbeda dari VM (`10.1.200.0/24`).

## 2. Aturan keras
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit; tidak ada passphrase atau password di argumen, variabel lingkungan, berkas, atau keluaran. Tidak ada panggilan ke Indodax atau layanan eksternal apa pun. Artefak uji ke direktori sementara, bukan repo.
- Jangan edit `tests/test_architecture_constraints.py`, `docker-compose.yml`, `Dockerfile*`, `alembic*`, `src/`. Jangan push. Stage per nama berkas (jangan `git add -A`). Jangan `ruff format` pada direktori; satu berkas boleh.
- Berkas `*.sh` dan `*.cron` harus LF (ada `.gitattributes`); periksa dengan `file` atau `od -c` bahwa tidak ada CR.
- Kita memakai working tree yang sama: periksa `git status` dulu, jangan menjalankan tes saat agen utama sedang mengubah berkas.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan". Skrip yang mengubah firewall atau menyentuh host **tidak boleh dijalankan**; cukup dicek sintaksnya (`sh -n`) dan diuji dengan stub.
- Gaya tulisan: aturan antislop berlaku (tanpa em dash, tanpa angka karangan, komentar menjelaskan alasan).

## 3. Tugas V: skrip backup luar-host terenkripsi (dijalankan pemilik)
Berkas: `deploy/trader/backup_offhost.sh`, `tests/trader/test_backup_offhost.py`, bagian baru "Off-host encrypted copy" di runbook R9 (`docs/10-OPERATIONS/06-RUNBOOKS.md`) dan satu baris di `docs/10-OPERATIONS/04-BACKUP-RESTORE-AND-RECOVERY.md`.
Pemilik menjalankannya sendiri dari Git Bash: `bash deploy/trader/backup_offhost.sh [--dest DIR] [--host infra@10.1.200.13]`.
Persyaratan:
1. **Alirkan, jangan simpan polos.** Perintah dump di host dijalankan lewat `ssh` (string perintah tetap, tanpa masukan pengguna di dalamnya): `docker exec stocks-postgres-1 pg_dumpall -U aidss --quote-all-identifiers | gzip -6`, lalu dialirkan lokal ke
   `openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt`. Plaintext tidak pernah ditulis ke disk lokal maupun ke host. Catatan: di PowerShell pipa merusak data biner, jadi skrip ini hanya untuk bash; tulis begitu di bantuan skrip.
2. **Passphrase:** diminta dua kali dengan `read -s` (tanpa echo), tidak pernah di argumen, lingkungan, berkas, atau log; diberikan ke openssl lewat file descriptor (`-pass fd:N`). Sediakan `--passphrase-fd N` agar tes bisa memberi passphrase tanpa terminal. Kalau dua isian tidak sama, berhenti.
3. **Keluaran:** `aidss-pg_dumpall-<UTC>.sql.gz.enc` dan `.sha256` di `--dest` (default folder yang dibuat dengan `umask 077`), menolak menimpa berkas yang ada, mode 600.
4. **Verifikasi sendiri:** setelah menulis, dekripsi balik ke aliran (tanpa menyimpan) dan periksa `gzip -t`, adanya penutup `PostgreSQL database cluster dump complete`, minimal satu `CREATE ROLE`, ukuran masuk akal. Cetak hanya jumlah (blok `COPY`, role), tidak ada isi data. Bila gagal: hapus keluaran, kode keluar bukan nol, dan jangan mencetak passphrase.
5. **Gagal di tengah** (ssh putus, dump terpotong): keluaran parsial dihapus.
6. **Pemulihan:** cetak perintah restore (`openssl enc -d ... | gunzip | docker exec -i ... psql`) tetapi jangan menjalankannya; dokumentasikan di runbook langkah latihan restore ke PostgreSQL sementara, mengacu ke `deploy/trader/rehearse_restore.sh`.
7. Sediakan `--source-cmd "<perintah>"` sebagai kait tes (menggantikan `ssh ...`), dan tulis di bantuan bahwa itu hanya untuk uji.
Tes (lewati bila tidak ada `bash` atau `openssl`): dump palsu dari `printf` + `gzip` lewat `--source-cmd`; hasil `.enc` tidak mengandung teks `CREATE ROLE` mentah; dekripsi balik sama dengan sumber; passphrase salah gagal; menolak menimpa; sumber terpotong (tanpa penutup) menghapus keluaran dan gagal;
sidecar `.sha256` cocok; passphrase tidak muncul di stdout, stderr, atau berkas mana pun; mode 600 (lewati di Windows). **Jangan jalankan terhadap host.**

## 4. Tugas W: rencana firewall host (hanya rencana)
Berkas: `docs/10-OPERATIONS/08-HOST-FIREWALL-PLAN.md`, draf aturan `deploy/host/firewall/docker-user.nft` (draf, **tidak diterapkan**), dan `deploy/host/firewall/apply-with-rollback.sh` (draf), tes sintaks (`sh -n`) di `tests/trader/test_host_firewall_drafts.py`.
Masukan: `MEMORY/records/2026-11-17-host-port-inventory.md` (satu-satunya sumber fakta tentang host; jangan menebak port atau proyek). Isi dokumen:
1. **Pendekatan dan alasannya:** port yang dipublikasikan Docker melewati `ufw`, jadi aturan harus di rantai `DOCKER-USER` (atau nftables yang setara); `ufw` saja tidak cukup. Jelaskan opsi (nftables langsung vs `ufw` + `DOCKER-USER`), pilih satu dengan alasan, termasuk persistensi setelah reboot dan paritas IPv6.
2. **Tabel per port** dari inventaris: proyek pemilik, usulan (biarkan, batasi ke subnet LAN, batasi ke `wt0`/netbird, atau tutup), dan kolom "butuh konfirmasi pemilik". **Proyek lain (portainer, hexstrike, wedding-staging, central-dashboard, callibrator, stirling-pdf, bentopdf, libreoffice, java 6547)
   tidak boleh ditutup tanpa konfirmasi pemilik**: tulis usulan sebagai pertanyaan dengan pilihan ganda yang bisa saya ajukan, bukan sebagai keputusan. Port AIDSS sudah tertutup; dokumentasikan bahwa aturan baru tidak boleh mengubahnya.
3. **Pengaman anti-terkunci:** SSH (22) hanya dari sumber yang disebut eksplisit (komputer pemilik `10.1.101.50` dan/atau subnetnya, dan `wt0`); aturan diterapkan dengan pemulih otomatis (mis. `systemd-run --on-active=5m` atau `at` yang membalikkan aturan kecuali dibatalkan) dan sesi SSH kedua tetap terbuka; urutan uji (SSH kedua, situs publik, tiap proyek yang dikonfirmasi).
4. **Saran terpisah dan opsional untuk SSH:** `PasswordAuthentication yes` dan `PermitRootLogin yes` aktif sekarang; tulis dampaknya pada prosedur deploy (`HOST_PW`) dan langkah aman bila pemilik ingin mengubahnya. Jangan menyatakan itu bagian dari firewall.
5. **Verifikasi hanya-baca** untuk agen utama (perintah `nft list`, `iptables -S DOCKER-USER`, `ss -ltn`, curl dari komputer pemilik) dan apa yang dianggap "selesai"; rollback; apa yang **tidak diketahui** (mis. proses `java` di 6547, pengguna LAN lain, trafik antar proyek lewat bridge).
6. Draf `docker-user.nft` hanya berisi aturan yang bisa kamu jelaskan satu per satu; semua alamat sumber berupa placeholder yang diberi komentar "isi dari jawaban pemilik", bukan tebakan. Beri label tegas "DRAFT, NOT APPLIED" di kepala berkas. Bila `nft` tersedia secara lokal gunakan `nft -c -f` untuk cek sintaks; bila tidak, tulis "tidak divalidasi".

## 5. Tugas X: perapian `CLAUDE.md` (dan `TASKS/PROGRESS.md` bila bertentangan)
`CLAUDE.md` memuat beberapa baris yang sudah usang setelah hardening dan deploy 2026-11-16 dan 2026-11-17. Periksa **tiap klaim terhadap repo dan record** sebelum menulis (jangan mengira-ngira): baris "Verified on 2026-11-15 ... `aidss-frontend:f08e3af`",
kalimat "Open risks of the deployment" (masih menyebut compose di server membangun dari source, padahal sudah memakai image; ada tanda kurung rusak), jumlah tes (Trader, arsitektur, routing; Vitest 100), dan versi image di kalimat "deployed `HALTED`". Jebakan `--no-deps` dari insiden 2026-11-17 sudah ada; jangan ditulis ulang.
Tambahkan hanya yang benar dan perlu agen berikutnya tahu: `audit-anchor` (ADR-054) dan wrapper-nya, alat impor profil dan profil starter (ADR-055, status `proposed`), `.gitattributes` untuk LF. Jangan menulis bahwa Trader bisa trading. Jangan menambah jebakan yang tidak kamu buktikan dari record.
Jalankan `python -m pytest tests/test_frontend_routing.py tests/test_architecture_constraints.py -q` sebagai bukti tidak ada yang rusak.

## 6. Tugas Y (opsional, hanya bila V, W, X selesai): tinjauan independen, hanya baca
Tinjau `deploy/trader/import_owner_profile.py` dan `deploy/trader/aidss-anchor.sh` seperti penguji keamanan: apakah ada jalur kebocoran password, token, atau URL database (argumen, log, pesan error, traceback); apakah ada perilaku tidak aman secara default;
apakah alat impor bisa tanpa sengaja menulis ke produksi (default dry-run, gerbang `accepted`, kata `APPLY`); kasus tepi (berkas profil rusak, respons server tak terduga, `Idempotency-Key` bertabrakan). Laporkan temuan dengan berkas:baris dan skenario kegagalan konkret.
Perbaiki hanya cacat yang jelas, dengan tes yang mereproduksinya; selain itu cukup dilaporkan.

## 7. Sebelum commit
`ruff check src tests alembic alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` (sebelum perubahanmu: 525 lulus + tes baru dari agen utama); bila menyentuh frontend (tidak diharapkan): `./node_modules/.bin/tsc -b --noEmit`, `npx oxlint .`, `npx vitest run --pool=vmThreads`.
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|dckr_pat_|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Setiap tugas menambah record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`, dan satu commit dengan pesan yang menyebut tugasnya.

## 8. Handoff (wajib, sembilan bagian lengkap)
`MEMORY/handoffs/2026-11-17-V-W-X-offhost-backup-firewall-plan.md`, satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` diperbarui. Format (jangan lewati bagian mana pun):

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
Daftar commit yang belum di-push diambil dari `git log --oneline origin/main..HEAD`. Jika terblokir atau ragu apakah suatu aksi aman, berhenti dan tulis handoff; jangan memperluas lingkup.
