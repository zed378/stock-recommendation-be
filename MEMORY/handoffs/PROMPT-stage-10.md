# Prompt tahap 10 untuk agen sebelah: sisa pekerjaan yang tidak butuh deploy, token, atau keputusan pemilik

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = origin/main = 4673ad3`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Tiga tugas (S, T, U). Kamu tidak punya akses SSH, build image, push image, deploy, atau token Docker Hub.

## 0. Baca dulu
`CLAUDE.md`, `AGENTS.md`, `MEMORY/handoffs/INDEX.md` dan handoff terakhir, `MEMORY/DECISIONS.md` (ADR-046, 047, 049, 050, 051, 052), `TASKS/BACKLOG.md`,
`MEMORY/records/2026-11-16-landing-redesign.md`, `MEMORY/records/2026-11-15-first-deploy.md` (dua bagian terakhir), `frontend/public/fonts/README.md`.
Untuk Tugas U baca juga, langsung dari berkasnya: `C:/Users/Zed/.claude/skills/antislop/SKILL.md` dan `antislop-ui/SKILL.md`.

## 1. Keadaan (fakta)
- Produksi `https://aidss.zedth.my.id` menjalankan `aidss-frontend:220f1cb` (landing baru: `frontend/src/pages/Landing.tsx`, `frontend/src/landing/`), `aidss-trader:e410ab7`, `aidss-api:e7b3da3`. Trader `HALTED`, tanpa URL exchange, tanpa kunci. Tidak pernah ada panggilan ke Indodax asli.
- Pemilik menerima pada 2026-11-16: ADR-046 (step-up 5 menit sekali pakai), ADR-047 (mulai `HALTED`; exit sinyal di mode `APPROVAL` tidak diantre), ADR-049 (opsi 1: satu set parameter untuk semua pair; desain override per pair tidak diadopsi), ADR-051 (tabel replay Idempotency-Key).
  **ADR-052 (harga beku) tetap `proposed`**: pemilik belum memilih opsi dan angka. Jangan memilihkan.
- `DECISIONS.md` sudah diperbarui (commit `785479c`), tetapi dokumen lain mungkin masih menyebut ADR tersebut `proposed`.
- Font landing: sudah diukur di produksi, tiap berkas diminta sekali; tidak ada duplikat. Jangan diselidiki ulang.
- Aset `frontend/public/landing/` berisi tiga JPEG (`exchange-architecture.jpg`, `hero-jakarta-skyline.jpg`, `quant-desk-editorial.jpg`) yang diduga tidak dipakai lagi sejak redesign `4a5bb9d`.
- Kunci i18n `rec.label.reduce` diduga hilang di aplikasi (ditemukan sebagai temuan sampingan; belum dilacak ke sumbernya).
- Tes: Trader + arsitektur + routing `515 passed, 7 deselected`; Vitest `93 passed` (dengan `--pool=vmThreads`). `tests/test_output_language.py::test_translation_covers_every_prose_field` gagal sejak sebelum Trader; bukan bagianmu.

## 2. Aturan keras
- **Bukan bagianmu, jangan disentuh:** tugas registry (build tag `latest`, hapus tag lama di Docker Hub), deploy image Trader dari lock 28 paket, hardening host (`pg_dumpall`, `aidss_app`, rotasi password, tutup 5432), monitor liveness/Telegram, rotasi password SSH,
  angka-angka milik pemilik, ADR-052, T2-07, T5-06. Semuanya menunggu pemilik atau agen utama.
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit (kunci contoh di dokumentasi Indodax juga tidak). Artefak uji ke `%TEMP%`, bukan repo. `tests/test_architecture_constraints.py` tidak boleh diedit.
- Tidak ada panggilan bertanda tangan ke Indodax. Produksi hanya dibaca (GET). Jangan login ke produksi untuk Tugas U (landing publik); jangan mendaftarkan akun. Jangan klik apa pun yang mengubah keadaan.
- Jangan ubah `docker-compose.yml`, `Dockerfile*`, `alembic*`. Jangan push. Jangan `git add -A`; stage per nama file. Jangan `ruff format` pada direktori. Jangan `git rm` di luar daftar Tugas T.
- Karena kita memakai working tree yang sama, periksa `git status` dulu dan jangan menjalankan tes saat agen utama sedang mengubah berkas.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan".
- Untuk teks UI/i18n dan komentar kode, aturan antislop berlaku: tanpa em dash, tanpa angka atau ticker karangan, komentar menjelaskan alasan, bukan apa.

## 3. Tugas S: selaraskan dokumen dengan keputusan pemilik (hanya dokumen)
1. `git grep -nE "ADR-0(46|47|49|51)"` di `docs/`, `TASKS/`, `MEMORY/` (kecuali `DECISIONS.md` dan `MEMORY/records/` yang tanggalnya lampau: record lama tidak ditulis ulang), lalu daftar setiap tempat yang menyebut keempat ADR itu `proposed` atau menunggu pemilik. Perbarui menjadi `accepted (owner, 2026-11-16)`.
2. `TASKS/BACKLOG.md` baris ADR-049 (override per pair): ganti menjadi keputusan "satu set parameter, desain override tidak diadopsi; buka lagi hanya bila pemilik meminta". Baris ADR-051 (job pruning): baca ADR-051 dan `src/aidss_trader/api` (`_Replays._prune_expired`, Task H)
   lalu tulis kondisi nyata: jika pruning oportunistik sudah ada dan teruji, tandai butir ini selesai (rujuk tesnya); jika tidak, biarkan terbuka dan jelaskan. Baris ADR-052 tetap terbuka.
3. `CLAUDE.md` dan `TASKS/PROGRESS.md`: bila ada kalimat yang menyebut ADR tadi sebagai belum diputuskan, selaraskan. Jangan mengubah klaim lain; jangan menulis bahwa Trader bisa trading.
4. Tambahkan record `MEMORY/records/2026-11-16-adr-acceptance-sync.md` (daftar berkas yang diubah dan alasan), satu baris di `MEMORY/MEMORY-INDEX.md`. Tidak perlu tes kode; jalankan `python -m pytest tests/test_frontend_routing.py tests/test_architecture_constraints.py -q` sebagai bukti tidak ada yang rusak.

## 4. Tugas T: pembersihan kecil di frontend
1. **JPEG tidak terpakai.** Untuk setiap dari tiga berkas: `git grep` nama berkasnya di seluruh repo (`frontend/src`, `frontend/index.html`, `frontend/nginx.conf`, `docs/`, README, tes), dan cari juga di hasil `npm run build` (`dist`) apakah masih dirujuk. Hanya bila **nol rujukan kode** (rujukan di record sejarah tidak dihitung),
   hapus dengan `git rm` dan catat ukurannya. Jika ada rujukan hidup, jangan hapus; laporkan. Perbarui `frontend/public/fonts/README.md` atau README aset hanya bila menyebutnya.
2. **`rec.label.reduce`.** Lacak: di mana kunci ini dibentuk (kemungkinan dari `rec.label.${nilai}` atau pemetaan rekomendasi), nilai apa yang menghasilkan `reduce`, dan apakah `frontend/src/i18n/messages.ts` punya kunci `rec.label.*` untuk nilai lain (`buy`, `hold`, `sell`, dan seterusnya) di kedua bahasa.
   Tentukan dari data backend (`src/aidss`, skema rekomendasi) apakah `reduce` nilai yang sah. Jika sah dan kuncinya hilang: tambahkan terjemahan `id` dan `en` yang konsisten dengan kunci tetangga (tanpa em dash), dan tes Vitest yang memastikan setiap nilai rekomendasi yang sah punya label di kedua bahasa.
   Jika `reduce` bukan nilai sah, jangan menambah kunci; laporkan asal nilainya.
3. Verifikasi frontend (bagian 6). Jangan menyentuh `Landing.tsx` pada tugas ini.

## 5. Tugas U: ukur landing di produksi (read-only)
Playwright Chromium dari Node (`%TEMP%\aidss-pw-verify`; paket ada di cache npx pengguna, python tidak punya Playwright). Landing publik, tanpa login. Bukti di luar repo.
1. **Versi:** chunk utama produksi harus `index-DUOgi8mR.js` (image `220f1cb`).
2. **Tata letak hero** pada 1920x1080, 2560x1440, 1440x900, 1024x768, 768x1024, 375x812, 320x640, masing-masing `id` dan `en`: ukuran font `h1`, jarak horizontal/vertikal antara kotak teks `h1` dan kotak tumpukan 3D (`.lp-stack`), apakah kotak keduanya beririsan (bounding box), tinggi hero, `scrollWidth` = lebar viewport, teks terpotong. Acuan agen utama: gap 70 px (1440 en, 1920 en), 85 px (1920 id).
3. **Font:** untuk satu pemuatan segar per ukuran: jumlah request `/fonts/*` (harus 3 di desktop; catat jika berbeda), `document.fonts` status `loaded`, dan apakah `font-display: swap` menimbulkan pergeseran terlihat (CLS dari `PerformanceObserver` `layout-shift`).
4. **Kinerja:** LCP, CLS, dan total byte transfer halaman `/` pada 1440x900 dan 375x812 dengan CPU 4x lebih lambat dan jaringan "Fast 3G" (CDP `Network.emulateNetworkConditions` / `Emulation.setCPUThrottlingRate`), tiga kali ulang, laporkan median dan rentang. Label jelas bahwa ini emulasi, bukan perangkat nyata.
   Catat elemen LCP (selector). INP tidak bisa diukur tanpa interaksi nyata; ukur durasi tiga interaksi (buka menu mobile di 375, ganti `ID`/`EN`, klik jangkar `#lapisan`) dan labeli sebagai "perkiraan, bukan INP".
5. **Reduced motion:** dengan `reducedMotion: "reduce"`, gulir hero dan bagian lapisan dan pastikan `--p`, `--rx`, `--ry` pada `.lp-stack` tidak berubah, tidak ada transisi (`transition-duration` terhitung 0s untuk `.lp-plane`, `.lp-stack-scene`, `.lp-reveal`), dan semua konten terlihat (tidak ada elemen `.lp-reveal` yang tetap `opacity: 0`). Ulangi dengan `no-preference` dan tunjukkan bahwa nilainya berubah saat digulir.
6. **Papan ketik:** Tab melalui halaman di 1440 dan 375; catat urutan fokus, bahwa setiap elemen fokus punya indikator terlihat, dan bahwa menu mobile menutup dengan Escape serta mengembalikan fokus ke tombolnya.
7. **Konsol/jaringan:** tidak ada error konsol, request gagal (selain `/api/` yang memang 401 untuk pengunjung), atau peringatan CSP.
8. Tangkapan layar hero (1920, 2560, 375) ke `%TEMP%`.

Bila ada cacat terukur (irisan teks dan tumpukan, overflow, elemen yang tetap tersembunyi, gerak saat reduced motion, fokus tak terlihat, LCP buruk dengan penyebab jelas di kode): tentukan penyebab dari data, perbaiki hanya di `Landing.tsx`, `frontend/src/landing/*`, atau `frontend/src/i18n/messages.ts`,
tambahkan tes Vitest yang mereproduksinya bila bisa diuji di jsdom, dan **jangan deploy**; tulis di handoff bahwa butuh build dan deploy oleh agen utama. Jika bersih, jangan mengubah kode. Temuan di luar cakupan dicatat dengan daftar berkas, bukan diperbaiki.
Jangan menyatakan "cepat" atau "lolos Core Web Vitals" dari satu mesin dan emulasi; tulis angka dan batasnya.

## 6. Sebelum commit
Tugas S saja (dokumen): cukup bukti di Tugas S.4. Bila ada perubahan kode (T atau U):
`ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: **`./node_modules/.bin/tsc -b --noEmit`** (bukan `npx tsc`: TypeScript 7.0.2 global kadang menggantikan 5.9.3), `npx oxlint .`,
**`npx vitest run --pool=vmThreads`** (pool bawaan gagal pada Node 26, juga pada HEAD bersih), `npm run build`.
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong.
Setiap tugas menambah record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`, dan `TASKS/PROGRESS.md` hanya sebatas bukti. Satu commit per tugas, pesan menyebut tugasnya.

## 7. Handoff (wajib, sembilan bagian lengkap)
`MEMORY/handoffs/2026-11-16-S-T-U-docs-cleanup-landing-measure.md`, satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` diperbarui. Format (jangan lewati bagian mana pun):

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
