# Handoff Index

Newest first.

- [2026-11-15 — L: Skrip latihan hardening & restore `--full` yang bisa diulang](2026-11-15-L-rehearsal-scripts.md) — `SELESAI` (`rehearse_isolation.sh`, `rehearse_restore.sh --full`, tes statis, PG 18 lokal)
- [2026-11-15 — K: Verifikasi browser ulang (perbaikan nginx, sidebar, dan landing page)](2026-11-15-K-live-browser-reverification.md) — `SELESAI` (7 rute Trader `goto`+`reload` 200 HTML, sidebar persist + auto-expand, landing `/` lulus)
- [2026-11-15 — Z: Ringkasan akhir Tahap 3 (H, I, J selesai; F & G menunggu SSH & gerbang)](2026-11-15-Z-final.md) — rangkuman akhir Tahap 3 untuk pemilik dan agen utama
- [2026-11-15 — J: Sinkronisasi dokumen Tahap 3 (`PROGRESS.md`, `BACKLOG.md`, `MEMORY-INDEX.md`)](2026-11-15-J-doc-sync.md) — `SELESAI`
- [2026-11-15 — G: Monitor liveness luar-proses & latihan restore VM](2026-11-15-G-liveness-and-restore-rehearsal.md) — `BERHENTI DI GERBANG` (menunggu kata sandi SSH & persetujuan pemilik; perintah R14 siap)
- [2026-11-15 — F: Hardening host PostgreSQL 16 (`10.1.200.13`)](2026-11-15-F-host-hardening-pg16.md) — latihan PG 16 `SELESAI` (agen utama, klon `aidss`); eksekusi produksi `BERHENTI DI GERBANG` (persetujuan pemilik per langkah)
- [2026-11-15 — I: Verifikasi browser langsung Playwright (`https://aidss.zedth.my.id`)](2026-11-15-I-live-browser-verification.md) — `SELESAI` (7 halaman SPA lulus; temuan bug routing reverse proxy `404` pada akses URL langsung `/trader*`)
- [2026-11-15 — H: Pemangkasan oportunistik `trading.idempotency_key` (`ADR-051`)](2026-11-15-H-idempotency-pruning.md) — `SELESAI` (`a6b385e`)
- [2026-11-15 — Z: Ringkasan akhir tahap 2 (commit belum di-push, keadaan VM, 5 risiko utama)](2026-11-15-Z-final.md) — rangkuman akhir untuk pemilik dan agen utama
- [2026-11-15 — E: Sinkronisasi dokumen (`TASKS/PROGRESS.md`, `CLAUDE.md`, `TASKS/BACKLOG.md`)](2026-11-15-E-doc-sync.md) — `SELESAI` (`40707f0`)
- [2026-11-15 — D: Sisa T6, indeks P5, idempotensi durabel, dan ADR-050..052](2026-11-15-D-t6-gaps-and-adrs.md) — `SELESAI` (`e410ab7`, `7a84db8`; butir owner-led tetap terbuka)
- [2026-11-15 — C: Verifikasi UI Trader dan perbaikan kontras/lokalisasi](2026-11-15-C-ui-verification.md) — `DIBLOKIR` (Chrome live `DevToolsActivePort`) / `SELESAI` (`1a07d95`, 51 Vitest lulus)
- [2026-11-15 — B: Eksekusi hardening host (`10.1.200.13`)](2026-11-15-B-host-hardening.md) — `BERHENTI DI GERBANG` (latihan PG 18 lokal 7/7 lulus + rollback bersih; VM butuh izin & SSH password)
- [2026-11-15 — A: Deploy migrasi 0007 (dan 0008) serta image `e410ab7` ke VM](2026-11-15-A-deploy-migration-0007.md) — `SELESAI` (`55a8e16`, `7a84db8`)
