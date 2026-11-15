# Prompt tahap 9 untuk agen sebelah: ukur header dan tautan ticker di produksi (`db57068`)

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = origin/main = 683abdb`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Satu tugas (R), read-only terhadap produksi. Tidak ada akses SSH, build, push image, atau deploy untukmu.

## 0. Baca dulu
`CLAUDE.md`, `AGENTS.md`, handoff Q, `MEMORY/records/2026-11-15-header-and-ticker-tap-targets.md`, `MEMORY/records/2026-11-15-phone-tap-targets.md`,
`MEMORY/records/2026-11-15-first-deploy.md` (bagian redeploy `db57068`), `frontend/src/components/Layout.tsx`, `frontend/src/components/primitives.tsx` (`tickerLinkHitArea`).

## 1. Keadaan (fakta)
- Produksi `https://aidss.zedth.my.id` menjalankan `aidss-frontend:db57068` (chunk utama `index-BR0mddld.js`, chunk `primitives-DAGn815L.js`). Sejak `2fc6c0b`, **hanya di bawah breakpoint `sm` (lebar < 640 px)**:
  1. Kontrol header kini 44 px tingginya: tombol menu (44x44), tautan merek, lonceng notifikasi (44x44), tombol `ID`/`EN` (masing-masing 44x44), `Sign out`, dan tautan `All controls` di bar status Trader.
     Supaya header lengket tidak membengkak, padding baris dan jarak antar kontrol dirapatkan (`gap-1`), dan **teks merek "AIDSS" disembunyikan di bawah 368 px** (`max-[23rem]:hidden`).
  2. Badge jumlah belum dibaca pada lonceng digeser ke dalam (`right-1 top-1`) agar tetap menempel ke ikon.
  3. Tautan ticker di daftar (`/picks`, hasil scan di `/monitoring`) diperbesar dengan padding dan margin negatif yang sama (`tickerLinkHitArea`), sehingga tinggi baris dan halaman tidak berubah.
- Pengukuran lokal agen utama (Playwright, API mock): header di 375, 360, 320 px: semua kontrol 44 px, `Sign out` tetap satu baris, lebar dokumen = viewport; tinggi header 184 menjadi 188 px; tautan ticker di `/picks` dari 31x20 menjadi 47x44 / 51x48,
  tinggi halaman dan setiap kartu identik dengan sebelumnya. Di 1280 px kontrol header dan tautan ticker tidak berubah. **Belum pernah diukur di produksi.**
- Pada Task Q kamu melaporkan di produksi (`2fc6c0b`) header: `Open menu 30x30`, `AIDSS 69x20`, `Open notifications 32x28`, `ID 28x24`, `EN 32x24`, `Sign out 67x24`, `All controls 79x24`, dan `/picks` 55 tautan ticker 31x20 / 35x24. Itu angka pembandingnya.
- Trader `HALTED`, tanpa URL exchange, tanpa kunci. Tidak pernah ada panggilan ke Indodax asli.

## 2. Aturan keras
- Hanya baca. Akun uji dari pemilik (sebelumnya `test@mail.com`, role admin); jangan mendaftarkan akun baru. Tombol `HALT` di bar status Trader **jangan diklik**. Jangan mengeklik "Fetch price data", "Ingest", tombol analisis/ekspor,
  "Mark all read", "Delete all", "Sign out" (mengakhiri sesi ujimu; ukur saja, jangan klik). Membuka panel notifikasi lalu menutupnya, mengganti bahasa ID/EN, dan membuka drawer menu boleh. Step-up meminta kata sandi pemilik: jangan diisi.
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit. Artefak uji ke `%TEMP%`, bukan repo. `tests/test_architecture_constraints.py` tidak boleh diedit.
- Jangan ubah `Landing.tsx`, `index.css`, `public/landing/`. Jangan push. Jangan `git add -A`; stage per nama file. Jangan `ruff format` pada direktori.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan".

## 3. Tugas R
Pakai Playwright Chromium (`%TEMP%\aidss-pw-verify`). Simpan bukti di luar repo.
1. **Konfirmasi versi:** chunk utama yang dimuat adalah `index-BR0mddld.js`, dan `primitives-DAGn815L.js` ikut diunduh pada `/picks`.
2. **Header di 375, 360, 320 px** pada `/watchlist` (bahasa `en` dan `id`): daftar setiap kontrol di `<header>` (tag, nama aksesibel, lebar x tinggi), apakah ada yang di bawah 44 px, apakah `Sign out` satu baris (tinggi teksnya), apakah teks merek "AIDSS" tampil di 375 dan hilang di 360 dan 320,
   tinggi total `<header>` (acuan lokal: 188 px), dan `scrollWidth` dokumen = viewport. Ulangi pada `/picks`, `/monitoring`, `/assets/BBCA`, `/trader`, dan `/admin` (cukup 375 dan 320).
   Pada tampilan dengan bar status Trader **bukan** `HALTED`/memuat (status nyata produksi), periksa juga bahwa bar tetap muat dan `HALT` (53x44) serta `All controls` tidak saling tumpang.
3. **Lonceng:** pada akun uji, jika ada notifikasi belum dibaca, apakah badge menempel ke ikon (bukan terpisah jauh) dan tidak menutupi tombol `ID`; buka panelnya lalu tutup (Escape) dan pastikan tidak ada overflow. Jika tidak ada notifikasi, katakan begitu, jangan memalsukan.
4. **Drawer menu:** buka lewat tombol menu 44x44 di 375 px, pastikan fokus dan penutupannya benar (Escape dan klik di luar), dan tombol menu mudah ditekan ibu jari (area sentuh tidak tumpang dengan lonceng).
5. **Tautan ticker:** di `/picks` pada 375 px, ukur semua tautan ticker (`a[href^="/assets/"]` di `<main>`): lebar dan tinggi (harus ≥ 44 tinggi), tinggi total halaman dan tinggi beberapa kartu dibanding pengukuran tugas Q (jika kamu menyimpannya) atau bandingkan dengan 1280 px bahwa tata letak baris tidak bergeser.
   Pastikan dua tautan yang bersebelahan tidak tumpang tindih area sentuhnya (cek dengan `elementFromPoint` di titik tengah antar dua baris), dan klik satu tautan ticker mengantar ke `/assets/<ticker>`. Ulangi untuk hasil scan di `/monitoring` (tab Whole exchange; hanya baca).
6. **Desktop tidak berubah:** pada 1280 px kontrol header tetap sekitar 32x28 (lonceng), 28x24 (`id`), 32x24 (`en`), 67x24 (`Sign out`), 79x24 (`All controls`), `HALT` 53x26; tautan ticker tetap 31x20 / 35x24; tinggi header 96 px.
7. **Tablet 768 px:** catat apa adanya ukuran kontrol header (diketahui tetap kompak karena perubahan hanya di bawah `sm`; tombol menu 30x30 tampil sampai `lg`), sebagai temuan untuk keputusan pemilik.
8. Tangkapan layar header di 375 dan 320 (`en` dan `id`) dan satu kartu `/picks`; periksa teks tidak terpotong atau tumpang.

Jika ada cacat (kontrol di bawah 44 px yang seharusnya 44, teks terpotong, `Sign out` dua baris, header meluap, area sentuh tumpang), tentukan penyebabnya dari data produksi, perbaiki hanya di komponen terkait, tambahkan tes Vitest yang mereproduksinya, dan **jangan deploy**;
tulis di handoff bahwa butuh build dan deploy oleh agen utama. Jika bersih, jangan mengubah kode. Temuan kontrol kecil di luar cakupan ini (Admin, checkbox 13 px, `Strategy`, `TranslateToggle`, `MultiSelect`) dicatat sebagai temuan dengan daftar berkas, bukan diperbaiki.

## 4. Sebelum commit (hanya bila ada perubahan kode)
`ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: **`./node_modules/.bin/tsc -b --noEmit`** (bukan `npx tsc`:
TypeScript 7.0.2 global kadang menggantikan 5.9.3), `npx oxlint .`, **`npx vitest run --pool=vmThreads`** (pool bawaan gagal di mesin ini pada Node 26, juga pada HEAD bersih), `npm run build`.
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Tambahkan record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`,
dan perbarui `TASKS/PROGRESS.md` hanya sebatas bukti. Kita memakai working tree yang sama: periksa `git status` dulu dan jangan menjalankan tes saat agen utama sedang mengubah berkas, supaya hasil tidak tercampur.

## 5. Handoff (wajib, dengan format lengkap sembilan bagian)
`MEMORY/handoffs/2026-11-15-R-production-header-ticker-remeasure.md`, satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` yang diperbarui. Format (jangan dilewati bagian mana pun):

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
