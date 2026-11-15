# Handoff D: Sisa T6, celah P5 / Idempotensi durabel, dan ADR-050..052
Tanggal/jam: 2026-11-15 10:16 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: 40707f0        Status: SELESAI (dengan catatan butir owner-led tetap terbuka)

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Menutup seluruh item teknis Tugas D (D1–D8): (1) D4 `P5`: menambahkan indeks query dashboard/list pada `models.py` melalui migrasi aditif `0008_indexes_idempotency` dan memindahkan filter `OrderRow` serta `ApprovalRow` di `/dashboard` dan `/intents` ke SQL, terbukti memakai `Index Scan` / `Index Scan Backward` (`0.016–0.059 ms`) pada `EXPLAIN (ANALYZE, BUFFERS)` PostgreSQL 18 lokal; (2) D6: menyimpan cache replay `Idempotency-Key` ke tabel `trading.idempotency_key` (dengan fallback memori bila tabel tak terjangkau) dan mendokumentasikannya di `ADR-051` (`proposed`); (3) D5/D7/D8: menulis `ADR-050` (`S13` dependency pinning, `proposed`) dan `ADR-052` (`R5` frozen price feed, `proposed`) melengkapi `ADR-049` (parameter per pair); (4) D2 (`T6-03`): menjalankan `deploy/trader/rehearse_restore.sh` pada PostgreSQL 18 lokal (30 tabel pulih dalam `3s`, batas hak akses `trader_rw`/`trader_monitor` terverifikasi); (5) D3 (`T6-05`): memperbarui `docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md` dengan seluruh bukti tanpa mencentang butir milik pemilik; (6) memperbaiki literal token palsu di `tests/trader/test_liveness_monitor.py` agar tidak memicu pemindai rahasia S17.

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- `e410ab7` (`feat(trader): dashboard indexes, durable Idempotency-Key replay, ADR-050..052`):
  - `src/aidss_trader/db/models.py`, `src/aidss_trader/api/app.py`, `alembic_trader/versions/0008_indexes_idempotency.py`
  - `tests/trader/test_d_gaps.py`, `tests/trader/test_migration.py`, `tests/trader/test_liveness_monitor.py`
  - `MEMORY/DECISIONS.md`, `MEMORY/MEMORY-INDEX.md`, `MEMORY/records/2026-11-15-d-indexes-durable-idempotency-and-adrs.md`
- `7a84db8` (`docs(trader): record PostgreSQL 18 P5/restore/privilege rehearsals and update release checklist`):
  - `docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md`, `tests/trader/test_privileges_postgres.py`
  - `MEMORY/MEMORY-INDEX.md`, `MEMORY/records/2026-11-15-d2-d3-d4-postgres-rehearsal-and-checklist.md`
- Sengaja tidak disentuh: dependensi `pyproject.toml`/`Dockerfile.trader` (menunggu pemilik pilih opsi `ADR-050`), logika `EmaAdxStrategy` (menunggu `ADR-049`), detektor feed beku (menunggu `ADR-052`), `tests/test_architecture_constraints.py`, file landing page di working tree.

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- ruff: `All checks passed!` (`.\.venv\Scripts\python.exe -m ruff check src tests alembic_trader`)
- pytest (SQLite/mock): `496 passed, 7 deselected, 1 xfailed in 57.99s` (`test_s13_dependencies_are_pinned` = strict `xfail`).
- pytest (`-m postgres` pada PostgreSQL 18 lokal `aidss_rehearsal`): `7 passed, 5 deselected in 0.77s` termasuk `test_p5_dashboard_open_orders_query_uses_an_index`.
- `EXPLAIN (ANALYZE, BUFFERS)` (PostgreSQL 18 lokal, data sintetis 200–500 baris setelah `ANALYZE`):
  - `order`: `Index Scan using ix_order_origin_state` (`Execution Time: 0.038 ms`, `Buffers: shared hit=2`)
  - `approval`: `Index Scan using ix_trading_approval_state` (`Execution Time: 0.019 ms`, `Buffers: shared hit=2`)
  - `order_intent`: `Index Scan Backward using ix_trading_order_intent_created_at` (`Execution Time: 0.059 ms`, `Buffers: shared hit=6`)
  - `ledger_entry`: `Index Scan Backward using ix_trading_ledger_entry_at` (`Execution Time: 0.049 ms`, `Buffers: shared hit=4`)
  - `trading_event`: `Index Scan Backward using ix_trading_trading_event_created_at` (`Execution Time: 0.030 ms`, `Buffers: shared hit=4`)
  - `reconciliation_run`: `Index Scan Backward using ix_trading_reconciliation_run_started_at` (`Execution Time: 0.016 ms`, `Buffers: shared hit=2`)
- `rehearse_restore.sh` (PostgreSQL 18 lokal): `Restore rehearsal completed cleanly in 3s` (30 tabel; `rw_can_update_audit=f`, `rw_can_delete_audit=f`, `rw_can_update_ledger=f`, `monitor_can_select_lease=t`, `monitor_can_update_lease=f`, `monitor_can_select_cred=f`).
- front end: tidak diubah pada Tugas D.

## 4. Perintah verifikasi untuk agen utama (maksimal 8, murah, read-only, dengan keluaran yang DIHARAPKAN)
1. `python -m ruff check src tests alembic_trader` → `All checks passed!`.
2. `python -m pytest tests/trader tests/test_architecture_constraints.py -q` → `496 passed, 7 deselected, 1 xfailed`.
3. `python -m pytest tests/trader/test_d_gaps.py -q` → `5 passed, 1 deselected`.
4. `git show --stat e410ab7` dan `git show --stat 7a84db8` → hanya file Trader, migrasi, ADR, checklist, dan record.

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi: seluruh tes unit/integrasi (496 lulus), `test_d_gaps.py` (5 SQLite + 1 PostgreSQL), `P5` `EXPLAIN (ANALYZE, BUFFERS)` di PostgreSQL 18 lokal, `rehearse_restore.sh` di PostgreSQL 18 lokal (`3s`), dan S17 secret scanner setelah perbaikan `test_liveness_monitor.py`.
- Tidak dijalankan / butuh tindakan lanjut: job pemangkasan (`DELETE`) baris `idempotency_key` > 24 jam belum dibuat; `rehearse_restore.sh` pada database VM asli dan pemasangan cron `check_liveness.py` menunggu pemilik; implementasi `S13`, `R5`, dan parameter per-pair menunggu keputusan pemilik atas ADR-050, ADR-052, dan ADR-049.

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- `tests/trader/test_liveness_monitor.py` (commit `fc3100b`) mengandung literal `FAKE_TOKEN` yang cocok pola `telegram bot token` di `test_s17_no_tracked_file_contains_a_key_shaped_secret`; diperbaiki di `e410ab7` dengan merakit string saat runtime.

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
1. **ADR-050 (`S13`):** Pilih opsi pinning dependensi `Dockerfile.trader` (rekomendasi: lockfile dengan hash / `pip-compile --generate-hashes` atau `uv pip compile --generate-hashes`).
2. **ADR-052 (`R5`):** Pilih opsi deteksi feed harga beku beserta nilai `N` siklus / toleransi candle (angka pemilik).
3. **ADR-049:** Pilih antara satu set parameter global atau override per pair dengan reset `PAPER` per pair.
4. **ADR-051:** Setujui tabel `trading.idempotency_key` (sudah aditif di migrasi 0008) dan jadwalkan job pemangkasan baris > 24 jam.

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- Aplikasi: `git revert e410ab7` mengembalikan `_Replays` ke memori saja (tabel `idempotency_key` di DB tidak mengganggu bila dibiarkan); migrasi `0008` punya `downgrade()` yang men-drop `idempotency_key` (untuk dev saja per aturan aditif). Waktu pemulihan: < 1 menit.

## 9. Risiko tersisa dan hal yang harus diperhatikan agen berikutnya
- `EXPLAIN (ANALYZE, BUFFERS)` dijalankan di PostgreSQL 18 lokal dengan 200–500 baris sintetis, bukan langsung di VM; namun indeks yang sama sudah terpasang di VM lewat migrasi `0008` pada `55a8e16`.
