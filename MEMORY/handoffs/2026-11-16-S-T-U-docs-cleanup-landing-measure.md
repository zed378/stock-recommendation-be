# Handoff S, T, U: Sinkronisasi ADR, Pembersihan Frontend, dan Pengukuran Landing Produksi
Tanggal/jam: 2026-11-16 14:42 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: (lihat `git log --oneline origin/main..HEAD`; commit handoff ini ditambahkan setelah `1681f92`)        Status: SELESAI

## 1. Ringkasan satu paragraf
Ketiga tugas Tahap 10 (`S`, `T`, dan `U`) telah selesai tanpa menyentuh `Landing.tsx`, `Dockerfile*`, `docker-compose.yml`, `alembic*`, `tests/test_architecture_constraints.py`, maupun `ADR-052`. Pada Tugas S (`c4ea4d2`), referensi `ADR-046`, `ADR-047`, `ADR-049`, dan `ADR-051` di `TASKS/BACKLOG.md`, `TASKS/PROGRESS.md` (`T3`), dan `docs/09-SECURITY-PRIVACY/01-IDENTITY-RBAC.md` diselaraskan menjadi `accepted (owner, 2026-11-16)` (termasuk mencatat pruning oportunistik `_Replays._prune_expired` yang sudah teruji di `test_d_gaps.py`), sementara `ADR-052` tetap `proposed`. Pada Tugas T (`48ac1f4`), tiga JPEG yang tidak dipakai lagi di `frontend/public/landing/` (total `713,149` byte) dihapus via `git rm` setelah terkonfirmasi nol rujukan di kode maupun `frontend/dist/`, dan kunci i18n `rec.label.reduce` (`Kurangi` / `Reduce`) ditambahkan ke `frontend/src/i18n/messages.ts` beserta tes `RecommendationLabels.test.ts`. Pada Tugas U (`1681f92`), pengukuran read-only Playwright Chromium di `https://aidss.zedth.my.id` (`index-DUOgi8mR.js`) memastikan nol error konsol/CSP, `overflowPx: 0` di 7 ukuran x 2 bahasa, dan `intersects: false`; tercatat dua temuan minor di `Landing.tsx` (CLS `0.136979` saat font swap `1440x900 en`, serta `h1.scrollWidth` melebihi `clientWidth` `+7`/`+12 px` pada `375`/`320 px en` dengan `overflowPx: 0`) tanpa mengubah kode.

## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
Daftar commit yang belum di-push pada saat sebelum commit handoff (`git log --oneline origin/main..HEAD`):
- `1681f92` — `docs(task-u): record production landing page measurements (220f1cb)`: `MEMORY/records/2026-11-16-u-production-landing-measure.md`, `MEMORY/MEMORY-INDEX.md`.
- `48ac1f4` — `chore(task-t): remove unused landing JPEGs and add rec.label.reduce i18n`: `frontend/public/landing/exchange-architecture.jpg` (dihapus), `frontend/public/landing/hero-jakarta-skyline.jpg` (dihapus), `frontend/public/landing/quant-desk-editorial.jpg` (dihapus), `frontend/src/i18n/messages.ts`, `frontend/src/components/__tests__/RecommendationLabels.test.ts`, `MEMORY/records/2026-11-16-t-frontend-cleanup.md`, `MEMORY/MEMORY-INDEX.md`.
- `c4ea4d2` (sudah berada di `origin/main` sebelum `1e434f8`) — `docs(task-s): sync accepted ADR-046, 047, 049, 051 across docs and backlog`: `TASKS/BACKLOG.md`, `TASKS/PROGRESS.md`, `docs/09-SECURITY-PRIVACY/01-IDENTITY-RBAC.md`, `MEMORY/records/2026-11-16-adr-acceptance-sync.md`, `MEMORY/MEMORY-INDEX.md`.

**Sengaja tidak disentuh:** `frontend/src/pages/Landing.tsx`, `frontend/src/landing/*`, `tests/test_architecture_constraints.py`, `docker-compose.yml`, `Dockerfile*`, `alembic*`, `MEMORY/DECISIONS.md` (`ADR-052`), `MEMORY/records/` lama, berkas untracked `MEMORY/handoffs/PROMPT-stage-10.md`, serta seluruh pekerjaan VM/registry/owner-numbers.

## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti
- **[agen kedua] Tugas S (`pytest` routing + arsitektur):**
  ```text
  ..........................................                               [100%]
  42 passed in 9.28s
  ```
- **[agen kedua] Tugas T (`tsc`, `oxlint`, `vitest`, `build`, `dist` grep):**
  ```text
  Found 0 warnings and 0 errors.
  Finished in 68ms on 93 files with 104 rules using 16 threads.
  Test Files  13 passed (13)
       Tests  94 passed (94)
  ✓ built in 1.15s
  ```
  `Get-ChildItem -Recurse frontend/dist | Select-String -Pattern "exchange-architecture|hero-jakarta-skyline|quant-desk-editorial"` -> exit 0, keluaran kosong.
- **[agen kedua] Tugas T (`ruff` & `pytest` backend):**
  ```text
  All checks passed!
  518 passed, 7 deselected in 104.46s (0:01:44)
  ```
- **[agen kedua] Tugas U (Playwright Chromium pada `https://aidss.zedth.my.id/`):**
  - `mainChunk`: `"/static/index-DUOgi8mR.js"`
  - `consoleErrors: []`, `pageErrors: []`, `cspViolations: []`, `unexpectedFailedRequests: []`
  - Semua 14 skenario (`1920x1080`, `2560x1440`, `1440x900`, `1024x768`, `768x1024`, `375x812`, `320x640` x `id`/`en`): `overflowPx: 0`, `intersects: false`, `fontsLoaded: 3/3`.
  - Emulasi CDP (CPU 4x + Fast 3G, 3 kali ulang; **emulasi, bukan perangkat nyata**):
    - `1440x900`: LCP (`h1#lp-hero-title.lp-display`) median `2828 ms` (`2456–2884 ms`), CLS median `0.136979` (`0.025374–0.136979`), transfer median `383100 B` (`383085–383124 B`).
    - `375x812`: LCP median `2884 ms` (`2316–3060 ms`), CLS median `0.026922` (`0.026922–0.026922`), transfer median `383132 B` (`383126–383439 B`).
  - Perkiraan durasi interaksi (**bukan INP**): `openMobileMenu375Ms: 205`, `toggleIdEnMs: 156`, `clickLapisanAnchorMs: 115`.
  - `reducedMotion: "reduce"`: `--p` tetap `0.62`, `--rx`/`--ry` tetap `0`, `transitionDuration` `1e-05s`, `hiddenReveals: 0`. `no-preference`: `--p` berubah `0.3` -> `1`.
  - Papan ketik: `allVisibleFocus: true` (`20/20` Tab stops di `1440` dan `375`), `mobileMenuEscape`: `expandedOpen: "true"`, `expandedAfterEsc: "false"`, `returnedFocus: true`.
  - Bukti tangkapan layar (`hero-1920.png`, `hero-2560.png`, `hero-375.png`) dan `report.json` tersimpan di `%TEMP%\aidss-pw-verify\out-stage10\`.
- **[agen utama / pemilik] Belum dijalankan:** build/deploy `aidss-frontend` untuk membawa perubahan Tugas T ke produksi, `-m postgres`, hardening VM `10.1.200.13`, dan `T2-07`/`T5-06`.

## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, keluaran yang DIHARAPKAN)
1. `git log --oneline origin/main..HEAD` -> menampilkan `1681f92`, `48ac1f4`, dan commit handoff ini.
2. `git grep -nE "exchange-architecture|hero-jakarta-skyline|quant-desk-editorial" -- ":!MEMORY/records/" ":!MEMORY/handoffs/"` -> keluaran kosong (exit 1).
3. `.venv\Scripts\ruff.exe check src tests alembic_trader deploy` -> `All checks passed!`.
4. `.venv\Scripts\python.exe -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` -> `518 passed, 7 deselected`.
5. `cd frontend && .\node_modules\.bin\tsc.cmd -b --noEmit` -> exit 0 tanpa error.
6. `cd frontend && npx oxlint .` -> `Found 0 warnings and 0 errors.`
7. `cd frontend && npx vitest run --pool=vmThreads` -> `Test Files  13 passed (13)`, `Tests  94 passed (94)`.
8. `cd frontend && npm run build` -> sukses (`✓ built in ...`) tanpa error.

## 5. DIVERIFIKASI vs DITULIS TAPI TIDAK DIJALANKAN
- **DIVERIFIKASI (dengan bukti):** `42 passed` (routing+arsitektur Tugas S), `tsc` + `oxlint` + `94` Vitest + `vite build` + `dist/` grep kosong (Tugas T), `ruff` + `518 passed, 7 deselected` (Tugas T), serta pengukuran Playwright produksi `https://aidss.zedth.my.id` (`index-DUOgi8mR.js`, Tugas U).
- **DITULIS TAPI TIDAK DIJALANKAN:** Build image dan deploy ulang `aidss-frontend` agar penghapusan 3 JPEG serta label `rec.label.reduce` aktif di produksi.

## 6. Temuan baru dan tindakannya
1. **`h1.scrollWidth > h1.clientWidth` di `375x812 en` (`342` vs `335 px`) dan `320x640 en` (`292` vs `280 px`):** Kata `"recommendations"` melebar `+7 px` / `+12 px` melewati kotak `h1` (`overflowPx` viewport tetap `0`). Tidak diubah karena tidak menyebabkan overflow dokumen dan berada di `Landing.tsx`; dicatat untuk evaluasi pemilik jika ingin menurunkan floor `clamp` di `Landing.tsx`.
2. **CLS `0.136979` pada `1440x900 en` (dan `0.081512` pada `2560x1440 en`):** Terjadi akibat `font-display: swap` saat `Newsreader` selesai dimuat dan mengubah tinggi baris `h1` bahasa Inggris. Dicatat sebagai observasi tanpa mengubah `Landing.tsx`.
3. **Permintaan `/fonts/*` pada konteks segar tak-bercache:** Teramati `3` atau `5` permintaan (`inter-latin.woff2` dan `newsreader-display.woff2` muncul dua kali pada sebagian konteks Playwright). Dicatat apa adanya tanpa penyelidikan ulang.

## 7. Keputusan yang menunggu pemilik
- **ADR-052 (`proposed`):** Opsi dan ambang batas deteksi feed harga beku (`R5`).
- **ADR-054 (`proposed`):** Path `--out` dan jadwal cron host untuk `audit-anchor` (`T1-05`).
- **Angka parameter & operasional:** `OQ-5`, `OQ-8`, `OQ-9`, `OQ-11`, `OQ-12`, `OQ-16`, persetujuan hardening VM (`isolate_analysis_role.sql`, port `5432`, rotasi password DB/SSH), `check_liveness.py`, `T2-07`, dan `T5-06`.
- **Opsional dari Tugas U:** Apakah ingin menyesuaikan floor ukuran `h1` untuk `320/375 px en` atau strategi `font-display` di `Landing.tsx`.

## 8. Rollback: cara, diuji atau belum, waktu yang DIUKUR (perkiraan berlabel)
- Untuk mengembalikan Tugas S / T / U di repositori: `git revert <sha>` (atau `git reset` sebelum push). Belum diuji; perkiraan waktu `< 10 detik` (perkiraan berlabel, belum diukur).
- Produksi VM tidak diubah oleh Tahap 10 (`aidss-frontend:220f1cb` tetap berjalan).

## 9. Risiko tersisa
1. **`aidss-frontend` di produksi masih menjalankan `220f1cb`** (belum memuat `rec.label.reduce` dan penghapusan 3 JPEG `public/landing/` sampai agen utama membangun dan men-deploy ulang).
2. **Hardening host VM `10.1.200.13` belum dieksekusi** (port `5432` terbuka, `api`/`worker` memakai superuser `aidss`, password SSH/DB lama perlu rotasi).
3. **Monitor liveness (`check_liveness.py`), `audit-anchor` cron (`ADR-054`), dan latihan restore VM belum diaktifkan.**
4. **`ADR-052` dan seluruh angka risiko/strategi (`OQ-5/8/9/11/12/16`) masih kosong**, serta belum ada panggilan live Indodax (`T2-07`, `T5-06`).
5. **Tes pra-ada `tests/test_output_language.py::test_translation_covers_every_prose_field` masih gagal** (di luar cakupan Trader/Tahap 10).
