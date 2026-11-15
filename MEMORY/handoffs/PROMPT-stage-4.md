# Prompt tahap 4 untuk agen sebelah: pekerjaan yang masih bisa dikerjakan tanpa akses VM

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = e533782` (lokal, belum di-push), `origin/main = 2bafc97`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Pemilik adalah manusia yang
memberi izin untuk aksi tak terbalik. Percakapan: Indonesia. Dokumen proyek: Inggris.

**Kamu tidak punya kata sandi SSH ke VM dan tidak boleh memintanya lewat chat atau menyimpannya.** Karena itu tahap ini hanya berisi pekerjaan
lokal dan pekerjaan read-only terhadap `https://aidss.zedth.my.id`. Semua yang mengubah VM tetap ditahan (bagian 5).

## 0. Baca dulu, berurutan
1. `CLAUDE.md`, `AGENTS.md`. 2. `TASKS/PROGRESS.md`, `TASKS/BACKLOG.md`. 3. `MEMORY/handoffs/INDEX.md`, handoff F, G, I, J, Z-final.
4. `MEMORY/records/2026-11-15-pg16-host-hardening-rehearsal.md` dan `2026-11-15-first-deploy.md` (bagian redeploy `75bc905`).
5. `deploy/trader/*`, `frontend/nginx.conf`, `tests/test_frontend_routing.py`.

## 1. Keadaan sistem (fakta, per HEAD `e533782`; periksa yang berubah)
- VM `10.1.200.13` menjalankan: `aidss-frontend:75bc905`, `aidss-trader:e410ab7`, `aidss-api:e7b3da3`. Trader `HALTED`, tanpa URL exchange, tanpa kunci.
  Database di migrasi 0008. Tidak pernah ada panggilan ke Indodax asli.
- **Koreksi penting dari tahap 3:** bug `404` pada `/trader/*` (handoff I) **bukan** reverse proxy VM. Penyebabnya `location /trader/` di
  `frontend/nginx.conf`; sudah diperbaiki di `75bc905` (`location /trader/v1/`), di-deploy, dan dijaga `tests/test_frontend_routing.py`.
  Dengan `curl`, `/trader`, `/trader/approvals`, `/trader/limits` kini 200 `text/html`; `/trader/v1/status` tetap 401 JSON. **Belum diverifikasi di browser.**
- Latihan hardening di PostgreSQL 16 VM sudah dijalankan agen utama pada klon `aidss`: isolate 1,1 s, rollback 1,2 s (sisi database), 6/6 tes hak akses, cluster
  kembali seperti semula. Langkah produksi belum jalan.
- Commit `b4169b9` (landing page, dari pemilik) sudah di `origin/main`. Pada HEAD ini: `tsc` bersih, `oxlint` exit 0, Vitest 51 lulus, build berhasil
  (peringatan chunk 699 kB). Python: `ruff check src tests alembic_trader deploy` bersih; `pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py` = 505 lulus, 7 deselected, 1 xfail yang disengaja (S13).
- Kegagalan lama di luar Trader: `tests/test_output_language.py::test_translation_covers_every_prose_field`.

## 2. Aturan keras
- Tidak ada kode penarikan dana; setiap order lewat Risk Engine; gagal = HALT; uang = `Decimal`; tidak ada data palsu.
- **Dilarang:** permintaan bertanda tangan ke Indodax; menyimpan kunci Indodax/Telegram; mengisi URL exchange; resume, promote, FLATTEN, CANCEL; menyimpan limit, parameter,
  biaya paper, atau ambang promosi di produksi. Angka milik pemilik (OQ-5, 8, 9, 11, 12, 16) tidak pernah diberi nilai bawaan atau saran.
- Tidak ada secret literal di kode, dokumen, log, fixture, atau pesan commit. `tests/test_architecture_constraints.py` tidak boleh diedit. Migrasi hanya aditif.
- **Tidak ada koneksi SSH ke VM, tidak ada perubahan di VM, tidak ada build/push image, tidak ada deploy.** Itu dikerjakan agen utama bila pemilik meminta.
- Pekerjaan browser terhadap produksi hanya baca. Akun uji dari pemilik (sebelumnya `test@mail.com`, role admin); jangan mendaftarkan akun baru. Buka dialog lalu **Batal**;
  jangan simpan apa pun; step-up meminta kata sandi pemilik, jangan diisi.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan". Tidak ada klaim "berfungsi" tanpa keluaran nyata.

## 3. Tugas (urut; tiap tugas satu commit dan satu handoff)

### K. Verifikasi browser ulang setelah perbaikan nginx dan setelah landing page (read-only)
Pakai Playwright Chromium (sudah ada di `%TEMP%\aidss-pw-verify`, atau pasang ulang di luar repo). Target `https://aidss.zedth.my.id`. Periksa dan simpan bukti **di luar repo**:
1. **Akses langsung / refresh** (`page.goto`, lalu `reload`) untuk ketujuh rute `/trader`, `/trader/approvals`, `/trader/strategies`, `/trader/parameters`, `/trader/paper`,
   `/trader/credentials`, `/trader/limits`: status 200, `text/html`, `<h1>` tampil, tidak ada redirect ke `http://`, 0 galat konsol/halaman.
2. **Sidebar yang bisa dilipat** dengan selektor yang benar (tombol grup memakai `aria-expanded`/`aria-controls`; tombol seluruh sidebar berlabel "Hide menu" / "Sembunyikan menu"). Uji lipat/buka grup,
   sembunyikan/tampilkan sidebar, auto-expand grup rute aktif, dan bahwa keadaan bertahan setelah reload (`localStorage` kunci `aidss.nav.collapsed`, `aidss.nav.sidebar`).
3. **Landing page** (`/`, tanpa login): ID/EN, lebar 375/768/1280 tanpa scroll horizontal, gambar termuat (`/landing/*.jpg`), fokus keyboard terlihat, 0 galat konsol/jaringan, kontras teks utama.
4. Ulangi pemeriksaan tahap 3 yang relevan: 7 layar menampilkan `HALTED` dan `PAPER`, header keamanan pada `/trader/v1/status` (401), simulasi outage `502` lewat route Playwright (jangan matikan kontainer).
Perbaiki cacat **hanya** di file frontend yang memang bagian Trader/sidebar, dan tambahkan tes Vitest untuk tiap perbaikan. **Jangan ubah `Landing.tsx`, `index.css`, `public/landing/`**
tanpa menanyakan pemilik; catat cacat landing sebagai temuan. Jika ada perbaikan, jangan deploy; tulis di handoff bahwa butuh build dan deploy oleh agen utama.

### L. Skrip latihan hardening yang bisa diulang (lokal)
Agen utama memakai skrip sekali pakai di luar repo. Jadikan itu alat yang sah di repo, tanpa kata sandi di dalamnya:
1. Tambah `deploy/trader/rehearse_isolation.sh` (jalan **di VM** oleh pemilik atau agen utama, memakai `docker exec` seperti `rehearse_restore.sh`): klon `aidss` ke database sementara lewat
   `pg_dump | psql`, terapkan `isolate_analysis_role.sql`, periksa kepemilikan dan atribut role, uji penolakan akses `aidss_app` ke schema `trading` dengan SQL (`SET ROLE` bila perlu), ukur waktu rollback,
   hapus database sementara **dan role `aidss_app`** di `trap` (role itu satu cluster; jangan tinggalkan). Sandi sementara dibuat acak dan dikirim lewat stdin, tidak lewat argumen.
2. Jalankan dua kali pada **PostgreSQL 18 lokal**: sekali sukses, sekali dengan kegagalan yang disengaja di tengah (pastikan `trap` tetap membersihkan database dan role).
3. Perluas `deploy/trader/rehearse_restore.sh` dengan opsi `--full` (dump penuh seluruh database, bukan hanya `-n trading`), karena handoff G meminta dump penuh tetapi skrip hanya men-dump schema `trading`.
   Tetap kompatibel tanpa opsi. Catat waktu dan jumlah baris. Jalankan lokal pada PG 18; **jangan** menjalankannya di VM.
4. Tambah tes statis pada Python (tanpa Docker) yang memastikan skrip tidak memuat kata sandi literal dan memakai `trap` pembersihan, mengikuti gaya `tests/trader/test_security_s1_s17.py` (S17).
5. Perbarui `docs/10-OPERATIONS/06-RUNBOOKS.md` (R10/R13) agar menunjuk ke skrip baru. Jangan mengubah `isolate_analysis_role.sql` atau `rollback_analysis_role.sql` kecuali ada cacat yang terbukti; bila ada, jelaskan buktinya.

### M. Sinkronisasi dokumen dan sisa kecil
- `TASKS/PROGRESS.md`: tambahkan baris redeploy `75bc905` (hanya frontend), perbarui angka tes dengan keluaran nyata (Python 505, Vitest 51) dan catat bahwa `CLAUDE.md` masih menyebut 496.
  Perbarui `CLAUDE.md` bagian "Trader" dan "What Is Currently Failing" sesuai bukti, tanpa menaikkan status melebihi bukti.
- `MEMORY/handoffs/INDEX.md`: baris I masih menulis "bug routing reverse proxy"; koreksi menjadi `frontend/nginx.conf` (sudah diperbaiki di `75bc905`). Isi field "HEAD saat selesai" yang masih "(akan diisi setelah commit)" di handoff I dan J dengan sha sebenarnya.
- Peringatan build: chunk 699 kB. **Bila** tugas K selesai tanpa sisa cacat, pertimbangkan `React.lazy` pada halaman Trader (satu perubahan kecil, dengan tes Vitest yang memastikan tiap rute masih termuat). Jangan memecah kode lain.
- Pertanyaan yang tetap milik pemilik (kumpulkan di handoff akhir dengan pilihan dan rekomendasi, jangan diimplementasi): ADR-046, 047, 049, 050 (S13: lock file), 051, 052, dan angka OQ-5, 8, 9, 11, 12, 16.

## 4. Aturan kerja bersama (semua pernah salah)
- Stage file **per nama**; jangan `git add -A`; baca `git status` sebelum commit. **Jangan `ruff format` pada direktori** (dua kali memformat 78 file `src/aidss`; bila terjadi: `git checkout -- src/aidss`).
- **Jangan push.** Pemilik atau agen utama yang mendorong. Daftar commit belum-di-push diambil dari `git log --oneline origin/main..HEAD`, bukan dari ingatan.
- Sebelum commit: `ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: `npx tsc -b --noEmit`, `npx oxlint .`, `npx vitest run`, `npm run build`.
  (Pembungkus `npm run lint` mencetak "ESLint output (JSON parse failed)"; itu bukan galat kode, jalankan `npx oxlint .` langsung.)
- Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong; pastikan perintahnya sendiri tidak error.
- Setiap commit: record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`, pembaruan `TASKS/PROGRESS.md`. Antislop mode `during (global preference)`; umumkan sekali.
- Windows: peringatan CRLF diabaikan; hati-hati path di heredoc.
- Jangan membuat file scratch di dalam repo; artefak uji ke `%TEMP%`. `frontend/.vitest/` sudah di `.gitignore`.

## 5. Ditahan, bukan untukmu (jangan dikerjakan, jangan dicoba)
- Eksekusi hardening produksi (`pg_dumpall`, buat `aidss_app`, rotasi sandi `aidss`, override URL di compose, tutup port 5432): butuh persetujuan pemilik per langkah dan akses SSH.
- Pemasangan monitor liveness (cron/systemd) dan token Telegram: pemilik yang mengisi token di terminalnya sendiri.
- Latihan restore dump penuh di VM; build/push image; deploy; T2-07 (cek live baca-saja) dan T5-06 (APPROVAL bermodal nyata): tugas pemilik.
- Rotasi kata sandi SSH `infra`: tugas pemilik.

## 6. HANDOFF (wajib; diperiksa agen utama)
Satu file per tugas (K, L, M): `MEMORY/handoffs/2026-11-15-<huruf>-<topik>.md` (atau tanggal hari itu) dan satu baris di `MEMORY/handoffs/INDEX.md`; commit per nama file. Format:

```
Tanggal/jam, Agen, HEAD saat selesai (sha nyata), Status: SELESAI | BERHENTI DI GERBANG | DIBLOKIR
## 1. Ringkasan satu paragraf
## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti: [agen kedua] / [agen utama] / [pemilik]
## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, dengan keluaran yang DIHARAPKAN)
## 5. DIVERIFIKASI (rujuk bukti) vs DITULIS TAPI TIDAK DIJALANKAN
## 6. Temuan baru dan tindakannya (wajib: setiap selisih lingkungan latihan vs produksi: versi PostgreSQL, ukuran data, perangkat)
## 7. Keputusan yang menunggu pemilik (pertanyaan, pilihan, rekomendasi)
## 8. Rollback: cara, sudah DIUJI atau belum, waktu pemulihan YANG DIUKUR (perkiraan harus berlabel "perkiraan")
## 9. Risiko tersisa
```
Di akhir tulis `…-Z-final.md`: commit yang belum di-push, perubahan yang butuh build/deploy oleh agen utama (bila ada), dan 5 risiko teratas untuk pemilik.
Bila sebuah tugas terblokir atau ragu apakah suatu aksi aman, berhenti, tulis handoff, dan lanjut ke tugas lain; jangan memperluas lingkup.
