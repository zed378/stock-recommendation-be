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
| `files/server/src/services/local-engine.service.ts` | Penyambung ke `handleIncomingSignal` milik klien |
| `index.ts.patch` | Empat baris di `server/src/index.ts` untuk menyalakannya |
| `files/.env.local-engine.example` | Variabel yang dibutuhkan |
| `files/server/tests/local-engine-*.test.ts` | 32 tes |

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
