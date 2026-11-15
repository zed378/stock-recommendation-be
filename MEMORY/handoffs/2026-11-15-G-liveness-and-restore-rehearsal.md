# Handoff G: Monitor liveness luar-proses & latihan restore VM (`10.1.200.13`)
Tanggal/jam: 2026-11-15 10:39 WIB        Agen: Antigravity (agen kedua)        HEAD saat selesai: 38d0206        Status: BERHENTI DI GERBANG

## 1. Ringkasan satu paragraf (apa yang berubah, apa dampaknya)
Menunggu kata sandi SSH `infra@10.1.200.13` untuk menjalankan `deploy/trader/rehearse_restore.sh` pada DB scratch di **PostgreSQL 16 VM** dengan **dump penuh** (mencatat detik aktual dan jumlah baris setiap tabel). Perintah instalasi cron/systemd `deploy/trader/check_liveness.py` dan pengisian file token Telegram root-only sudah disiapkan sesuai `docs/10-OPERATIONS/06-RUNBOOKS.md` R14 tanpa dipasang di host sebelum pemilik menyetujui dan mengisi tokennya sendiri.

## 2. Commit (sha, pesan, daftar file) dan file yang SENGAJA tidak disentuh
- Tidak ada kode yang diubah; hanya handoff gerbang ini (`MEMORY/handoffs/2026-11-15-G-liveness-and-restore-rehearsal.md`, `MEMORY/handoffs/INDEX.md`).

## 3. Bukti (tempel keluaran asli, bukan ringkasan)
- Referensi lokal PG 18 (`7a84db8`): `Restore rehearsal completed cleanly in 3s` (30 tabel, hak akses `trader_rw`/`trader_monitor` terverifikasi).
- Eksekusi VM PG 16 (`sh deploy/trader/rehearse_restore.sh stocks-postgres-1 aidss aidss`): belum dijalankan (menunggu kata sandi SSH).

## 4. Perintah yang disiapkan untuk pemilik (R14, JANGAN dijalankan sebelum Trader sengaja aktif & pemilik setuju)
1. Sebagai `root` di `10.1.200.13`, buat file token Telegram mode `0600` (isi oleh pemilik di terminal sendiri):
   ```sh
   install -m 0600 /dev/null /root/.aidss-monitor-telegram.env
   cat <<'EOF' > /root/.aidss-monitor-telegram.env
   TELEGRAM_BOT_TOKEN=<token-bot-anda>
   TELEGRAM_CHAT_ID=<chat-id-anda>
   EOF
   ```
2. Set sandi `trader_monitor` di PostgreSQL (`ALTER ROLE trader_monitor PASSWORD '...';`) dan simpan `AIDSS_MONITOR_DATABASE_URL` di `/root/.aidss-monitor-db.env` (mode `0600`).
3. Uji sekali secara manual:
   ```sh
   set -a; . /root/.aidss-monitor-db.env; set +a
   python3 /path/to/deploy/trader/check_liveness.py \
     --token-file /root/.aidss-monitor-telegram.env \
     --state-file /var/run/aidss-trader-liveness.json \
     --max-age-s 15 --cooldown-s 300
   ```
4. Jadwalkan setiap menit di `crontab` root (hanya setelah Trader sengaja dijalankan; saat Trader `HALTED` tanpa lease aktif atau dimatikan, monitor akan mengirim peringatan).

## 5. Yang DIVERIFIKASI (dengan rujukan ke bukti di bagian 3) vs yang DITULIS TAPI TIDAK DIJALANKAN
- Diverifikasi `[agen kedua]` di Tahap 2: `check_liveness.py` lulus Acceptance A13 terhadap fake Telegram server; `rehearse_restore.sh` lulus pada PG 18 lokal (`3s`).
- Belum dijalankan `[agen kedua]`: `rehearse_restore.sh` di VM PG 16.
- Belum dijalankan `[pemilik]`: instalasi cron/systemd & pengisian `/root/.aidss-monitor-telegram.env`.

## 6. Temuan baru (cacat, risiko, penyimpangan dari spesifikasi) dan tindakannya
- Tidak ada temuan baru; selama cron monitor belum terpasang, `T6-04` operasional host tetap menunggu persetujuan pemilik.

## 7. Keputusan yang menunggu pemilik (pertanyaan jelas, pilihan, rekomendasi)
1. Berikan kata sandi SSH `infra@10.1.200.13` untuk menjalankan `rehearse_restore.sh` pada DB scratch VM.
2. Konfirmasi kapan pemilik ingin memasang cron/systemd `check_liveness.py` dan mengisi `/root/.aidss-monitor-telegram.env`.

## 8. Rollback: cara membatalkan perubahan ini, sudah diuji? waktu pemulihan
- `rehearse_restore.sh` men-drop DB scratch-nya sendiri; hapus baris crontab + `/root/.aidss-monitor-*.env` jika monitor perlu dinonaktifkan (< 1 menit, estimasi).

## 9. Risiko tersisa dan hal yang harus diperhatikan agen berikutnya
- Jangan menulis token Telegram atau kata sandi ke file repo, log, atau argumen perintah.
