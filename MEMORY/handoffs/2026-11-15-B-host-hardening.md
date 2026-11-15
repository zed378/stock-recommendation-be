# Handoff B: Eksekusi hardening host (`10.1.200.13`)
Tanggal/jam: 2026-11-15 10:16 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: 40707f0        Status: BERHENTI DI GERBANG

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Belum ada perubahan yang dijalankan di VM `10.1.200.13` karena tugas ini membutuhkan kata sandi SSH `infra@10.1.200.13` dan persetujuan eksplisit pemilik per aksi tak terbalik (penutupan port 5432, rotasi kata sandi superuser `aidss`, pemindahan role analisis ke `aidss_app`). Seluruh rangkaian SQL (`bootstrap.sql`, `isolate_analysis_role.sql`, migrasi `0001..0008`, dan `rollback_analysis_role.sql`) telah dilatih penuh di kontainer PostgreSQL 18 lokal terisolasi (`pgvector/pgvector:pg18`), dan seluruh 7 tes `-m postgres` termasuk `test_analysis_app_role_owns_public_but_cannot_access_trading_schema` serta `test_monitor_role_reads_heartbeat_only` lulus.

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- `7a84db8` (`docs(trader): record PostgreSQL 18 P5/restore/privilege rehearsals and update release checklist`): `MEMORY/records/2026-11-15-d2-d3-d4-postgres-rehearsal-and-checklist.md`, `MEMORY/MEMORY-INDEX.md`.
- Script yang sudah ada dan dilatih (tidak diubah): `deploy/trader/bootstrap.sql`, `deploy/trader/isolate_analysis_role.sql`, `deploy/trader/rollback_analysis_role.sql`, `deploy/trader/docker-compose.trader.yml`.
- Sengaja tidak disentuh: file landing page di working tree, file `src/aidss/`.

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- ruff: `All checks passed!`
- pytest (`-m postgres` di PostgreSQL 18 lokal, database `aidss_rehearsal`):
  - `tests/trader/test_privileges_postgres.py::test_analysis_app_role_owns_public_but_cannot_access_trading_schema PASSED [ 71%]`
  - `tests/trader/test_privileges_postgres.py::test_monitor_role_reads_heartbeat_only PASSED [ 85%]`
  - `7 passed, 5 deselected in 0.77s`
- rollback (`rollback_analysis_role.sql`): `BEGIN` / `DO` / `COMMIT` (exit 0).
- front end: tidak berlaku.
- keadaan VM: tidak diubah oleh agen ini (port `0.0.0.0:5432` masih terbuka dan API analisis masih memakai superuser `aidss`).

## 4. Perintah verifikasi untuk agen utama (maksimal 8, murah, read-only, dengan keluaran yang DIHARAPKAN)
1. `Get-Content MEMORY/records/2026-11-15-d2-d3-d4-postgres-rehearsal-and-checklist.md` → memuat hasil latihan lokal `7 passed, 5 deselected in 0.77s` dan `rollback_analysis_role.sql`.
2. `git show --stat 7a84db8` → 4 file berubah.
3. (Di VM setelah pemilik menyetujui & memberikan kata sandi SSH): `ss -tnp 'sport = :5432'` dan `SELECT client_addr, usename FROM pg_stat_activity WHERE client_addr IS NOT NULL;` → pra-cek koneksi sebelum menutup port.

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi: `bootstrap.sql`, `isolate_analysis_role.sql`, `rollback_analysis_role.sql`, dan 7 tes `-m postgres` pada PostgreSQL 18 lokal (`2026-11-15-d2-d3-d4-postgres-rehearsal-and-checklist.md`).
- Tidak dijalankan di VM: pra-cek koneksi 5432, `pg_dumpall`, eksekusi `isolate_analysis_role.sql` pada DB `aidss` asli, rotasi password `aidss`, pengujian dukungan `!reset` pada `docker compose version` di VM, serta override Compose.

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- Tidak ada temuan baru; risiko terbuka tetap port 5432 dan superuser `aidss` yang sama dengan username.

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
1. **Gerbang eksekusi Tugas B di `10.1.200.13`:** Apakah pemilik menyetujui urutan: (a) pra-cek 5432 + `pg_dumpall`, (b) latihan di scratch DB VM, (c) menerapkan `aidss_app` + rotasi password `aidss` + override Compose menutup port 5432? Mohon kirimkan kata sandi SSH `infra@10.1.200.13` secara terpisah.
2. **Rotasi kata sandi SSH `infra` dan salinan kunci master:** Ingatkan pemilik untuk merotasi kata sandi `infra` (pernah terbuka di chat) dan memastikan backup `~/.aidss-trader-master.key` serta `pg_dumpall` disalin keluar host.

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- `deploy/trader/rollback_analysis_role.sql` mengembalikan kepemilikan objek `public` ke `aidss`; Compose override dikembalikan dengan menghapus `ports: !reset []` dan mengembalikan `AIDSS_DATABASE_URL` lama. Sudah diuji pada PostgreSQL 18 lokal (`BEGIN`/`DO`/`COMMIT` < 1 detik).

## 9. Risiko tersisa dan hal yang harus diperhatikan agen berikutnya
- Jangan menutup port 5432 sebelum `ss -tnp 'sport = :5432'` dan `pg_stat_activity` memastikan tidak ada klien sah di luar `stocks-*`.
- Verifikasi `docker compose version` di VM mendukung `ports: !reset []` sebelum menjalankan override.
