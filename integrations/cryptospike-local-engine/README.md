# Mesin strategi lokal untuk cryptospike-client

Tambahan untuk [bozid95/cryptospike-client](https://github.com/bozid95/cryptospike-client) (diperiksa pada commit `c4a1648`). Klien itu **sudah** mengeksekusi sinyal ke Binance Futures dan Tokocrypto Spot, tetapi seluruh sinyalnya datang dari server luar. Paket ini menambahkan sumber sinyal sendiri, memakai eksekutor, pengaman, TP/SL, dan filter yang sudah ada. Repo cryptospike **tidak diubah** di sini; semuanya berupa berkas yang Anda terapkan sendiri.

## Isi

| Berkas | Fungsi |
|---|---|
| `files/server/src/engine/indicators.ts` | EMA, ATR, ADX, +DI/-DI; rumus sama dengan AIDSS Trader (dites paritas terhadap Python) |
| `files/server/src/engine/strategy.ts` | Aturan masuk: EMA cepat > lambat, ADX > ambang, +DI - -DI > margin (varian D2). Stop = close - kelipatan ATR, TP1..3 = kelipatan R |
| `files/server/src/engine/klines.ts` | Candle 4 jam tertutup dari endpoint publik Binance (tanpa kunci, tanpa tanda tangan) |
| `files/server/src/engine/config.ts` | Konfigurasi dari environment; mati bawaan, tanpa angka bawaan |
| `files/server/src/engine/local-engine.ts` | Putaran per simbol: satu keputusan per candle tertutup, kegagalan satu simbol tidak menghentikan yang lain |
| `files/server/src/engine/ai-assessor.ts` | Penilai AI (opsional): dossier angka, prompt, validasi jawaban ketat, satu panggilan Anthropic Messages API |
| `files/server/src/services/local-engine.service.ts` | Penyambung ke `handleIncomingSignal` milik klien |
| `index.ts.patch` | Empat baris di `server/src/index.ts` untuk menyalakannya |
| `files/.env.local-engine.example` | Variabel yang dibutuhkan |
| `files/server/tests/local-engine-*.test.ts` | 47 tes |
| `simulation/` | Simulasi lokal dengan kode klien ASLI: penangkapan sinyal luar dan alur AI penuh (lihat bagian di bawah) |

## Menerapkan

```bash
./apply.sh /path/ke/cryptospike-client      # menambah berkas dan mengubah satu berkas; tidak menyalakan apa pun
cd /path/ke/cryptospike-client/server
npx tsx --test tests/local-engine-*.test.ts
```

Lalu salin isi `.env.local-engine.example` ke `.env`, isi **semua** angka sendiri, dan nyalakan.

## Cara kerja dan pengaman

- **Mati secara bawaan.** `LOCAL_ENGINE_ENABLED=true` diperlukan. Satu angka strategi yang kosong membuat mesin menolak jalan dan menyebut yang kurang.
- **Mode bawaan SHADOW:** sinyal hanya dicatat di log. `EXECUTE` butuh juga `LOCAL_ENGINE_CONFIRM_EXECUTE=yes`; tanpa itu mesin turun ke SHADOW dan mengatakannya.
- Di EXECUTE, sinyal masuk ke `handleIncomingSignal`, jadi semua pengaman klien tetap berlaku: `autoExecute` per bursa, dry-run Tokocrypto, filter koin, batas posisi, SL wajib, dan dedupe id sinyal (`local-<simbol>-<waktu buka candle>`; aman terhadap restart).
- Hanya candle yang sudah tutup yang dipakai. Data candle yang rusak ditolak seluruhnya.
- Arah BTC (EMA cepat vs lambat) dikirim sebagai `btcTrendBias`, supaya filter "blokir LONG saat BTC bearish" milik klien bekerja. Bila data BTC gagal diambil, tidak ada sinyal sama sekali.
- Hanya **LONG**. Tokocrypto Spot memang hanya beli; short belum diuji.

## AI sebagai penilai (opsional)

Aturan tetap menemukan kandidat dan menentukan entry, stop, dan target. AI hanya menerima ringkasan angka kandidat (30 penutupan ternormalisasi, ADX, DI, ATR persen, jarak stop, perubahan 24 jam dan 7 hari, volume relatif, arah BTC) dan mengembalikan satu objek JSON: `score` 0-100, `verdict` TAKE/SKIP, `confidence`, `reasons`, `risks`.

- **AI hanya bisa menolak.** Kandidat jadi sinyal bila verdict TAKE dan skor >= `LOCAL_ENGINE_AI_MIN_SCORE`. Harga, stop, dan target tetap persis dari aturan (dites).
- **Gagal berarti tidak bertindak.** Error jaringan, status HTTP bukan 2xx, timeout 20 detik, jawaban bukan JSON, skor di luar 0-100, atau bentuk yang salah: kandidat dibuang dan dicatat `AI_UNAVAILABLE`. Candle itu tidak diulang.
- **Tanpa teks luar.** Prompt hanya berisi angka dan simbol yang sudah divalidasi, jadi tidak ada berita atau nama token bebas yang bisa menyisipkan instruksi. Kunci API dan data akun tidak ikut terkirim (dites).
- **Biaya terkendali.** AI hanya dipanggil untuk kandidat yang lolos aturan, dengan batas per putaran.
- **Catatan keputusan** `data/local-engine-decisions.jsonl`: tiap kandidat dengan hasilnya (SIGNAL, AI_SKIP, AI_BELOW_MIN, AI_UNAVAILABLE, AI_BUDGET) dan penilaian AI. Gunakan ini untuk MENGUKUR apakah skor AI memisahkan hasil yang baik dari yang buruk sebelum memberinya bobot. **Tidak ada bukti bahwa penilaian AI menambah keunggulan.** Mulailah di SHADOW dan bandingkan hasil kandidat yang diloloskan dan yang ditolak.

## Simulasi dengan kode klien asli

Dua skrip di `simulation/` memuat kode asli `socket.service.ts` dan eksekutor Tokocrypto klien, dengan server sinyal dan database palsu. Tidak ada koneksi keluar, kunci, atau bursa. Salin ke `server/simulation/` di salinan klien Anda dan pasang `npm i --no-save socket.io`:

```bash
npx tsx simulation/run-signal-capture.ts   # cara klien menangkap sinyal dari luar (hasil contoh: EXAMPLE-OUTPUT.txt)
npx tsx simulation/run-ai-pipeline.ts      # aturan -> penilai AI -> sinyal -> klien (EXAMPLE-AI-PIPELINE-OUTPUT.txt)
```

Kontrak server sinyal yang ditiru (`new_signal`, `signal_ack`, auth token) disimpulkan dari kode klien, bukan dari dokumen server aslinya.

### Temuan dari simulasi pada klien (tidak diubah)

1. **Sinyal yang sama dikirim ulang membuat pembelian kedua di jalur Tokocrypto.** Dedupe id sinyal hanya ada di eksekutor Binance. Replay setelah reconnect akan membuka posisi ganda, hanya dibatasi `maxOpenPositions`. Mesin lokal ini memakai id yang sama per candle, tetapi pengaman di Tokocrypto tetap perlu ditambah di klien.
2. **Server yang sengaja memutus klien (`io server disconnect`) tidak membuat klien tersambung lagi** (perilaku bawaan socket.io-client); hanya putusnya transport yang tersambung otomatis. Klien bisa diam tanpa menerima sinyal sampai di-restart.
3. ACK `RESULT` dikirim juga untuk sinyal yang diabaikan, dan jalur Binance melaporkan `DISABLED` bila tanpa kunci.
4. FeeShield Tokocrypto menggeser target TP1 yang terlalu rapat menjadi +3%, jadi target R dari aturan bisa berbeda dari yang sungguh dipasang di spot.

## Yang harus Anda ketahui sebelum memakai uang sungguhan

1. **Keluarnya berbeda dari yang kami uji.** Di AIDSS aturan keluar adalah "filter tren gagal". Di klien ini posisi dikelola tangga TP 50/30/20, SL, break-even, dan trailing. **Hasil backtest AIDSS tidak berlaku untuk konfigurasi ini.**
2. **Aturan masuk ini belum terbukti.** Di AIDSS varian D2 mencatat -0,57% (jumlah return per pasangan, 16 transaksi, sekitar 50 hari, pasar turun, pasangan IDR). Itu belum profitable dan terlalu sedikit untuk disimpulkan. Angka di `.env.local-engine.example` hanya bentuk contoh, bukan hasil penyetelan.
3. **Belum diuji ke bursa.** Tes memakai fungsi palsu untuk jaringan dan eksekutor. Jalur `handleIncomingSignal` ke Binance/Tokocrypto tidak dijalankan karena butuh database dan kunci. Urutan yang disarankan: SHADOW dulu beberapa hari, lalu Binance Testnet, lalu Tokocrypto dry-run, baru nominal sangat kecil.
4. Sinyal lokal tidak membawa `score`; biarkan `minScore` 0 atau semua sinyalnya ditolak.
5. `api.binance.com` mungkin diblokir dari jaringan tertentu (klien ini punya resolver DoH karena alasan serupa). Ganti lewat `LOCAL_ENGINE_KLINES_BASE` bila perlu; belum diverifikasi dari VPS Anda.
6. Strategi tetap harus dibatasi risikonya lewat pengaturan klien (persentase risiko, maks posisi). Mesin ini tidak menambah batas kerugian harian atau kill switch global; klien juga tidak punya.

## Temuan lain pada repo cryptospike-client (tidak diubah)

- Kunci API dan secret bursa disimpan polos di SQLite, dan `GET /api/config` mengembalikan secret ke frontend.
- CORS mengizinkan semua origin (`callback(null, true)` di semua cabang) bersama `credentials: true`.
- `package-lock.json` tidak sinkron dengan `package.json` (`npm ci` gagal: `@types/ws` hilang dari lock).
- Klien mengirim ACK status eksekusi ke server luar (`SIGNAL_ACK_ENABLED=false` mematikannya).
