# Prompt v2 untuk agen sebelah: sisa pekerjaan AIDSS Trader (tahap 3)

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal prompt ini: `HEAD = origin/main = a85e831`.
Agen utama (Claude) **tidak mengimplementasi**; ia hanya memeriksa handoff-mu dan menjalankan perintah verifikasimu. Pemilik adalah
manusia yang memberi izin untuk aksi yang tak terbalik. Bahasa percakapan: Indonesia. Dokumen proyek: Inggris.

Tahap 2 sudah menghasilkan handoff yang baik (`MEMORY/handoffs/INDEX.md`). Tahap 3 memakai format yang sama dengan perbaikan
di bagian 6. Baca handoff A sampai E dan Z dulu supaya tidak mengulang pekerjaan.

---

## 0. Baca dulu, berurutan

1. `CLAUDE.md`, `AGENTS.md` (aturan non-negotiable dan jebakan).
2. `TASKS/PROGRESS.md`, `TASKS/BACKLOG.md`, `MEMORY/DECISIONS.md` (terutama ADR-013, 014, 021, 022, 029, 030, 036, 039, 040, 046 sampai 052).
3. `MEMORY/handoffs/INDEX.md` dan semua handoff di dalamnya. `MEMORY/records/2026-11-15-first-deploy.md`.
4. `docs/10-OPERATIONS/06-RUNBOOKS.md`, `MEMORY/records/2026-11-15-host-hardening-plan.md`, `deploy/trader/*`.

## 1. Keadaan sistem (fakta per a85e831; periksa ulang yang berubah)

- Trader (`src/aidss_trader`) terpisah dari platform analisis (`src/aidss`). Semua perilaku trading **hanya terverifikasi terhadap mock exchange**.
  **Tidak pernah ada panggilan ke Indodax asli.** T2-07 (cek live baca-saja, skrip `python -m aidss_trader live-check`) dan T5-06 (APPROVAL
  dengan modal nyata) adalah tugas **pemilik**. Jangan menjalankannya.
- VM `10.1.200.13`, user `infra`. **Kata sandi: minta ke pemilik; jangan tulis ke file, commit, log, atau argumen perintah.** (Kata sandi lama sudah terbuka
  di chat; ingatkan pemilik merotasinya.) Compose project `stocks` di `~/stocks` (milik root; `infra` ada di grup docker). **Dilarang membuat direktori baru.**
  Rahasia host: `~/.aidss-trader.env` (mode 0600), `~/.aidss-trader-master.key` (mode 0600).
- Berjalan di VM: `aidss-trader:e410ab7`, `aidss-frontend:e410ab7`, `aidss-api:e7b3da3` (API dan worker). Database di migrasi **0008**
  (30 tabel di schema `trading`). Trader **`HALTED`**, tanpa URL exchange dan tanpa kunci. Jangan mengubahnya.
- **Postgres di VM adalah PostgreSQL 16** (`pgvector/pgvector:pg16`), bukan 18. Port 5432 masih ter-publish ke `0.0.0.0` dan superuser `aidss`
  memakai password sama dengan username. Role `aidss_app` belum ada. Monitor liveness belum terpasang. Dump ada di `~/aidss-pre-*.sql.gz` (disk yang sama).
- Tes (acuan): `ruff check src tests alembic_trader deploy` bersih; `python -m pytest tests/trader tests/test_architecture_constraints.py -q` = 496 lulus,
  7 deselected, 1 xfail yang disengaja (S13). Frontend: `npx tsc -b --noEmit` bersih, `npx vitest run` = 51 lulus.
- Working tree berisi pekerjaan **landing page yang pemiliknya belum jelas**: `frontend/src/pages/Landing.tsx`, `frontend/src/index.css`,
  `frontend/public/landing/`, `frontend/src/pages/__tests__/`, kunci landing di `frontend/src/i18n/messages.ts`, dan pola `src/pages` di
  `frontend/vite.config.ts`, plus artefak `frontend/.vitest/`. **Jangan stage, ubah, atau hapus. Tanya pemilik siapa pemiliknya** dan tulis
  jawabannya di handoff. Tambahkan `frontend/.vitest/` ke `.gitignore` hanya setelah pemilik setuju.

## 2. Resep deploy yang terbukti (ikuti persis)

1. Tes dan ruff pada HEAD. Build **dari ekspor bersih**, bukan working tree: `git archive HEAD | tar -x -C <scratch>`;
   `docker build -f Dockerfile.trader -t zed378/aidss-trader:<sha> .` dan `docker build -t zed378/aidss-frontend:<sha> ./frontend`.
   Tag = sha commit pendek. **Tidak pernah `latest` untuk Trader.** Image API hanya dibuild ulang bila `src/aidss`, `Dockerfile`, `pyproject.toml`
   atau `alembic/` berubah (`git diff --stat <sha-lama> HEAD -- <path>`).
2. Push image dengan **PowerShell** (permintaan pemilik), repositori `zed378` (publik, ADR-030). Satu panggilan PowerShell per push; jangan digabung dengan
   panggilan lain dalam satu langkah.
3. **Latih migrasi di database sementara pada PostgreSQL 16 di VM** (`CREATE DATABASE <scratch>`, `GRANT CREATE ... TO trader_owner`, `REVOKE ALL ON SCHEMA public
   FROM trader_rw, trader_monitor`, migrasi, `pytest -m postgres tests/trader/test_privileges_postgres.py`, `DROP DATABASE ... WITH (FORCE)`).
   **Jangan menjalankan tes hak akses pada database `aidss` asli**: tes itu menambah baris ke audit log append-only yang tidak bisa dibersihkan.
   Kata sandi role dibaca dari `~/.aidss-trader.env` ke dalam proses, tidak pernah dicetak.
4. `pg_dump` baru (mode 0600, di home `infra`), lalu migrasi sebagai `trader_owner`:
   `docker run --rm --network stocks_default -e AIDSS_TRADER_MIGRATION_DATABASE_URL <image> alembic -c alembic_trader.ini upgrade head`.
5. Compose override lewat **stdin**: `cd ~/stocks && set -a && . ~/.aidss-trader.env && set +a && docker compose -f docker-compose.yml -f - up -d --no-build`
   (image tiap service; `trader` dengan `user: "1000:1000"`, secret `trader_master_key`, `expose: ["8001"]`, `read_only`, `tmpfs /tmp`).
6. Verifikasi: `docker ps`, log Trader, `select state from trading.trading_state` (harus `HALTED`), `select version_num from trading.alembic_version`,
   `curl -D - localhost:5173/trader/v1/status` (401 dengan header keamanan), `docker exec stocks-trader-1 python -m aidss_trader healthcheck` (exit 0).
7. Alat SSH: skrip paramiko dengan `HOST_PW` dari environment (jangan dari argumen), contoh ada di riwayat sesi sebelumnya.

## 3. Aturan keras

- Tidak ada kode penarikan dana; setiap order lewat Risk Engine; gagal = HALT; uang = `Decimal`; tidak ada data palsu.
- **Dilarang** mengirim permintaan bertanda tangan ke Indodax; menyimpan kunci Indodax/Telegram; mengisi URL exchange; me-resume, mempromosikan,
  FLATTEN, atau CANCEL di server; menyimpan angka limit, parameter, biaya paper, atau ambang promosi di produksi. Angka milik pemilik (OQ-5, 8, 9, 11, 12, 16)
  tidak pernah diberi nilai bawaan atau saran.
- Tidak ada secret literal di kode, dokumen, log, fixture, atau pesan commit. `tests/test_architecture_constraints.py` tidak boleh diedit.
  Trader tidak mengimpor `aidss` dan sebaliknya. Migrasi Alembic hanya aditif.
- **Aksi tak terbalik di VM** (tutup port, rotasi password, ganti role, pasang cron/systemd, hapus data) hanya setelah kamu menampilkan rencana, dampak, rollback
  yang sudah diuji, dan **pemilik menyetujui aksi itu secara eksplisit**. Persetujuan satu aksi tidak berlaku untuk aksi berikutnya.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan". Tidak ada klaim "berfungsi" tanpa bukti.

## 4. Tugas tahap 3 (urut; berhenti di gerbang, tulis handoff, lanjut ke tugas lain)

### F. Hardening host (gerbang pemilik per langkah). Lanjutan Tugas B.
Rencana, SQL, rollback, dan override sudah ada dan teruji di PG 18 lokal. Yang kurang adalah **bukti di PostgreSQL 16 dan eksekusi di VM**.
1. Ulangi latihan penuh (`bootstrap.sql`, `isolate_analysis_role.sql`, migrasi 0001-0008, tes `-m postgres` termasuk dua tes `aidss_app` dan `monitor`,
   lalu `rollback_analysis_role.sql`) pada **database sementara di PostgreSQL 16 VM**. Catat apakah hasil sama dengan PG 18; selisih = temuan.
2. Pra-cek konsumen port 5432 (`pg_stat_activity` dengan `client_addr` bukan null; `ss -tnp 'sport = :5432'`). Pastikan versi Compose di host mendukung
   `ports: !reset []` (`docker compose version`); jika tidak, jelaskan alternatifnya.
3. **Gerbang:** tampilkan hasil langkah 1 dan 2, rencana eksekusi, dan rollback; tunggu persetujuan pemilik. Lalu: `pg_dumpall` baru (mode 0600), role `aidss_app`,
   rotasi password superuser `aidss`, `AIDSS_APP_DATABASE_URL` di `~/.aidss-trader.env`, tutup port 5432, `up -d --no-build`.
4. Verifikasi: API analisis sehat dan login berhasil, worker tanpa galat hak akses, Trader `HALTED` dan lease terpegang, `aidss_app` tidak bisa membaca schema `trading`,
   port 5432 tidak terjangkau dari mesin lain (`nc` atau uji dari luar), kontainer lain di host tidak terpengaruh. **Ukur** waktu pemulihan rollback; jangan menulis perkiraan.
5. Ingatkan pemilik: rotasi kata sandi SSH `infra`; salin dump keluar host (ADR-040); satu-satunya salinan kunci master ada di host.

### G. Monitor liveness dan latihan restore di VM (gerbang pemilik)
1. `deploy/trader/check_liveness.py` dan `rehearse_restore.sh` sudah ada dan teruji dengan penerima palsu. Jalankan `rehearse_restore.sh` **hanya pada database sementara di VM**
   dengan **dump penuh** (bukan hanya skema `trading`); catat waktu nyata dan jumlah baris.
2. Siapkan perintah pemasangan monitor (cron atau systemd timer) dan file token Telegram root-only **tanpa memasangnya**. **Gerbang:** pemasangan hanya setelah pemilik menyetujui dan
   menyediakan token di terminalnya sendiri; token tidak pernah lewat chat atau repo.

### H. Pemangkasan `idempotency_key` (ADR-051)
Tabel hanya bertambah. Rancang pemangkasan baris > 24 jam: pilih mekanisme paling sederhana yang aman (misalnya penghapusan oportunistik di dalam transaksi tulis API, atau
satu fungsi yang dipanggil dari siklus housekeeping), mengingat `trader_rw` punya `DELETE` hanya pada tabel itu. Aditif, ada tes (kedaluwarsa, baris baru tidak terhapus, kegagalan
pemangkasan tidak menggagalkan permintaan), tidak mengubah semantik replay. Catat di ADR-051 sebagai implementasi dan perbarui handoff.

### I. Verifikasi UI di browser nyata (menggantikan Tugas C yang terblokir)
Chrome lokal gagal (`DevToolsActivePort`). Pakai **Chromium bawaan Playwright**: `npx playwright install chromium`, dijalankan dari scratch di luar repo atau sebagai devDependency
yang tidak mengubah build produksi. Target: https://aidss.zedth.my.id dengan **akun uji `trader`/`admin` dari pemilik** (jangan mendaftarkan akun di produksi tanpa izin).
Aman: membaca, membuka dialog lalu **Batal**. **Jangan** menyimpan kredensial, me-resume, mempromosikan, FLATTEN/CANCEL, atau menyimpan limit/parameter/paper/ambang.
Step-up meminta password pemilik; jangan dimasukkan sendiri. Periksa dan simpan buktinya **di luar repo**: ketujuh layar Trader, sidebar yang bisa dilipat (grup dan seluruh sidebar),
label PAPER, ID/EN, fokus keyboard, kontras, lebar 375/768/1280 px, scroll horizontal, galat konsol, jaringan (tanpa rahasia, header keamanan ada), serta tampilan saat Trader tidak
menjawab (blokir request dengan fitur route Playwright, jangan mematikan kontainer). Perbaiki cacat di file Trader dan tambahkan tes Vitest untuk tiap perbaikan.
Jika Playwright juga tidak bisa dijalankan, tulis penyebabnya dan berhenti; jangan memalsukan bukti.

### J. Sinkronisasi dokumen dan sisa kecil
- Setelah F sampai I, perbarui `TASKS/PROGRESS.md`, `CLAUDE.md`, `TASKS/BACKLOG.md` dan `MEMORY/MEMORY-INDEX.md` sesuai bukti; jangan menaikkan status melebihi bukti.
- ADR yang menunggu keputusan pemilik (049 sampai 052, ditambah 046 dan 047) tidak diimplementasi sebelum pemilik memilih. Kumpulkan pertanyaannya di handoff akhir dengan pilihan dan rekomendasi.

---

## 5. Aturan kerja bersama (semua pernah salah)

- Stage file **per nama**; **jangan `git add -A`**; baca `git status` sebelum commit. **Jangan `ruff format` pada direktori** (pernah dua kali memformat 78 file `src/aidss`).
  Kalau terjadi: `git checkout -- src/aidss` sebelum commit.
- Satu commit per tugas, pesan commit menyebut apa yang **tidak** terverifikasi. **Jangan push ke GitHub**; pemilik atau agen utama yang mendorong saat diminta.
  Setiap commit memperbarui `TASKS/PROGRESS.md`, menulis record di `MEMORY/records/`, dan menambah satu baris di `MEMORY/MEMORY-INDEX.md`.
- Sebelum commit: `ruff check src tests alembic_trader deploy`, `python -m pytest tests/trader tests/test_architecture_constraints.py -q`, dan di `frontend/`:
  `npx tsc -b --noEmit`, `npm run lint`, `npx vitest run`, `npm run build`. Satu kegagalan lama di luar Trader: `tests/test_output_language.py::test_translation_covers_every_prose_field`.
- Skill antislop untuk UI/copy, mode global `during`. Umumkan sekali: `antislop active: during (global preference).`
- Tipe API Trader: `python -m aidss_trader.api.openapi frontend/.trader-openapi.json`, lalu di `frontend/` `npx openapi-typescript .trader-openapi.json -o src/api/trader-schema.d.ts`, hapus JSON-nya.
- Windows: peringatan CRLF diabaikan. Hati-hati path Windows di heredoc (`\r` menjadi carriage return; jaga `\\`).
- **Pemindaian secret sebelum setiap commit** pada diff-nya: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong; pastikan perintahnya sendiri tidak error.

## 6. HANDOFF (wajib; diperiksa agen utama)

Per tugas (F sampai J) atau saat berhenti di gerbang: `MEMORY/handoffs/2026-11-15-<huruf>-<topik>.md` (atau tanggal hari itu) dan satu baris di `MEMORY/handoffs/INDEX.md`, commit per nama file.
Format tahap 2 tetap, dengan **tambahan wajib** ini:

```
Tanggal/jam, Agen, HEAD saat selesai, Status: SELESAI | BERHENTI DI GERBANG | DIBLOKIR
## 1. Ringkasan satu paragraf
## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti:
   [agen kedua] / [agen utama] / [pemilik]. Aksi di VM yang dilakukan orang lain tidak boleh tampak sebagai hasilmu.
## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, dengan keluaran yang DIHARAPKAN)
## 5. DIVERIFIKASI (rujuk bukti) vs DITULIS TAPI TIDAK DIJALANKAN
## 6. Temuan baru dan tindakannya
   Wajib dicantumkan: setiap selisih antara lingkungan latihan dan produksi (versi PostgreSQL, ukuran data, perangkat).
## 7. Keputusan yang menunggu pemilik (pertanyaan, pilihan, rekomendasi)
## 8. Rollback: cara, sudah DIUJI atau belum, dan waktu pemulihan YANG DIUKUR. Perkiraan harus berlabel "perkiraan".
## 9. Risiko tersisa
```
Aturan: tidak ada "seharusnya berfungsi". Daftar commit yang belum di-push **diambil dari `git log --oneline origin/main..HEAD`**, bukan dari ingatan.
Di akhir semua pekerjaan tulis `…-Z-final.md`: commit belum di-push, keadaan akhir VM (`docker ps`, versi migrasi, state Trader), dan 5 risiko teratas untuk pemilik.

## 7. Urutan dan batas
F langkah 1-2 dan I (read-only) bisa jalan lebih dulu; H paling mandiri; G dan F eksekusi menunggu persetujuan. Jika terblokir persetujuan, tulis handoff dan lanjut ke tugas lain.
Jangan memperluas lingkup: mengisi angka pemilik, menghubungi Indodax, atau mengubah desain strategi tidak diminta. Bila ragu apakah suatu aksi aman, tanyakan ke pemilik.
