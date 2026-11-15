# Handoff F: Hardening host PostgreSQL 16 (`10.1.200.13`, `aidss_app`, tutup port 5432)
Tanggal/jam: 2026-11-15 10:39 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: 38d0206        Status: BERHENTI DI GERBANG

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Belum ada perubahan pada VM `10.1.200.13` karena menunggu kata sandi SSH `infra@10.1.200.13` dan izin pemilik pada gerbang. Seluruh skrip hardening (`deploy/trader/bootstrap.sql`, `deploy/trader/isolate_analysis_role.sql`, `deploy/trader/rollback_analysis_role.sql`, `deploy/trader/docker-compose.trader.yml`) sudah siap dan sebelumnya lulus latihan pada PostgreSQL 18 lokal (`7/7 -m postgres` + rollback bersih). Tahap 3 mewajibkan pengulangan latihan pada DB scratch **PostgreSQL 16** di VM (`pgvector/pgvector:pg16`), pre-check koneksi aktif port 5432, dan verifikasi dukungan `ports: !reset []` pada `docker compose version` sebelum meminta gerbang pemilik untuk perubahan produksi.

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- Tidak ada commit kode baru pada Tugas F; hanya handoff gerbang ini (`MEMORY/handoffs/2026-11-15-F-host-hardening-pg16.md`, `MEMORY/handoffs/INDEX.md`).

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- Latihan lokal PG 18 (referensi dari Tahap 2 `7a84db8`): `7 passed, 5 deselected in 0.77s`.
- Bukti PG 16 VM (`stocks-postgres-1`, `pgvector/pgvector:pg16`): belum dijalankan (menunggu kata sandi SSH).

## 4. Perintah verifikasi untuk agen utama (maksimal 8, murah, read-only, dengan keluaran yang DIHARAPKAN)
- (Akan diisi setelah langkah 1–2 PG 16 VM dan langkah 3 produksi selesai dijalankan.)

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi `[agen kedua]` di Tahap 2: seluruh SQL di PostgreSQL 18 lokal.
- Belum dijalankan di VM `[agen kedua]` (menunggu kata sandi SSH):
  1. Latihan DB scratch `aidss_role_rehearsal` di `stocks-postgres-1` (**PostgreSQL 16**): `bootstrap.sql`, `isolate_analysis_role.sql`, `0001..0008`, `pytest -m postgres`, `rollback_analysis_role.sql`, lalu `DROP DATABASE`.
  2. Pre-check `pg_stat_activity WHERE client_addr IS NOT NULL`, `docker compose version`, dan validasi `ports: !reset []`.
- Belum dijalankan di VM `[pemilik]` (Gerbang Pemilik setelah langkah 1–2 lulus):
  - `pg_dumpall`, terapkan `isolate_analysis_role.sql` di `aidss`, buat/rotasi sandi `aidss_app` & `aidss`, tutup port 5432, uji login UI + worker + Trader `HALTED` + cek port 5432 dari luar, serta **ukur waktu aktual** rollback jika diuji.

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- Risiko terbuka tetap sama: port `5432` VM masih ter-publish ke `0.0.0.0` dan `api`/`worker` masih memakai superuser `aidss`.

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
1. Berikan kata sandi SSH `infra@10.1.200.13` (di terminal/chat aman, jangan disimpan ke file/commit; rotasi kata sandi lama yang pernah terbuka).
2. Setujui eksekusi langkah produksi setelah hasil latihan PG 16 VM dan pre-check dilaporkan.

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- `deploy/trader/rollback_analysis_role.sql` + kembalikan `AIDSS_APP_DATABASE_URL` ke superuser URL + `docker compose up -d --no-build`. Sudah diuji di PG 18 lokal; **waktu pemulihan di VM belum diukur** (akan diukur saat gerbang disetujui).

## 9. Risiko tersisa dan hal yang harus diperhatikan agen berikutnya
- Jangan meneruskan hasil PG 18 lokal sebagai bukti PG 16 VM; kedua versi harus dibedakan secara eksplisit.
