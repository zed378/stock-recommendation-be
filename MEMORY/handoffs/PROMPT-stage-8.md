# Prompt tahap 8 untuk agen sebelah: ukur ulang overflow dan tinggi kontrol di produksi (`2fc6c0b`)

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = origin/main = 82b55da`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Satu tugas (Q), read-only terhadap produksi. Tidak ada akses SSH, build, push image, atau deploy untukmu.

## 0. Baca dulu
`CLAUDE.md`, `AGENTS.md`, handoff P, `MEMORY/records/2026-11-15-phone-tap-targets.md`, `MEMORY/records/2026-11-15-first-deploy.md` (bagian redeploy `eba243c` dan `2fc6c0b`),
`frontend/src/components/primitives.tsx`, `frontend/src/components/TabStrip.tsx`.

## 1. Keadaan (fakta)
- Produksi `https://aidss.zedth.my.id` menjalankan `aidss-frontend:2fc6c0b` (chunk utama `index-HvlgnJp2.js`; chunk `primitives-CpTPs67F.js`, `AssetDetail-DsVQA76H.js`, `StockPicks-CyBa0p3U.js`,
  `Monitoring-CFlTyQIG.js`, `TabStrip-qKVUDWzp.js`). Sejak `dd2d776` ada tiga perubahan layout, **semuanya baru terkonfirmasi lewat isi chunk, belum diukur di browser produksi**:
  1. (`eba243c`) baris tombol analisis di tab Analisis `/assets/:ticker` membungkus (`flex-wrap`): di tugas P ia meluap 17 px pada 320 px dalam `id`.
  2. (`eba243c`) grid kartu `/picks` memakai `grid-cols-1` di bawah `lg`: di tugas P ia meluap 5 px pada 375 px.
  3. (`2fc6c0b`) tinggi minimal 44 px di bawah `sm` (`max-sm:min-h-11`) pada kedua ukuran `Button`, `inputClass`, `inlineControlClass`, selektor timeframe (`1d/1w/1M`) di `/assets/:ticker`, selektor horizon (`1d/7d/14d/30d`) di `/picks`,
     dan dua tab Monitoring yang kini memakai `TabStrip`. Dari `sm` ke atas tinggi tidak berubah.
- Pengukuran lokal agen utama (Playwright pada API mock, lebar 375): kontrol di `<main>` yang tingginya di bawah 44 px turun dari 5, 7, 10 menjadi 1, 1, 2 pada `/assets/BBCA`, `/monitoring`, `/picks`; `/journal` dan `/portfolio` 0.
  Sisanya: tautan atribusi TradingView (35x19, wajib dari pustaka grafik) dan checkbox bawaan 13 px. Di 1280 px tinggi tidak berubah (timeframe 33x24, tombol 38).
- Trader `HALTED`, tanpa URL exchange, tanpa kunci. Tidak pernah ada panggilan ke Indodax asli.

## 2. Aturan keras
- Hanya baca. Akun uji dari pemilik (sebelumnya `test@mail.com`, role admin); jangan mendaftarkan akun baru. Jangan mengeklik "Fetch price data", "Ingest", tombol analisis/ekspor, "Mark all read", "Delete all",
  atau apa pun yang memicu pekerjaan atau mengubah data di server. Membuka tab, mengganti timeframe/horizon, dan membuka dialog lalu **Batal** boleh. Step-up meminta kata sandi pemilik: jangan diisi.
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit. Artefak uji ke `%TEMP%`, bukan repo. `tests/test_architecture_constraints.py` tidak boleh diedit.
- Jangan ubah `Landing.tsx`, `index.css`, `public/landing/`. Jangan push. Jangan `git add -A`; stage per nama file. Jangan `ruff format` pada direktori.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan".

## 3. Tugas Q
Pakai Playwright Chromium (`%TEMP%\aidss-pw-verify`). Simpan bukti di luar repo. Bahasa `en` lalu `id`.
1. **Konfirmasi versi:** chunk utama yang dimuat adalah `index-HvlgnJp2.js`; sebutkan juga chunk halaman yang diunduh pada tiap rute.
2. **Dua overflow yang dulu ditemukan:** (a) `/assets/BBCA`, tab Analisis, bahasa `id`, lebar 320 px: `scrollWidth` dibanding `clientWidth`; (b) `/picks` pada 375 px. Keduanya harus 0. Ukur juga 360, 375, 768, 1280 px pada kedua rute.
3. **Overflow dokumen** di 375 dan 320 px untuk `/watchlist`, `/portfolio`, `/journal`, `/picks`, `/monitoring`, `/trader`, `/admin`, `/assets/BBCA` (semua enam tab). Laporkan elemen pelakunya bila ada (tag, kelas, lebar, teks), mengabaikan yang berada di dalam kontainer `overflow-x:auto`.
4. **Tinggi kontrol di 375 px:** untuk setiap rute di atas, daftar kontrol di `<main>` (`a[href]`, `button`, `select`, `input`, `[role=button]`) yang tinggi atau lebarnya di bawah 44 px, dengan teks dan ukurannya. Bandingkan dengan angka agen utama di bagian 1.
   Tambahkan juga halaman yang tidak diukur agen utama: panel notifikasi (lonceng di header, buka lalu tutup), `/admin` bagian-bagiannya (`/admin/users`, `/admin/audit`), dialog konfirmasi yang bisa dibuka lalu dibatalkan, dan `Layout` (header, sakelar bahasa ID/EN, sidebar). Ini daftar temuan, bukan perbaikan.
5. **Desktop tidak berubah:** pada 1280 px tinggi tombol timeframe `1d/1w/1M` tetap sekitar 24 px dan tombol `Button` md sekitar 38 px.
6. **Kerapatan di ponsel:** buka `/monitoring` (tab Watchlist dan Global), `/picks`, `/assets/BBCA` pada 375 px dan ambil tangkapan layar; catat apakah ada baris tombol yang kini terlalu tinggi, bertumpuk, atau memotong teks setelah kontrol dibesarkan. Pastikan tab Monitoring tampil dan bisa dipindah (klik Whole exchange / My watchlist) tanpa menghapus pilihan yang tidak seharusnya.
7. **TabStrip di Monitoring:** dua tab itu muat tanpa menggulir di 375 px; tombol berpindah, `aria-current="page"` berpindah, dan keyboard `Tab` + `Enter` mengaktifkannya.

Jika ada cacat (overflow tersisa, teks terpotong, tab Monitoring rusak), tentukan penyebabnya dari data produksi, perbaiki hanya di komponen terkait, tambahkan tes Vitest yang mereproduksinya, dan **jangan deploy**;
tulis di handoff bahwa butuh build dan deploy oleh agen utama. Jika bersih, jangan mengubah kode. Temuan kontrol kecil di luar primitif bersama (halaman admin, notifikasi, dialog, checkbox 13 px) dicatat sebagai temuan dengan daftar berkas yang menulis kelasnya, bukan diperbaiki,
karena memperbesarnya mengubah kerapatan tampilan dan butuh keputusan pemilik.

## 4. Sebelum commit (hanya bila ada perubahan kode)
`ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: **`./node_modules/.bin/tsc -b --noEmit`** (bukan `npx tsc`:
TypeScript 7.0.2 global kadang menggantikan 5.9.3), `npx oxlint .`, **`npx vitest run --pool=vmThreads`** (pool bawaan gagal di mesin ini pada Node 26, juga pada HEAD bersih), `npm run build`.
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Tambahkan record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`,
dan perbarui `TASKS/PROGRESS.md` hanya sebatas bukti. Kita memakai working tree yang sama: jangan menjalankan tes saat agen utama sedang mengubah berkas (periksa `git status` dulu), supaya hasil tidak tercampur.

## 5. Handoff (wajib, dengan format lengkap sembilan bagian)
`MEMORY/handoffs/2026-11-15-Q-production-layout-remeasure.md`, satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` yang diperbarui. Format (jangan dilewati bagian mana pun):

```
Tanggal/jam, Agen, HEAD saat selesai (sha nyata), Status: SELESAI | DIBLOKIR
## 1. Ringkasan satu paragraf
## 2. Commit (sha, pesan, file) dan file yang SENGAJA tidak disentuh
## 3. Bukti (keluaran asli, bukan ringkasan), dan SIAPA yang menjalankan tiap bukti: [agen kedua] / [agen utama] / [pemilik]
## 4. Perintah verifikasi untuk agen utama (maksimal 8, read-only, keluaran yang DIHARAPKAN)
## 5. DIVERIFIKASI vs DITULIS TAPI TIDAK DIJALANKAN
## 6. Temuan baru dan tindakannya
## 7. Keputusan yang menunggu pemilik
## 8. Rollback: cara, diuji atau belum, waktu yang DIUKUR (perkiraan berlabel)
## 9. Risiko tersisa
```
Daftar commit yang belum di-push diambil dari `git log --oneline origin/main..HEAD`. Jika terblokir atau ragu apakah suatu aksi aman, berhenti dan tulis handoff; jangan memperluas lingkup.
