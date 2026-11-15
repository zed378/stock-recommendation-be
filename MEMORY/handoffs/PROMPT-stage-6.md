# Prompt tahap 6 untuk agen sebelah: verifikasi `f08e3af` di browser (halaman lazy dan boundary kegagalan chunk)

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = origin/main = e467a26`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Satu tugas (O), read-only terhadap produksi. Tidak ada akses SSH, build, push image, atau deploy untukmu.

## 0. Baca dulu
`CLAUDE.md`, `AGENTS.md`, `MEMORY/handoffs/INDEX.md`, handoff N, `MEMORY/records/2026-11-15-lazy-signed-in-pages.md`,
`MEMORY/records/2026-11-15-first-deploy.md` (bagian redeploy `f08e3af`), `frontend/src/App.tsx`, `frontend/src/lazyPages.ts`.

## 1. Keadaan (fakta)
- Produksi `https://aidss.zedth.my.id` menjalankan `aidss-frontend:f08e3af` (chunk utama `index-X8GmafIB.js`, 248 kB). Sejak `ab5a9ab`:
  1. `LazyRoute` (alias lama `LazyTraderRoute`) = `ChunkErrorBoundary` + `Suspense` per rute, dengan pesan i18n `trader.routeError.*`
     ("Halaman gagal dimuat" / "Page failed to load", tombol "Muat ulang" / "Reload").
  2. Ke-13 halaman setelah login kini chunk sendiri: `Watchlist`, `AssetDetail`, `Portfolio`, `Journal`, `Chat`, `Agenda`, `ScreenBuilder`, `MarketChat`, `Shared`, `Profile`, `Admin`, `StockPicks`, `Monitoring`.
     `Landing` dan `Login` tetap di chunk utama.
- Dengan `curl` saja: rute `/`, `/login`, `/watchlist`, `/trader*` 200 `text/html`; chunk `Watchlist`, `AssetDetail`, `Admin`, `Monitoring`, `Trader` 200. **Perilaku baru belum pernah dicoba di browser.**
  Skenario abort/offline di tahap 5 dijalankan pada `ab5a9ab`, yang belum punya boundary.
- Trader `HALTED`, tanpa URL exchange, tanpa kunci. Tidak pernah ada panggilan ke Indodax asli.

## 2. Aturan keras
- Hanya baca. Akun uji dari pemilik (sebelumnya `test@mail.com`, role admin); jangan mendaftarkan akun baru. Buka dialog lalu **Batal**; jangan simpan kredensial, resume, promote, FLATTEN/CANCEL, jangan simpan
  limit/parameter/biaya paper/ambang. Step-up meminta kata sandi pemilik: jangan diisi. Jangan mengubah data produksi di halaman `Admin`, `Portfolio`, `Journal`, `Watchlist`, `Profile` (buka dan baca saja).
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit. Artefak uji ke `%TEMP%`, bukan repo. `tests/test_architecture_constraints.py` tidak boleh diedit.
- Jangan ubah `Landing.tsx`, `index.css`, `public/landing/`. Jangan push. Jangan `git add -A`; stage per nama file. Jangan `ruff format` pada direktori.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan".

## 3. Tugas O
Pakai Playwright Chromium (`%TEMP%\aidss-pw-verify`, atau pasang ulang di luar repo). Simpan bukti di luar repo.
1. **Chunk utama** halaman dimuat adalah `index-X8GmafIB.js`; konfirmasi bahwa produksi memang `f08e3af` (nama chunk, bukan asumsi).
2. **Navigasi SPA** (klik sidebar) ke semua halaman bertanda lazy di atas yang bisa dibuka akun uji, plus ketujuh halaman Trader: tiap halaman tampil (`<h1>` atau landmark utama), 0 galat konsol/halaman, 0 request gagal.
   Catat chunk yang diunduh pada kunjungan pertama dan bahwa kunjungan kedua tidak mengunduh ulang. `Admin` dan `/admin/:section`: buka sekurang-kurangnya dua bagian lewat alamatnya.
3. **Akses langsung dan reload** untuk minimal `/watchlist`, `/assets/<satu ticker yang ada di watchlist>`, `/admin`, `/monitoring`, `/trader/limits`: 200 HTML, halaman tampil.
4. **Fallback loading:** perlambat satu chunk non-Trader (`page.route('**/static/AssetDetail-*.js', ...)` jeda 1,5 detik) dan satu chunk Trader; tidak boleh layar kosong, sidebar tetap tampil selama menunggu.
5. **Chunk gagal dimuat (inti tugas ini):** blokir (`route.abort()`) `AssetDetail-*.js`, lalu `Monitoring-*.js`, lalu `TraderPaper-*.js` pada kunjungan pertama lewat navigasi SPA. Untuk tiap kasus catat: `role="alert"` muncul dengan judul, isi, dan tombol "Muat ulang"/"Reload"
   dalam bahasa aktif (uji `id` dan `en`); sidebar masih bisa dipakai; mengeklik rute lain yang chunk-nya sehat berfungsi tanpa muat ulang penuh (boundary diatur ulang per `pathname`); tombol muat ulang setelah rute dibuka kembali (hapus blokir lebih dulu) memulihkan halaman.
   Layar kosong, `pageErrors` tak tertangkap, atau boundary yang menempel setelah pindah rute = **cacat**.
6. **Offline setelah dimuat:** kunjungi satu halaman, `context.setOffline(true)`, buka halaman lain yang belum pernah dibuka (satu Trader, satu non-Trader); catat perilaku, dan pulihkan setelah `setOffline(false)` + tombol muat ulang.
7. Lebar 375/768/1280: tanpa scroll horizontal pada `/watchlist`, `/assets/<ticker>`, `/trader`, dan pada layar galat boundary. Fokus keyboard tampak pada tombol "Muat ulang", dan kontras teks galat memadai.
8. Perhatikan juga: apakah ada halaman yang memakai `useParams`/state dan kehilangannya karena `key={pathname}` pada boundary (misalnya pindah antar `/assets/A` dan `/assets/B`, atau antar `/admin/:section`: konten harus berganti dengan benar, tanpa kilatan layar kosong yang lama).

Jika ada cacat, perbaiki hanya di `frontend/src/App.tsx`, `frontend/src/lazyPages.ts`, atau komponen yang memang terkait, tambahkan tes Vitest yang mereproduksinya, dan jangan deploy.
Jika tidak ada cacat, jangan mengubah kode. Cacat di `Landing.tsx` atau `index.css` hanya dicatat sebagai temuan.

## 4. Sebelum commit
`ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: **`./node_modules/.bin/tsc -b --noEmit`** (bukan `npx tsc`:
ada TypeScript 7.0.2 global di `%APPDATA%\npm\tsc` yang kadang menggantikan 5.9.3 milik proyek dan memunculkan TS5102 `baseUrl`; cek `./node_modules/.bin/tsc --version` = 5.9.3), `npx oxlint .`, `npx vitest run`, `npm run build`.
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Tambahkan record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`, dan perbarui `TASKS/PROGRESS.md` hanya sebatas bukti.

## 5. Handoff (wajib)
`MEMORY/handoffs/2026-11-15-O-lazy-pages-browser-verification.md` dan satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` yang diperbarui. Format:

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
