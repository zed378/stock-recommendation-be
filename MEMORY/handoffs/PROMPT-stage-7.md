# Prompt tahap 7 untuk agen sebelah: ukur ulang overflow `/assets/:ticker` di produksi (`dd2d776`)

Repo: `C:\Users\Zed\Documents\Project\stock-recommendation`, branch `main`. Titik awal: `HEAD = origin/main = a8f2072`.
Agen utama (Claude) tidak mengimplementasi; ia memeriksa handoff-mu dan menjalankan perintah verifikasimu. Percakapan: Indonesia. Dokumen proyek: Inggris.
Satu tugas (P), read-only terhadap produksi. Tidak ada akses SSH, build, push image, atau deploy untukmu.

## 0. Baca dulu
`CLAUDE.md`, `AGENTS.md`, handoff O, `MEMORY/records/2026-11-15-asset-page-mobile-overflow.md`, `MEMORY/records/2026-11-15-first-deploy.md` (bagian redeploy `dd2d776`),
`frontend/src/components/TabStrip.tsx`, `frontend/src/components/__tests__/TabStrip.test.tsx`.

## 1. Keadaan (fakta)
- Di tugas O kamu mengukur `/assets/BBCA` pada 375 px: `scrollWidth 523`, `overflowPx 148`. Penyebabnya ternyata baris enam tab (Chart, Indicators, Fundamentals, Analysis,
  Strategy, News) selebar sekitar 507 px, bukan data. Diperbaiki dengan komponen `TabStrip` (menggulir di dalam dirinya, label utuh, tab terpilih digulir ke tampilan, tinggi 44 px di bawah `sm`).
- Produksi menjalankan `aidss-frontend:dd2d776` (chunk utama `index-B1brQ7pV.js`, chunk `AssetDetail-u7eMYfpv.js`). Dari luar sudah terverifikasi lewat curl bahwa chunk itu memuat kelas tab baru
  (`overflow-x-auto overscroll-x-contain`, `shrink-0 whitespace-nowrap`) dan tidak memuat baris lama. **Pengukuran lebar di produksi belum ada**: agen utama tidak punya login uji. Bukti sebelumnya hanya dari
  browser lokal dengan API dimock (dokumen sama dengan viewport pada 375, 360, 320, 768, 1280; di 375 strip 343 px berisi 507 px, klik News menggulirnya ke `scrollLeft 164`).
- Trader `HALTED`, tanpa URL exchange, tanpa kunci. Tidak pernah ada panggilan ke Indodax asli.

## 2. Aturan keras
- Hanya baca. Akun uji dari pemilik (sebelumnya `test@mail.com`, role admin); jangan mendaftarkan akun baru. Jangan mengeklik "Fetch price data", "Ingest", atau tombol analisis/ekspor yang memicu pekerjaan di server;
  membuka tab dan mengganti timeframe boleh. Jangan menyimpan apa pun, jangan ubah data produksi. Step-up meminta kata sandi pemilik: jangan diisi.
- Tidak ada secret literal di kode, dokumen, log, atau pesan commit. Artefak uji ke `%TEMP%`, bukan repo. `tests/test_architecture_constraints.py` tidak boleh diedit.
- Jangan ubah `Landing.tsx`, `index.css`, `public/landing/`. Jangan push. Jangan `git add -A`; stage per nama file. Jangan `ruff format` pada direktori.
- Bedakan "diverifikasi (dengan bukti)" dari "ditulis tapi tidak dijalankan".

## 3. Tugas P
Pakai Playwright Chromium (`%TEMP%\aidss-pw-verify`). Simpan bukti di luar repo. Target `https://aidss.zedth.my.id/assets/BBCA` (atau ticker lain di watchlist bila BBCA tidak ada), bahasa `en` lalu `id`.
1. **Konfirmasi versi:** chunk utama yang dimuat adalah `index-B1brQ7pV.js` dan chunk halaman `AssetDetail-u7eMYfpv.js`.
2. **Overflow dokumen** (`document.documentElement.scrollWidth` dibanding `clientWidth`) pada 375, 360, 320, 768, 1280 px, dan pada **setiap tab** (Chart, Indicators, Fundamentals, Analysis, Strategy, News) di 375 dan 320.
   Ini penting: pada tugas O hanya tab awal yang diukur, dan data nyata tiap tab (tabel fundamental, teks analisis, daftar berita, panel strategi) bisa menimbulkan overflow lain yang tidak muncul di mock.
   Bila ada elemen yang melewati tepi, laporkan penelusurannya (tag, kelas, lebar, teksnya) dengan cara yang sama seperti `getBoundingClientRect().right > viewport` dan abaikan yang berada di dalam kontainer `overflow-x:auto`.
3. **Baris tab di 375:** lebar `nav` vs isinya (`clientWidth`, `scrollWidth`), tinggi tombol (harus ≥ 44), klik News: apakah tab terlihat penuh dan `aria-current="page"` berpindah, lalu kembali ke Chart: `scrollLeft` kembali ke 0.
   Pada 1280: strip tidak menggulir dan tinggi tombol sekitar 38.
4. **Keyboard:** `Tab` sampai tombol tab terakhir; apakah ia tergulir ke tampilan dan memiliki indikator fokus yang terlihat? `Enter`/`Space` mengaktifkannya.
5. **Tampilan:** ambil tangkapan layar baris tab di 375 (aktif di Chart dan di News) dan periksa bahwa garis bawah tab aktif terbaca dan bagian tab yang terpotong di tepi memberi petunjuk bahwa strip bisa digulir.
6. Sebagai pembanding, ulangi pengukuran overflow 375 px pada `/watchlist`, `/portfolio`, `/journal`, `/picks`, `/monitoring`, `/trader`, dan `/admin` (read-only), supaya halaman lain dengan masalah serupa terdeteksi.

Jika ada overflow yang tersisa, tentukan penyebabnya dari data produksi, perbaiki hanya di komponen terkait (bukan `Landing.tsx`/`index.css`), tambahkan tes Vitest, dan **jangan deploy**; tulis di handoff bahwa butuh build dan deploy oleh agen utama.
Jika bersih, jangan mengubah kode. Catat temuan non-overflow (misalnya target sentuh di bawah 44 px pada tombol timeframe `1d / 1w / 1M` yang kira-kira 28 px) sebagai temuan, bukan perbaikan.

## 4. Sebelum commit (hanya bila ada perubahan kode)
`ruff check src tests alembic_trader deploy`; `python -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`; di `frontend/`: **`./node_modules/.bin/tsc -b --noEmit`** (bukan `npx tsc`:
TypeScript 7.0.2 global kadang menggantikan 5.9.3), `npx oxlint .`, **`npx vitest run --pool=vmThreads`** (pool bawaan gagal di mesin ini pada Node 26, juga pada HEAD bersih), `npm run build`.
Pemindaian secret pada diff yang di-stage: `git diff --cached | grep -E 'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY'` harus kosong. Tambahkan record di `MEMORY/records/`, satu baris di `MEMORY/MEMORY-INDEX.md`,
dan perbarui `TASKS/PROGRESS.md` hanya sebatas bukti.

## 5. Handoff (wajib, dengan format lengkap sembilan bagian)
`MEMORY/handoffs/2026-11-15-P-asset-page-overflow-production.md`, satu baris di `MEMORY/handoffs/INDEX.md`, lalu `...-Z-final.md` yang diperbarui. Format (jangan dilewati bagian mana pun, termasuk rollback dan pemisahan "diverifikasi vs tidak dijalankan"):

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
