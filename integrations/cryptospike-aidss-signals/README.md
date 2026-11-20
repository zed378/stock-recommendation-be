# Sinyal crypto dari stock pick AIDSS ke klien CryptoSpike

## Offline signal builder (ADR-068, proposed)

The additional `aidss_signals.builder` tool evaluates user-defined entry and exit
conditions on local closed candles. Its standalone output is always **SHADOW**.
The owner chose **Indodax IDR**, with a separate `aidss_signals.indodax_builder`
review worker, visual editor in Trader Strategies and required review gate for
PAPER entries. See `docs/05-MODULE-SPECIFICATIONS/01-STRATEGY-ENGINE.md` for setup.
This does not connect the declarative builder to CryptoSpike publication.

```powershell
.venv/Scripts/python -m aidss_signals.builder --schema
.venv/Scripts/python -m aidss_signals.builder builder.json candles.json
# Explicitly request Kronos inference and the configured AIDSS AI gateway:
.venv/Scripts/python -m aidss_signals.builder builder.json candles.json --models
```

`--schema` prints the complete JSON contracts. `builder.json` requires `name`,
`symbol`, `exchange`, `timeframe` (`4h` or `1d`), `entry`, `exit`,
`max_data_age_seconds`, `forecast_bars`, `forecast_samples`,
`min_projected_return_pct`, and `ai_min_score`. Every number is supplied by the
owner; the tool supplies no trading thresholds. Decimal values can be strings.

Each entry/exit group has `mode` (`ALL` or `ANY`) and a nonempty `rules` array.
Each rule has a unique `name`, `left`, `operator` and `right`. Operands specify
`indicator`: `close`; `constant` with `value`; or `ema`, `rsi`, `adx`,
`volume_ratio` with `period`. Operators: `gt`, `gte`, `lt`, `lte`,
`crosses_above`, `crosses_below`. Volume ratio uses the preceding window,
excluding the current candle. Insufficient history blocks the entire group,
including ANY groups. No arbitrary expressions or Python code are evaluated.

`candles.json` contains `long` (whether a spot position exists) and `candles`
(oldest first). Each candle has UTC `timestamp` (bar open), positive `open`,
`high`, `low`, `close`, and nonnegative `volume`. Gaps, malformed OHLC,
unfinished candles and stale data block the decision.

Outputs: `HOLD`, `EXIT`, `BLOCKED`, or `ENTRY_CANDIDATE`, with rule evidence,
config/data hashes, stable candidate id and model provenance. A candidate
requires both a non-fixture Kronos projection meeting the return threshold
and AI TAKE meeting the score threshold. Model failure means BLOCKED. Exit
rules never call models. Without `--models`, an entry candidate is BLOCKED
because model evidence is unavailable; deterministic HOLD/EXIT still work.

Kronos uses a continuous crypto calendar, including weekends. Optional Kronos
dependencies and model weights must already be available to run inference.
The AI gateway uses the existing configured providers, quotas and costs.
No real inference, exchange operation or profitability is established by the
synthetic tests. Future execution requires existing sizing, Risk Engine,
promotion gates and owner-approved settings.

Metode yang Anda tetapkan, sebagai satu alur:

1. **Worker** mengambil data emiten crypto (publik, tanpa kunci): ticker 24 jam dan candle harian tertutup dari Binance spot.
2. **Parameter seperti emiten saham:** koin dinilai dengan **kriteria stock pick AIDSS yang sama** (`aidss.screener.criteria`, tidak disalin): horizon 14d dan 30d, tiap kriteria bernama dan berbobot (ADX, +DI/-DI, SMA50, SMA200, return 60 bar, dst). Skor = bobot kriteria terpenuhi dibanding maksimum horizon terpilih.
3. **Ambang 80%:** hanya koin dengan skor >= 80% yang menjadi kandidat.
4. **AI menguatkan analisa** lewat gateway LLM AIDSS yang sudah ada: AI menerima kriteria terpenuhi dan tidak, angka indikator, dan level; menjawab skor 0-100 dan TAKE/SKIP. **AI hanya bisa menolak.**
5. **Penerima sinyal mengeksekusi:** sinyal yang lolos dikirim lewat server Socket.IO ke klien CryptoSpike, yang menjalankannya di Binance Futures dan/atau Tokocrypto Spot di bawah pengaturannya sendiri (autoExecute, dry-run, filter koin, batas posisi, SL wajib).

Kode: `src/aidss_signals/` (di luar `src/aidss`, karena platform analisis tidak menempatkan order dan tes arsitekturnya menjaga itu). Tes: `tests/test_aidss_signals.py` (24 tes).

## Emiten

Daftar tetap Anda (`AIDSS_SIGNALS_SYMBOLS`) **ditambah** N koin dengan volume 24 jam terbesar (`AIDSS_SIGNALS_TOP_N`, **bawaan 5**, Anda atur 0 sampai 50). Koin yang ada di kedua daftar dihitung sekali. Stablecoin, pasangan fiat, dan token berleverage dibuang dari pilihan top-N. Syarat likuiditas `AIDSS_SIGNALS_MIN_QUOTE_VOLUME_USDT` berlaku untuk semuanya.

## Menjalankan

```bash
pip install -e ".[signals]"                       # python-socketio
cp integrations/cryptospike-aidss-signals/.env.signals.example .env   # lalu isi
python -m aidss_signals once                      # satu putaran (SHADOW kecuali PUBLISH dikonfirmasi)
python -m aidss_signals serve                     # server Socket.IO + putaran 00:05 UTC tiap hari
```

Di klien CryptoSpike: isi `SERVER_URL` dengan alamat server ini dan Client Token dengan `AIDSS_SIGNALS_CLIENT_TOKEN`. Tanpa `PUBLISH` dan konfirmasi, tidak ada yang dikirim ke siapa pun.

## Pengaman

- **Mati bawaan, SHADOW bawaan.** Tidak ada angka bawaan kecuali TOP_N (pilihan Anda). Satu angka kosong menghentikan pekerja dan menyebut apa yang kurang.
- **Gagal berarti tidak bertindak:** data koin gagal dimuat, kriteria tidak bisa dibaca (riwayat < 201 bar), AI tidak menjawab atau menjawab di luar bentuk, atau tren BTC tidak tersedia (seluruh putaran berhenti).
- **Satu keputusan per koin per penutupan harian**, tersimpan di berkas; id sinyal `aidss-<SIMBOL>-<tanggal>`.
- **AI** hanya menerima angka dan kalimat kriteria tetap dari kode; tidak ada teks luar. Biaya dan fallback diatur gateway AIDSS.
- **Catatan keputusan** `signals-decisions.jsonl` merekam tiap koin dan hasilnya, supaya nilai skor dan AI bisa diukur dari hasil nyata.
- Server menolak token salah saat handshake (perbandingan waktu-konstan); ACK dicatat.

## Simulasi end to end (lokal)

`e2e_publisher.py` menjalankan server AIDSS dan satu putaran worker (candle sintetis, AI berskrip), sementara klien CryptoSpike **asli** (database palsu, Tokocrypto dry-run) tersambung. Hasil contoh: `EXAMPLE-E2E-PYTHON.txt` dan `EXAMPLE-E2E-CLIENT.txt`: dari 4 koin, satu lolos dan sampai ke klien sebagai posisi dry-run; satu di bawah ambang, satu ditolak AI, satu AI tidak tersedia.

```bash
PYTHONPATH=src python integrations/cryptospike-aidss-signals/e2e_publisher.py      # terminal 1
# terminal 2, di server/ salinan klien (butuh simulation/ dari ../cryptospike-local-engine):
SIM_URL=http://127.0.0.1:3099 SIM_TOKEN=sim-aidss-signal-token-0001 npx tsx simulation/run-client-only.ts
```

## Yang harus Anda ketahui

1. **Stock pick adalah saringan, bukan prakiraan** (README AIDSS). Skor menghitung kondisi terpenuhi; bukan probabilitas profit. Belum ada bukti bahwa koin yang lolos 80% memberi hasil lebih baik. Mulailah dengan SHADOW dan baca catatan keputusan beberapa minggu.
2. **Kriteria dirancang untuk saham harian IDX.** Pasar crypto 24/7, lebih volatil, dan `volatility` memakai faktor tahunan 252 hari; bobot dan ambang kriteria tidak disetel untuk crypto.
3. **Level stop dan target mekanis (ATR dan kelipatan R) adalah angka Anda, bukan hasil stock pick.** Klien lalu menerapkan tangga TP/SL-nya sendiri (FeeShield Tokocrypto dapat menggeser TP1).
4. **Belum diuji:** panggilan ke penyedia AI sungguhan (tes memakai fungsi palsu), data Binance sungguhan (tes memakai transport palsu), dan eksekusi di bursa. Jangkauan `api.binance.com` dari server Anda belum diverifikasi (`AIDSS_SIGNALS_KLINES_BASE` dapat diganti).
5. Temuan klien: sinyal berulang dengan id sama membuka posisi ganda di jalur Tokocrypto, dan klien tidak tersambung lagi bila server sengaja memutusnya (lihat README `cryptospike-local-engine`). Server ini tidak memutus klien dan id sinyal stabil per hari, tetapi pengaman di klien tetap perlu.
