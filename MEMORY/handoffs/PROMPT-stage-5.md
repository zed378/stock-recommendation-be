# Prompt tahap 5 untuk agen sebelah: verifikasi lazy loading rute Trader di produksi

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = origin/main = 074b254`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Satu tugas saja (N), read-only terhadap produksi. Tidak ada akses SSH, build, push image, atau deploy untukmu.

## 0. Baca dulu
`CLAUDE.md`, `AGENTS.md`, `MEMORY/handoffs/INDEX.md`, handoff K dan M, `MEMORY/records/2026-11-15-first-deploy.md` (bagian redeploy `ab5a9ab`),
`frontend/src/App.tsx`, `frontend/src/pages/__tests__/TraderLazyRoutes.test.tsx`.

## 1. Keadaan (fakta)
- Produksi `https://aidss.zedth.my.id` menjalankan `aidss-frontend:ab5a9ab`: ketujuh halaman Trader dimuat lazy (`React.lazy` + `<Suspense>`), chunk
  `Trader-*.js`, `TraderApprovals-*.js`, `TraderCredentials-*.js`, `TraderLimits-*.js`, `TraderPaper-*.js`, `TraderParameters-*.js`, `TraderStrategies-*.js` di `/static/`.
  Chunk utama `index-SOTAvzij.js` (635 kB). Dengan `curl`: semua chunk 200 `application/javascript`, rute `/trader*` 200 `text/html`. **Belum diverifikasi di browser.**
- Trader `HALTED`, tanpa URL exchange. Tidak pernah ada panggilan ke Indodax asli. Image `aidss-trader:e410ab7`, `aidss-api:e7b3da3`.
- Tes pada HEAD: Python 508 lulus, 1 xfail yang disengaja; Vitest 58 lulus; `tsc`, `oxlint` bersih; build berhasil.

## 2. Aturan keras
- Hanya baca. Akun uji dari pemilik (sebelumnya `test@mail.com`, role admin); jangan mendaftarkan akun baru. Buka dialog lalu **Batal**; jangan simpan kredensial, jangan resume/promote/FLATTEN/CANCEL,
  jangan simpan limit, parameter, biaya paper, atau ambang. Step-up meminta kata sandi pemilik: jangan diisi.
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit. Artefak uji ke `%TEMP%`, bukan repo. `tests/test_architecture_constraints.py` tidak boleh diedit.
- Jangan ubah `Landing.tsx`, `index.css`, `public/landing/`. Jangan push. Jangan `git add -A`; stage per nama file. Jangan `ruff format` pada direktori.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan".

## 3. Tugas N: verifikasi lazy loading di browser nyata (Playwright Chromium)
Pakai Playwright yang sudah ada di `%TEMP%\aidss-pw-verify` (atau pasang ulang di luar repo). Periksa dan simpan bukti di luar repo:
1. **Navigasi SPA antar ketujuh halaman Trader** (klik sidebar, bukan `goto`): tiap halaman menampilkan `<h1>`, `HALTED`, `PAPER`, 0 galat konsol/halaman, 0 request gagal.
   Catat chunk mana yang diunduh pada kunjungan pertama ke tiap halaman (event `response` untuk `/static/Trader*.js`) dan bahwa kunjungan kedua tidak mengunduh ulang.
2. **Akses langsung dan reload** pada tiap rute `/trader*`: 200 HTML, halaman tampil, hanya chunk halaman itu (ditambah chunk bersama) yang dimuat.
3. **Fallback loading:** perlambat satu chunk (`page.route('**/static/TraderLimits-*.js', ...)` dengan jeda 1,5 detik) dan pastikan ada keadaan loading yang jelas, bukan layar kosong; lalu halaman tampil.
4. **Chunk gagal dimuat:** blokir satu chunk (`route.abort()`), buka rutenya lewat navigasi SPA. Catat apa yang terlihat. Layar putih atau galat tak tertangkap = **cacat**.
5. **Offline setelah dimuat:** kunjungi satu halaman, putuskan jaringan (`context.setOffline(true)`), pindah ke halaman Trader lain yang belum pernah dibuka; catat perilakunya.
6. Lebar 375/768/1280: tanpa scroll horizontal pada `/trader` dan `/trader/limits`.

Jika langkah 4 atau 5 menunjukkan layar kosong atau galat yang tidak ditangkap, perbaiki di `frontend/src/App.tsx` (misalnya error boundary di sekitar `<Suspense>` dengan pesan dan tombol "muat ulang",
teks lewat i18n `id`/`en`) dan tambahkan tes Vitest yang mensimulasikan `import()` yang ditolak. **Jangan deploy.** Tulis di handoff bahwa perbaikan butuh build dan deploy oleh agen utama.
Jika tidak ada cacat, jangan mengubah kode.

## 4. Sebelum commit
`ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: `npx tsc -b --noEmit`, `npx oxlint .`, `npx vitest run`, `npm run build`.
(Pembungkus `npm run lint` mencetak "ESLint output (JSON parse failed)"; abaikan, pakai `npx oxlint .`. Satu kali `tsc` pernah gagal dengan `TS5102 baseUrl` lalu bersih di 4 run berikutnya; bila terulang, catat versi `tsc` yang terpakai.)
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Tambahkan record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`, dan perbarui `TASKS/PROGRESS.md` hanya sebatas bukti.

## 5. Handoff (wajib)
`MEMORY/handoffs/2026-11-15-N-lazy-route-verification.md` dan satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` yang diperbarui. Format:

```
Tanggal/jam, Agen, HEAD saat selesai (sha nyata), Status: SELESAI | DIBLOKIR
## 1. Ringkasan satu paragraf
## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti: [agen kedua] / [agen utama] / [pemilik]
## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, keluaran yang DIHARAPKAN)
## 5. DIVERIFIKASI vs DITULIS TAPI TIDAK DIJALANKAN
## 6. Temuan baru dan tindakannya
## 7. Keputusan yang menunggu pemilik
## 8. Rollback: cara, diuji atau belum, waktu yang DIUKUR (perkiraan berlabel)
## 9. Risiko tersisa
```
Daftar commit yang belum di-push diambil dari `git log --oneline origin/main..HEAD`. Jika terblokir atau ragu apakah suatu aksi aman, berhenti dan tulis handoff; jangan memperluas lingkup.
