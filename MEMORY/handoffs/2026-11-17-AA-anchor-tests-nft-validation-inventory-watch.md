# Handoff AA: Portabilitas Tes Anchor, Validasi `nft -c`, Inventaris Klien, Watcher Anchor & Sinkronisasi Dokumen
Tanggal/jam: 2026-11-18 10:21 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: (lihat `git log --oneline origin/main..HEAD`; commit handoff ini ditambahkan setelah `5a36b57`)        Status: SELESAI

## 1. Ringkasan satu paragraf
Seluruh tugas Tahap 12 (`A` sampai `F`) selesai tanpa mengakses host `10.1.200.13`, tanpa membangun/mendorong image produksi, dan tanpa mengubah `src/`, `frontend/`, `tests/test_architecture_constraints.py`, maupun `docker-compose.yml`. Pada Tugas A (`19e9373`), `test_aidss_anchor_script.py` memilih Git Bash dan `usr/bin` Git secara eksplisit agar lulus tanpa mengubah PATH eksternal. Pada Tugas B (`220035c`), `validate-draft.sh` memvalidasi draf firewall tahap 1 `deploy/host/firewall/docker-user.nft` secara offline di kontainer `aidss-nft-validator:alpine3.22.2` (`nftables v1.1.3`, kernel `6.6.87.2-microsoft-standard-WSL2`, exit `0`, tanpa memuat aturan). Pada Tugas C (`f81f6d8`), skrip hanya-baca `inventory-clients.sh` dan bagian `"Stage 2 inventory"` pada dokumen 08 disiapkan untuk inventaris klien per port dan identifikasi `java` 6547 tanpa `cmdline`/`environ`. Pada Tugas D (`63713f7`), watcher `aidss-anchor-watch.sh`, draf cron `aidss-anchor-watch.cron` (LF), dan runbook `R16` disiapkan tanpa default ambang tersembunyi dan tanpa pengirim token bawaan. Pada Tugas E (`5a36b57`) & F, dokumen migrasi (`09-MIGRATION-RUNBOOK.md`), `PROGRESS.md`, `BACKLOG.md`, `trader-document-catalog.md`, `CHANGELOG.md`, serta tinjauan keamanan independen `import_owner_profile.py` dan skrip terkait diselesaikan; `ruff` bersih dan `564 passed, 15 deselected`.

## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
Daftar commit yang belum di-push sebelum commit handoff (`git log --oneline origin/main..HEAD`):
- `5a36b57` — `docs(task-e): sync migration runbook, backlog, progress, and Stage-12 record`: `docs/10-OPERATIONS/09-MIGRATION-RUNBOOK.md`, `TASKS/PROGRESS.md`, `TASKS/BACKLOG.md`, `trader-document-catalog.md`, `MEMORY/CHANGELOG.md`, `MEMORY/records/2026-11-18-stage-12-a-to-f.md`, `MEMORY/MEMORY-INDEX.md`.
- `63713f7` — `feat(task-d): add anchor freshness watcher, draft cron, and R16 runbook`: `deploy/trader/aidss-anchor-watch.sh`, `deploy/trader/aidss-anchor-watch.cron`, `tests/trader/test_aidss_anchor_watch.py`, `docs/10-OPERATIONS/06-RUNBOOKS.md`.
- `f81f6d8` — `feat(task-c): add read-only host client inventory script for Stage-2 firewall`: `deploy/host/firewall/inventory-clients.sh`, `tests/trader/test_inventory_clients.py`, `docs/10-OPERATIONS/08-HOST-FIREWALL-PLAN.md`.
- `220035c` — `feat(task-b): validate unapplied Stage-1 nftables draft offline in container`: `deploy/host/firewall/validate-draft.sh`, `tests/trader/test_host_firewall_drafts.py`.
- `19e9373` — `test(task-a): make aidss-anchor tests independent of caller PATH on Windows`: `tests/trader/test_aidss_anchor_script.py`.
(Sebelumnya di branch: `8d25b69`, `588acd7`, `3852466`).

**Sengaja tidak disentuh:** `deploy/trader/aidss-anchor.sh`, `deploy/host/firewall/docker-user.nft` (sudah lolos `nft -c` apa adanya), `deploy/trader/import_owner_profile.py`, `tests/test_architecture_constraints.py`, `src/`, `frontend/`, `docker-compose.yml`, `Dockerfile*`, `alembic*`, `CLAUDE.md` (fakta sudah mutakhir), serta host VM `10.1.200.13`.

## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti
- **[agen kedua] `validate-draft.sh` terhadap `deploy/host/firewall/docker-user.nft`:**
  ```text
  nftables v1.1.3 (Commodore Bullmoose #4)
  6.6.87.2-microsoft-standard-WSL2
  ```
  (Exit code `0`, kontainer `--rm --pull never --cap-drop ALL --cap-add NET_ADMIN --security-opt no-new-privileges --network none --read-only`).
- **[agen kedua] Pemeriksaan LF pada seluruh `*.sh`, `*.cron`, `*.nft`:**
  ```text
  CR_FILES: []
  ```
- **[agen kedua] Lint (`ruff check src tests alembic alembic_trader deploy`):**
  ```text
  All checks passed!
  ```
- **[agen kedua] Suite pytest penuh (`python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`, tanpa mengubah PATH shell):**
  ```text
  564 passed, 15 deselected in 186.85s (0:03:06)
  ```
- **[agen utama / pemilik] Belum dijalankan:** eksekusi `inventory-clients.sh` pada VM `10.1.200.13`, penerapan firewall tahap 1 maupun tahap 2 di VM, pemasangan `aidss-anchor-watch.cron` di VM, `backup_offhost.sh` ke VM nyata, `-m postgres`, dan `T2-07`/`T5-06`.

## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, keluaran yang DIHARAPKAN)
1. `git log --oneline origin/main..HEAD` -> menampilkan `8d25b69`, `19e9373`, `220035c`, `f81f6d8`, `63713f7`, `5a36b57`, dan commit handoff ini.
2. `.venv\Scripts\ruff.exe check src tests alembic alembic_trader deploy` -> `All checks passed!`.
3. `.venv\Scripts\python.exe -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` -> `564 passed, 15 deselected` (tanpa mengubah `PATH` shell).
4. `.venv\Scripts\python.exe -c "from pathlib import Path; print([str(p) for p in Path('.').rglob('*') if p.suffix in {'.sh','.cron','.nft'} and b'\r' in p.read_bytes()])"` -> `[]`.
5. `sh deploy/host/firewall/validate-draft.sh` (jika `aidss-nft-validator:alpine3.22.2` tersedia di Docker lokal) -> `nftables v1.1.3 ...` + exit `0`.

## 5. DIVERIFIKASI vs DITULIS TAPI TIDAK DIJALANKAN
- **DIVERIFIKASI (dengan bukti):** portabilitas tes `test_aidss_anchor_script.py` tanpa edit PATH eksternal (`564 passed, 15 deselected`), validasi sintaks `nft -c -f` draf tahap 1 di kontainer terisolasi (`exit 0`), tes stub `inventory-clients.sh` & `aidss-anchor-watch.sh`, LF bersih, dan `ruff` bersih.
- **DITULIS TAPI TIDAK DIJALANKAN (terhadap VM):** eksekusi `inventory-clients.sh` di `10.1.200.13` dan pemasangan `aidss-anchor-watch.cron`.

## 6. Temuan baru dan tindakannya
1. **`deploy/trader/aidss-anchor-watch.cron` sempat berakhiran CRLF (`\r\n`):** terdeteksi saat pemeriksaan byte `\r` sebelum commit dan sudah dikonversi ke LF (`CR_FILES: []`).
2. **Tinjauan keamanan `import_owner_profile.py` (Tugas F):** tidak ada kebocoran password/token/DB URL di argumen, log, atau `_reason()`. Catatan minor non-kritis: `main()` baris `329` (`json.loads(args.profile.read_text(...))`) melempar traceback mentah tanpa secret bila berkas profil tidak ada atau JSON rusak.
3. **Firewall tahap 1 belum diterapkan:** `docker-user.nft` lolos `nft -c -f` secara sintaks, namun dukungan `ct original proto-dst` pada kernel host Ubuntu `26.04` (`7.0.0-38`) tetap perlu diuji dengan pengaman rollback berjangka waktu saat diterapkan oleh agen utama.

## 7. Keputusan yang menunggu pemilik
1. **Ambang kesegaran anchor (`AIDSS_ANCHOR_MAX_AGE_S` untuk `aidss-anchor-watch.sh`):**
   - A) `5400` detik (90 menit — toleransi 1 kali cron per jam terlewat/terlambat).
   - B) `7200` detik (2 jam — toleransi lebih longgar untuk pemeliharaan singkat).
   - C) Nilai lain sesuai pilihan pemilik.
2. **Kanal notifikasi pemantau anchor (`AIDSS_ANCHOR_ALERT_CMD`):**
   - A) Log lokal + syslog (`user.err` / `user.crit`) saja untuk saat ini.
   - B) Hook ke webhook lokal / HTTP alert internal.
   - C) Hook ke Telegram (memerlukan token & chat ID terpisah seperti `check_liveness.py`).
3. **Frekuensi & retensi backup luar-host (`deploy/trader/backup_offhost.sh`, worksheet L1):**
   - A) Mingguan + sebelum setiap rilis/migrasi, simpan 4 salinan terbaru di workstation/disk eksternal.
   - B) Harian (manual/terjadwal di workstation), simpan 7 harian + 4 mingguan.
   - C) Hanya sebelum setiap perubahan produksi/rilis.
4. **Firewall Tahap 2 (proyek non-AIDSS & `java` 6547):** menunggu hasil `inventory-clients.sh` dari VM untuk keputusan per port.
5. **Keputusan Trading/Operasional yang tetap terbuka:** `ADR-052` (ditunda hingga data paper), `OQ-5/8/9/11/12/16`, `T2-07`, dan `T5-06`.

## 8. Rollback: cara, diuji atau belum, waktu yang DIUKUR (perkiraan berlabel)
- Seluruh perubahan Tahap 12 hanya berada di repositori (skrip offline/draf/tes/dokumen), tidak ada perubahan pada VM `10.1.200.13` maupun image produksi. Rollback repositori: `git revert 19e9373..5a36b57` (perkiraan `< 10 detik`, belum dijalankan).

## 9. Risiko tersisa
1. **Host `10.1.200.13` belum memiliki aturan firewall aktif** (`docker-user.nft` baru lolos `nft -c` lokal, belum diterapkan).
2. **Belum ada salinan backup luar-host nyata** di workstation pemilik sampai `backup_offhost.sh` dijalankan terhadap VM.
3. **Cron `aidss-anchor` sudah terpasang, namun eksekusi pertamanya dan watcher `aidss-anchor-watch` belum terkonfirmasi/terpasang** (menunggu pilihan ambang & kanal notifikasi).
4. **Identitas `java` pada port `6547` dan daftar klien proyek non-AIDSS masih belum diketahui** sampai `inventory-clients.sh` dijalankan di VM.
5. **Tes pra-ada `tests/test_output_language.py::test_translation_covers_every_prose_field` masih gagal** (di luar cakupan Trader/Tahap 12).
