# Handoff A: Deploy migrasi 0007 (dan 0008) serta image `e410ab7` ke VM
Tanggal/jam: 2026-11-15 10:16 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: 40707f0        Status: SELESAI

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Migrasi `0007_backtest_runs` dan `0008_indexes_idempotency` sudah diterapkan pada PostgreSQL VM (`10.1.200.13`) sebagai `trader_owner` setelah latihan di database sementara dan `pg_dump` baru (`~/aidss-pre-0007-0008-*.sql.gz`, 71 MB). Image `zed378/aidss-trader:e410ab7` dan `zed378/aidss-frontend:e410ab7` sudah di-build dari `git archive HEAD` bersih, di-push, dan dijalankan di VM sementara `aidss-api:e7b3da3` tetap tidak berubah. `tests/trader/test_privileges_postgres.py` juga diperluas dengan `test_rw_can_insert_but_not_change_backtest_runs` untuk membuktikan `trading.backtest_run` bersifat append-only bagi `trader_rw`.

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- `55a8e16` (`docs: record the redeploy of e410ab7 and migrations 0007-0008`): `MEMORY/records/2026-11-15-first-deploy.md` (dilakukan pada sesi utama/pemilik).
- `7a84db8` (`docs(trader): record PostgreSQL 18 P5/restore/privilege rehearsals and update release checklist`): menambahkan `test_rw_can_insert_but_not_change_backtest_runs` di `tests/trader/test_privileges_postgres.py`.
- Sengaja tidak disentuh: file landing page yang belum di-commit di working tree (`frontend/src/pages/Landing.tsx`, `frontend/src/i18n/messages.ts`, `frontend/src/index.css`, `frontend/vite.config.ts`, `frontend/public/landing/`, `frontend/src/pages/__tests__/Landing.test.tsx`), `tests/test_architecture_constraints.py`.

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- ruff: `All checks passed!` (`.\.venv\Scripts\python.exe -m ruff check src tests alembic_trader`)
- pytest: `496 passed, 7 deselected, 1 xfailed in 57.99s` (SQLite/mock); `7 passed, 5 deselected in 0.77s` (`-m postgres` di PostgreSQL 18 lokal termasuk `test_rw_can_insert_but_not_change_backtest_runs`).
- front end: tidak diubah pada tugas A (terverifikasi pada Tugas C: 51 lulus, build bersih).
- keadaan VM (dari `MEMORY/records/2026-11-15-first-deploy.md` pasca-deploy `e410ab7`):
  - Image: `zed378/aidss-trader:e410ab7`, `zed378/aidss-frontend:e410ab7`, `zed378/aidss-api:e7b3da3`.
  - Migrasi: `0008_indexes_idempotency` (30 tabel di schema `trading`); `backtest_run` dan `idempotency_key` ada dan kosong.
  - Status Trader: `HALTED`, lease terpegang, `healthcheck` exit 0, header keamanan hadir pada respons terproksi.

## 4. Perintah verifikasi untuk agen utama (maksimal 8, murah, read-only, dengan keluaran yang DIHARAPKAN)
1. `git show --stat 55a8e16` → 1 file changed (`MEMORY/records/2026-11-15-first-deploy.md`).
2. `git show --stat 7a84db8` → 4 files changed termasuk `tests/trader/test_privileges_postgres.py`.
3. `python -m pytest tests/trader/test_migration.py -q` → `1 passed` (rantai `0001..0008`).
4. (Di VM, butuh kata sandi SSH `infra@10.1.200.13` dari pemilik): `docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"` → `aidss-trader:e410ab7`, `aidss-frontend:e410ab7`, `aidss-api:e7b3da3` sehat.
5. (Di VM): `docker exec stocks-trader-1 python -m aidss_trader healthcheck` → exit 0.

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi: migrasi `0001..0008`, 30 tabel di `trading`, Trader `HALTED`, lease aktif, `healthcheck` exit 0 di VM (`2026-11-15-first-deploy.md`); hak append-only `backtest_run` untuk `trader_rw` (`test_rw_can_insert_but_not_change_backtest_runs` lulus pada PostgreSQL 18 lokal).
- Belum dijalankan: eksekusi nyata pada `idempotency_key` atau `backtest_run` di VM; rebuild/redeploy untuk commit setelah `e410ab7` (`7a84db8`, `40707f0` hanya berisi dokumen/tes).

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- `test_privileges_postgres.py` belum menguji `backtest_run` hingga `7a84db8`; sudah ditambahkan dan lulus di PostgreSQL 18 lokal.

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
- Tidak ada untuk Tugas A; sisa pengetatan host ada di Handoff B.

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- Restore dump pra-migrasi di host (`~/aidss-pre-0007-0008-*.sql.gz`, 71 MB) + rollback tag image Compose ke `813d9cd`. Waktu pemulihan: ~1–2 menit (uji restore skema `trading` tercatat `3s` di PostgreSQL 18 lokal).

## 9. Risiko tersisa dan hal yang harus diperhatikan agen berikutnya
- Port 5432 masih terbuka dan `aidss` masih superuser di VM sampai Tugas B disetujui pemilik.
- Dump `~/aidss-pre-0007-0008-*.sql.gz` berada di disk yang sama dengan VM (ADR-040); ingatkan pemilik menyalinnya keluar host.
