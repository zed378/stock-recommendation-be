# Handoff H: Pemangkasan oportunistik `trading.idempotency_key` (`ADR-051`)
Tanggal/jam: 2026-11-15 10:30 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: a6b385e        Status: SELESAI

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Menutup celah `ADR-051` (pertumbuhan baris kedaluwarsa di `trading.idempotency_key`) tanpa menambah cron/worker baru: `_Replays.put()` di `src/aidss_trader/api/app.py` sekarang memanggil `_Replays._prune_expired(now)` setelah `put` selesai di-commit, menghapus baris dengan `created_at < now - timedelta(seconds=REPLAY_TTL_S)` dalam transaksi terpisah yang dibungkus `try/except` sehingga kegagalan pemangkasan tidak pernah menggagalkan request utama. `ADR-051` di `MEMORY/DECISIONS.md` diperbarui, dua tes baru ditambahkan di `tests/trader/test_d_gaps.py`, dan catatan di `MEMORY/records/2026-11-15-h-idempotency-pruning.md` ditulis serta diindeks.

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- `a6b385e` (`feat(trader): opportunistic pruning of expired idempotency_key rows (ADR-051)`):
  - `src/aidss_trader/api/app.py`
  - `tests/trader/test_d_gaps.py`
  - `MEMORY/DECISIONS.md`
  - `MEMORY/MEMORY-INDEX.md`
  - `MEMORY/records/2026-11-15-h-idempotency-pruning.md`
- Sengaja tidak disentuh: `alembic_trader/versions/0008_indexes_idempotency.py` (tidak ada perubahan skema), file landing page di working tree.

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- ruff: `All checks passed!` (`.\.venv\Scripts\python.exe -m ruff check src tests alembic_trader deploy`)
- `test_d_gaps.py`: `7 passed, 1 deselected in 0.90s` (`.\.venv\Scripts\python.exe -m pytest tests/trader/test_d_gaps.py -q`)
- pytest penuh Trader + arsitektur: `498 passed, 7 deselected, 1 xfailed in 70.10s` (`.\.venv\Scripts\python.exe -m pytest tests/trader tests/test_architecture_constraints.py -q`)

## 4. Perintah verifikasi untuk agen utama (maksimal 8, murah, read-only, dengan keluaran yang DIHARAPKAN)
1. `python -m ruff check src tests alembic_trader deploy` → `All checks passed!`.
2. `python -m pytest tests/trader/test_d_gaps.py -q` → `7 passed, 1 deselected`.
3. `python -m pytest tests/trader tests/test_architecture_constraints.py -q` → `498 passed, 7 deselected, 1 xfailed`.
4. `git show --stat a6b385e` → hanya 5 file (`app.py`, `test_d_gaps.py`, `DECISIONS.md`, `MEMORY-INDEX.md`, `2026-11-15-h-idempotency-pruning.md`).

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi `[agen kedua]`: penghapusan baris > 24 jam sambil mempertahankan baris segar (`test_put_prunes_expired_rows_but_keeps_fresh_rows`) dan ketahanan ketika query pemangkasan gagal (`test_pruning_failure_does_not_fail_put_or_request`), serta seluruh suite Trader (498 lulus).
- Belum dijalankan di VM `[pemilik]`: image VM masih `e410ab7`; commit `a6b385e` belum di-build/deploy ke VM.

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- Tidak ada temuan baru pada Tugas H.

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
- Tidak ada keputusan tambahan di luar persetujuan `ADR-051` (`proposed` -> `accepted` bila sudah diulas pemilik).

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- `git revert a6b385e` mengembalikan `_Replays.put()` ke versi tanpa `_prune_expired()`. Tidak ada perubahan skema DB. Waktu pemulihan: < 1 menit (estimasi; mekanisme standar `git revert`).

## 9. Risiko tersisa dan hal yang harus diperhatikan agen berikutnya
- Jika `trading.idempotency_key` sudah terlanjur besar sebelum pemangkasan berjalan, `DELETE` oportunistik pertama kali bisa menghapus banyak baris sekaligus; pada traffic Operator UI tunggal saat ini risikonya rendah.
