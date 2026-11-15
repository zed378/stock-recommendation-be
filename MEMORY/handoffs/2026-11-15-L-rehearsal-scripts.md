# Handoff L: Skrip latihan hardening & restore `--full` yang bisa diulang
Tanggal/jam: 2026-11-15 11:39 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: (commit Tugas L)        Status: SELESAI

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Menjadikan prosedur latihan hardening dan restore sebagai alat repo yang aman dan teruji: menambahkan `deploy/trader/rehearse_isolation.sh` (klon ke DB scratch, terapkan `isolate_analysis_role.sql`, sandi acak via stdin, verifikasi atribut/kepemilikan/`SET ROLE aidss_app` ditolak di `trading`, ukur waktu rollback, bersih-bersih di `trap`), memperluas `deploy/trader/rehearse_restore.sh` dengan flag `--full` (tetap kompatibel tanpa flag), menambahkan tes statis `tests/trader/test_rehearsal_scripts.py`, dan memperbarui `docs/10-OPERATIONS/06-RUNBOOKS.md` (R13/R14).

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- File pada commit Tugas L:
  - `deploy/trader/rehearse_isolation.sh`
  - `deploy/trader/rehearse_restore.sh`
  - `tests/trader/test_rehearsal_scripts.py`
  - `docs/10-OPERATIONS/06-RUNBOOKS.md`
  - `MEMORY/records/2026-11-15-l-rehearsal-scripts.md`
  - `MEMORY/handoffs/2026-11-15-L-rehearsal-scripts.md`
  - `MEMORY/MEMORY-INDEX.md`, `MEMORY/handoffs/INDEX.md`
- Sengaja tidak disentuh: `deploy/trader/isolate_analysis_role.sql` dan `deploy/trader/rollback_analysis_role.sql` (tidak ada cacat yang ditemukan).

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- Semua dijalankan oleh `[agen kedua]` pada **PostgreSQL 18 lokal** (`pgvector/pgvector:pg18`, 30 tabel `trading` + 1 tabel `public`):
  - `rehearse_isolation.sh` (sukses): `Clone completed in 2s`, `Isolation applied in 1s`, `aidss_app | f | f | f | f`, `public_tables_not_owned_by_aidss_app = 0`, `Verified: public DDL ok, trading.audit_log denied for aidss_app.`, `public_tables_not_owned_by_superuser = 0`, `Isolation rehearsal completed cleanly (isolate=1s, rollback=1s).` (exit `0`).
  - `rehearse_isolation.sh` (kegagalan disengaja `nonexistent_db`): exit `1`, `Remaining DBs:` kosong (`trap cleanup` membersihkan DB scratch).
  - `rehearse_restore.sh --full`: `public | 1`, `trading | 30`, `rw_can_update_audit=f`, `rw_can_delete_audit=f`, `rw_can_update_ledger=f`, `monitor_can_select_lease=t`, `monitor_can_update_lease=f`, `monitor_can_select_cred=f`, `Restore rehearsal completed cleanly in 4s` (exit `0`).
  - `rehearse_restore.sh` (tanpa flag): `trading | 30`, `Restore rehearsal completed cleanly in 4s` (exit `0`).
  - `test_rehearsal_scripts.py`: `3 passed in 0.26s`.
  - `ruff check src tests alembic_trader deploy`: `All checks passed!`.
  - Suite penuh (`pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`): `508 passed, 7 deselected, 1 xfailed in 115.20s`.

## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, dengan keluaran yang DIHARAPKAN)
1. `python -m ruff check src tests alembic_trader deploy` → `All checks passed!`.
2. `python -m pytest tests/trader/test_rehearsal_scripts.py -q` → `3 passed`.
3. `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` → `508 passed, 7 deselected, 1 xfailed` (diverifikasi di `task-1833`).

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi `[agen kedua]`: kedua skrip pada PostgreSQL 18 lokal (sukses, gagal disengaja, `--full`, dan mode default) serta tes statis Python.
- Tidak dijalankan `[pemilik] / [agen utama]`: eksekusi kedua skrip pada **PostgreSQL 16 VM** `10.1.200.13`.

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- **Bug awal yang ditemukan & diperbaiki saat uji coba:** `pg_dump | psql` dalam `sh` POSIX menyembunyikan kegagalan `pg_dump` karena tidak ada `pipefail`; diperbaiki dengan dump ke `/tmp/${SCRATCH_DB}.sql` (dihapus di `cleanup()`) sebelum restore ke `SCRATCH_DB`.
- **Perbedaan lingkungan:** diuji pada **PostgreSQL 18 lokal** dengan skema kosong + 1 tabel `public`, bukan **PostgreSQL 16 VM** (`aidss` 337 MB).

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
- Jalankan `sh deploy/trader/rehearse_restore.sh --full stocks-postgres-1 aidss aidss` di VM saat sesi pemilik untuk mencatat waktu restore penuh pada data produksi 337 MB.

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- `git revert <sha>` (< 1 menit, perkiraan).

## 9. Risiko tersisa
- Durasi `rehearse_restore.sh --full` di VM (~337 MB) akan lebih lama dari 4 detik pada DB lokal yang hampir kosong.
