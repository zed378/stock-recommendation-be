# Handoff F: Hardening host PostgreSQL 16 (`10.1.200.13`, `aidss_app`, tutup port 5432)
Tanggal/jam: 2026-11-15 (diperbarui setelah latihan)        Agen: Antigravity (agen kedua) menyiapkan skrip; agen utama menjalankan latihan        HEAD saat selesai: lihat `git log` (commit yang menambahkan record latihan)        Status: LATIHAN PG 16 SELESAI; EKSEKUSI PRODUKSI BERHENTI DI GERBANG

## 1. Ringkasan satu paragraf
Skrip hardening (`bootstrap.sql`, `isolate_analysis_role.sql`, `rollback_analysis_role.sql`, `docker-compose.trader.yml`) sudah dilatih di PostgreSQL 16.16 pada VM, pada **klon** penuh database `aidss` (337 MB), bukan pada database aslinya. Hasilnya lulus dan cluster kembali persis seperti semula. Belum ada perubahan pada database `aidss`, role, port, maupun compose di VM. Langkah produksi menunggu persetujuan eksplisit pemilik per langkah.

## 2. Commit dan file yang sengaja tidak disentuh
- Hanya dokumen: record `MEMORY/records/2026-11-15-pg16-host-hardening-rehearsal.md`, handoff ini, indeks, `TASKS/PROGRESS.md`.
- Skrip latihan (`rehearse_pg16.py`) ada di scratchpad sesi, di luar repo.

## 3. Bukti, dan siapa yang menjalankan
Semua `[agen utama]`, lewat SSH dengan `HOST_PW` dari environment pemilik. Rincian dan angka lengkap: record di atas.
- Klon: 11,4 s, 47 tabel `public` + 30 `trading`, sama dengan sumber.
- `isolate_analysis_role.sql`: 1,1 s; 47/47 tabel milik `aidss_app`; bukan superuser/createdb/createrole/bypassrls.
- `alembic upgrade head` dengan image `aidss-api:e7b3da3` sebagai `aidss_app`: exit 0.
- `pytest -m postgres test_privileges_postgres.py`: 6 lulus, 0 skip.
- SQL langsung `aidss_app`: tulis di `public` ok; `SELECT trading.audit_log`, `SELECT trading.credential`, `CREATE` di `trading` ditolak.
- `rollback_analysis_role.sql`: 1,2 s; 0 tabel bukan milik `aidss`.
- Pembersihan: database sementara dan role `aidss_app` dihapus; daftar role/database identik dengan sebelum.
- Pra-cek: Compose v5.6.0 (mendukung `ports: !reset []`); semua klien port 5432 ada di jaringan Docker (172.22.0.x), tidak ada dari luar; disk 150 GB bebas.

## 4. Perintah verifikasi untuk agen utama (read-only)
1. `ssh infra@10.1.200.13 "docker exec stocks-postgres-1 psql -U aidss -d aidss -Atc \"select rolname from pg_roles where rolname !~ '^pg_' order by 1\""` → `aidss, trader_monitor, trader_owner, trader_rw` (tanpa `aidss_app`).
2. `docker exec stocks-postgres-1 psql -U aidss -d postgres -Atc "select datname from pg_database order by 1"` → `aidss, postgres, template0, template1`.

## 5. DIVERIFIKASI vs DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi: seluruh langkah latihan di atas, pada PG 16 VM (selisih dari PG 18 lokal: tidak ada; hasilnya sama).
- Tidak dijalankan: semua langkah produksi (`pg_dumpall`, buat role `aidss_app` di `aidss`, rotasi sandi `aidss`, `AIDSS_APP_DATABASE_URL`, tutup 5432, `up -d`) dan verifikasi pasca-ubah.

## 6. Temuan dan selisih lingkungan latihan vs produksi
- Klon tidak punya `GRANT CREATE ON DATABASE ... TO trader_owner` (tingkat database tidak ikut dump), sehingga `alembic` Trader gagal di klon dengan "permission denied for database". Artefak latihan; di `aidss` izin itu sudah ada.
- API/worker nyata belum dijalankan terhadap klon sebagai `aidss_app`; hanya alembic dan SQL langsung. Jalur seperti pgvector oleh worker tidak tercakup.
- `docker-compose.yml` di VM menulis `postgresql+psycopg://aidss:aidss@postgres:5432/aidss` langsung; langkah produksi harus menimpanya lewat override, bukan hanya menambah variabel di `~/.aidss-trader.env`.
- Role `aidss_app` bersifat satu cluster; latihan membuat dan menghapusnya (terverifikasi).

## 7. Keputusan yang menunggu pemilik
1. Setujui eksekusi produksi, per langkah: `pg_dumpall` baru; buat `aidss_app` + sandi; rotasi sandi `aidss`; override URL di compose; tutup 5432; `up -d --no-build`. Rekomendasi: lakukan di jam sepi, dengan dump keluar host lebih dulu (ADR-040).
2. Rotasi kata sandi SSH `infra` (pernah terbuka di chat) dan hapus `HOST_PW` dari environment User.

## 8. Rollback
- Sisi database: `rollback_analysis_role.sql` **teruji, 1,2 s** pada klon. Lalu kembalikan URL ke superuser dan `docker compose up -d --no-build`: **belum diukur** end-to-end.

## 9. Risiko tersisa
- Sampai langkah produksi jalan: port 5432 terbuka ke `0.0.0.0` dengan superuser `aidss` bersandi sama dengan nama pengguna; dump hanya di disk yang sama.
