/**
 * Every string the interface shows, in both languages.
 *
 * One flat object per locale rather than nested namespaces: the keys read as
 * sentences at the call site, and a missing translation is a TypeScript error
 * because `en` is typed against `id` rather than declared independently.
 *
 * Indonesian is the source of truth. This is an IDX product read by Indonesian
 * investors, and translating *from* the language the domain is actually spoken
 * in produces better terms than translating into it - `emiten`, `laporan
 * keuangan`, and `kuartal berjalan` have no clean English equivalents that a
 * translator working the other way would land on.
 */

export const id = {
  // --- shell -------------------------------------------------------------
  "app.name": "AI Investment Decision Support",
  "app.shortName": "AIDSS",
  "app.tagline": "Alat bantu keputusan — bukan bot trading",

  "export.pdf": "Ekspor PDF",
  "export.entry": "Harga masuk",
  "export.generated": "Dibuat",
  "export.timeframe": "Kerangka waktu",
  "export.agents": "Temuan tiap agen",
  "export.page": "hal.",
  "pager.none": "Tidak ada data",
  "pager.range": "{first}–{last} dari {total}",
  "pager.perPage": "Per halaman",
  "pager.previous": "Sebelumnya",
  "pager.next": "Berikutnya",
  "admin.tab.settings": "Pengaturan",
  "admin.tab.providers": "Penyedia AI",
  "admin.users.create": "+ Buat akun",
  "admin.users.createTitle": "Buat akun baru",
  "admin.users.createHint": "Dipakai saat pendaftaran ditutup, atau untuk membuat admin kedua.",
  "admin.users.created": "Akun dibuat",
  "admin.settings.title": "Pengaturan platform",
  "admin.settings.registration": "Pendaftaran terbuka",
  "admin.settings.registrationHint": "Saat ditutup, hanya admin yang bisa membuat akun. Akun pertama pada instansi kosong selalu diizinkan.",
  "admin.settings.newsCron": "Jadwal sapuan berita (cron)",
  "admin.settings.newsCronHint": "Kosongkan untuk mematikan. Dibaca dalam waktu bursa (WIB). Contoh: 0 */2 * * *",
  "admin.settings.saved": "Pengaturan tersimpan",
  "admin.settings.caveat": "Pendaftaran yang ditutup tidak memengaruhi akun yang sudah ada. Jadwal cron dibaca dalam waktu bursa (WIB), dan perubahannya berlaku pada tick penjadwal berikutnya.",
  "admin.providers.title": "Penyedia AI",
  "admin.providers.add": "+ Tambah penyedia",
  "admin.providers.empty": "Belum ada penyedia yang dikonfigurasi.",
  "admin.providers.emptyHint": "Tanpa satu pun, platform memakai penyedia dari environment. Tambahkan di sini agar bisa berganti model tanpa deploy ulang.",
  "admin.providers.name": "Nama",
  "admin.providers.model": "Model",
  "admin.providers.role": "Peran",
  "admin.providers.priority": "Prioritas",
  "admin.providers.priorityHint": "Lebih kecil dicoba lebih dulu dalam rantai fallback.",
  "admin.providers.baseUrl": "Base URL",
  "admin.providers.apiKey": "API key",
  "admin.providers.apiKeyKeep": "Biarkan kosong untuk mempertahankan kunci tersimpan. Isi spasi lalu hapus untuk menghapusnya.",
  "admin.providers.apiKeyStored": "Kunci tersimpan: {hint}",
  "admin.providers.timeout": "Timeout (detik)",
  "admin.providers.selfHosted": "Inferensi milik sendiri",
  "admin.providers.selfHostedHint": "Menentukan apakah data keuangan pribadi boleh dikirim ke sini.",
  "admin.providers.costIn": "Biaya per 1K token masuk",
  "admin.providers.costOut": "Biaya per 1K token keluar",
  "admin.providers.test": "Uji",
  "admin.providers.testOk": "Terhubung dalam {ms} ms",
  "admin.providers.active": "Aktif",
  "admin.providers.caveat": "Kunci disimpan terenkripsi dan tidak pernah dikembalikan API. Mengganti AIDSS_JWT_SECRET membuat kunci tersimpan tidak terbaca dan harus dimasukkan ulang.",
  "nav.group.research": "Riset",
  "nav.group.watching": "Pemantauan",
  "nav.group.positions": "Posisi",
  "nav.group.administration": "Administrasi",
  "nav.openMenu": "Buka menu",
  "admin.tab.issuers": "Emiten",
  "admin.issuers.title": "Direktori emiten",
  "admin.issuers.sync": "Sinkron dari IDX",
  "admin.issuers.syncQueued": "Sinkronisasi direktori dimulai",
  "admin.issuers.saved": "Alias tersimpan",
  "admin.issuers.searchPlaceholder": "Cari kode atau nama perusahaan…",
  "admin.issuers.listedOnly": "Hanya yang tercatat",
  "admin.issuers.empty": "Direktori masih kosong.",
  "admin.issuers.emptyHint": "Sinkronkan dari IDX agar penandaan berita punya daftar perusahaan untuk dicocokkan.",
  "admin.issuers.name": "Nama",
  "admin.issuers.sector": "Subsektor",
  "admin.issuers.aliases": "Alias",
  "admin.issuers.delisted": "delisting",
  "admin.issuers.edit": "Ubah alias",
  "admin.issuers.automatic": "Otomatis (indeks + turunan nama) — tidak bisa diubah di sini",
  "admin.issuers.extraAliases": "Alias tambahan",
  "admin.issuers.extraHint": "Satu per baris. Hindari satu kata umum: ia akan menandai ratusan berita yang tidak terkait.",
  "admin.issuers.syncedAt": "Disinkronkan {when}",
  "admin.issuers.caveat": "Alias dicocokkan pada batas kata dan tanpa memperhatikan huruf besar-kecil. Kode emiten dicocokkan peka huruf besar, karena BANK dan LABA juga kata Indonesia biasa.",
  "nav.watchlist": "Watchlist",
  "nav.portfolio": "Portofolio",
  "nav.journal": "Jurnal",
  "nav.chat": "Tanya AI",
  "nav.signOut": "Keluar",
  "nav.language": "Bahasa",

  // --- the constraint that defines the product ---------------------------
  "disclaimer.short": "Informasional. Bukan nasihat investasi.",
  "disclaimer.long":
    "Semua keluaran di sini bersifat informasional dan tidak merupakan nasihat investasi. " +
    "Platform ini tidak dapat menempatkan order, tidak terhubung ke broker mana pun, dan " +
    "tidak mengeksekusi apa pun. Setiap keputusan dan risikonya ada pada Anda.",
  "disclaimer.title": "Alat bantu keputusan, bukan bot trading",

  // --- auth --------------------------------------------------------------
  "auth.signIn": "Masuk",
  "auth.signUp": "Daftar",
  "auth.email": "Email",
  "auth.password": "Kata sandi",
  "auth.fullName": "Nama lengkap",
  "auth.noAccount": "Belum punya akun?",
  "auth.haveAccount": "Sudah punya akun?",
  "auth.signingIn": "Sedang masuk…",
  "auth.signingUp": "Sedang mendaftar…",
  "auth.failed": "Email atau kata sandi salah.",
  "auth.registerFailed": "Pendaftaran gagal.",
  "auth.sessionExpired": "Sesi Anda berakhir. Silakan masuk lagi.",
  // States the policy the server actually enforces. Inventing stricter-looking
  // rules would make people pick passwords to satisfy a rule that does not
  // exist, and would be wrong the moment the real one changed.
  "auth.passwordHint": "Minimal 10 karakter.",

  "login.lede":
    "Analisis multi-agen untuk emiten IDX, dengan alasannya ditulis lengkap — " +
    "termasuk bukti yang membantahnya.",
  "login.point1.title": "Setiap sikap membawa penyangkalnya",
  "login.point1.body":
    "Rekomendasi tanpa faktor yang membantahnya ditolak sebelum tersimpan. Yang Anda baca " +
    "selalu memuat sisi lainnya.",
  "login.point2.title": "Confidence dihitung, bukan diklaim",
  "login.point2.body":
    "Angkanya berasal dari cakupan bukti, kesepakatan antar-agen, dan keseimbangannya — " +
    "bukan dari penilaian model atas dirinya sendiri.",
  "login.point3.title": "Data tertunda dinyatakan tertunda",
  "login.point3.body":
    "Sumber gratis tertinggal sekitar 15 menit. Setiap observasi mencatat kesegarannya " +
    "alih-alih menyiratkan yang tidak dimilikinya.",
  "login.constraint":
    "Platform ini tidak dapat menempatkan order, tidak terhubung ke broker mana pun, dan " +
    "tidak mengeksekusi apa pun. Setiap keputusan dan risikonya ada pada Anda.",
  "login.welcomeBack": "Selamat datang kembali",
  "login.welcomeBackHint": "Masuk untuk melanjutkan.",
  "login.createAccount": "Buat akun",
  "login.createAccountHint": "Gratis, dan watchlist Anda hanya milik Anda.",


  // --- watchlist ---------------------------------------------------------
  "watchlist.title": "Watchlist",
  "watchlist.empty": "Watchlist Anda masih kosong.",
  "watchlist.emptyHint": "Tambahkan emiten untuk mulai memantaunya.",
  "watchlist.add": "Tambah emiten",
  "watchlist.addPlaceholder": "Kode emiten, misal BBCA",
  "watchlist.note": "Catatan",
  "watchlist.notePlaceholder": "Kenapa emiten ini Anda pantau? (opsional)",
  "watchlist.remove": "Hapus",
  "watchlist.added": "Ditambahkan",
  "watchlist.adding": "Menambahkan…",
  "watchlist.addFailed": "Gagal menambahkan emiten.",
  "watchlist.confirmRemove": "Hapus {ticker} dari kelompok {category}?",

  "watchlist.category": "Kelompok",
  "watchlist.categoryPlaceholder": "mis. Perbankan, Dividen",
  "watchlist.categoryHint": "Kelompok dibuat otomatis saat pertama dipakai.",
  "watchlist.categoryEmpty": "Kelompok ini kosong.",
  "watchlist.allCategories": "Semua kelompok",
  "watchlist.move": "Pindah",
  "watchlist.moveTitle": "Pindahkan {ticker}",
  "watchlist.currentCategory": "sekarang",
  "watchlist.moveHint":
    "Satu emiten hanya berada di satu kelompok. Memindahkannya tidak menghapus catatan.",
  "watchlist.categoryExists": "Kelompok {name} sudah ada.",
  "watchlist.sameTickerNote":
    "Satu emiten boleh berada di lebih dari satu kelompok — bank yang membagi dividen " +
    "masuk ke keduanya.",
  "watchlist.expandAll": "Buka semua",
  "watchlist.collapseAll": "Tutup semua",
  "watchlist.newCategory": "+ Buat kelompok baru",
  "watchlist.newCategoryName": "Nama kelompok",
  // The "+" belongs to the button, which is an invitation. A dialog title is a
  // statement of where you already are, and reads as a stray character there.
  "watchlist.createCategory": "+ Kelompok baru",
  "watchlist.createCategoryTitle": "Buat kelompok baru",
  "watchlist.create": "Buat",
  "watchlist.emptyCategoryHint": "Kelompok kosong boleh saja — isi kapan pun Anda mau.",
  "watchlist.rename": "Ganti nama",
  "watchlist.renameTitle": "Ganti nama kelompok {name}",
  "watchlist.deleteCategory": "Hapus kelompok",
  "watchlist.confirmDeleteCategory":
    "Hapus kelompok {name}? {count} emiten di dalamnya akan dipindahkan ke Default, " +
    "bukan ikut dihapus.",
  "watchlist.categoryActionFailed": "Aksi kelompok gagal.",

  "watchlist.search": "Cari",
  "watchlist.searchPlaceholder": "Kode, nama perusahaan, sektor, atau catatan Anda…",
  "watchlist.searchHint": "Catatan Anda ikut dicari — di situlah alasan memantau biasanya ditulis.",
  "watchlist.searchResults": "{count} hasil untuk “{query}”",
  "watchlist.searchNothing": "Tidak ada yang cocok dengan “{query}”.",
  "watchlist.clearSearch": "Hapus pencarian",
  "watchlist.item": "emiten",
  "watchlist.items": "emiten",

  // --- asset -------------------------------------------------------------
  "asset.price": "Harga",
  "asset.change": "Perubahan",
  "asset.notFound": "Emiten tidak ditemukan.",
  "asset.notFoundHint": "Emiten ini belum terdaftar. Tambahkan dulu lewat watchlist.",
  "asset.ingest": "Ambil data harga",
  "asset.ingesting": "Mengambil data…",
  "asset.ingestDone": "{count} bar tersimpan.",
  "asset.noCandles": "Belum ada data harga untuk emiten ini.",
  "asset.noCandlesHint": "Ambil data harga dulu, lalu indikator akan dihitung.",

  "tab.chart": "Grafik",
  "tab.indicators": "Indikator",
  "tab.fundamentals": "Fundamental",
  "tab.analysis": "Analisis",
  "tab.news": "Berita",

  "timeframe.label": "Rentang",

  // --- indicators --------------------------------------------------------
  "indicators.title": "Indikator teknikal",
  "indicators.empty": "Belum ada indikator terhitung.",
  "indicators.emptyHint": "Ambil data harga dulu — indikator dihitung dari candle tersimpan.",
  "indicators.asOf": "Per {date}",
  "indicators.bars": "Jumlah bar",
  "indicators.lastClose": "Penutupan terakhir",
  "indicators.structure": "Struktur pasar",
  "indicators.structure.ranging": "Menyamping",
  "indicators.structure.uptrend": "Tren naik",
  "indicators.structure.downtrend": "Tren turun",
  "indicators.levels": "Level support & resistance",
  "indicators.support": "Support",
  "indicators.resistance": "Resistance",
  "indicators.breakout": "Breakout",
  "indicators.breakout.direction": "Arah",
  "indicators.breakout.none": "Tidak ada",
  "indicators.breakout.up": "Ke atas",
  "indicators.breakout.down": "Ke bawah",
  "indicators.breakout.level": "Level",
  "indicators.breakout.lookback": "Jendela",
  "indicators.breakoutNote":
    "Jendela breakout tidak menyertakan bar berjalan, sehingga sinyalnya tidak berubah " +
    "di tengah sesi lalu hilang lagi setelah penutupan.",
  "indicators.features": "Fitur turunan",
  "indicators.levelsNote":
    "Level dihitung dari harga historis, bukan target. Ia menandai di mana harga pernah " +
    "berbalik, bukan di mana ia akan berbalik.",

  // --- fundamentals ------------------------------------------------------
  "fundamentals.title": "Data fundamental",
  "fundamentals.empty": "Belum ada data fundamental tersimpan.",
  "fundamentals.emptyHint":
    "Ambil data fundamental untuk emiten ini, atau penyedia data mungkin tidak meliputnya.",
  "fundamentals.ingest": "Ambil fundamental",
  "fundamentals.metric": "Metrik",
  "fundamentals.value": "Nilai",
  "fundamentals.period": "Periode",
  "fundamentals.source": "Sumber",
  "fundamentals.basis": "Basis",
  "fundamentals.basis.ytd": "Kumulatif berjalan",
  "fundamentals.basis.annual": "Tahunan",
  "fundamentals.basis.quarterly": "Kuartalan",
  "fundamentals.basis.ttm": "12 bulan terakhir",
  "fundamentals.basisNote":
    "Angka kumulatif berjalan mencakup sebagian tahun buku, bukan setahun penuh. " +
    "Membandingkannya dengan angka tahunan adalah kesalahan yang mudah terjadi.",

  // --- analysis ----------------------------------------------------------
  "analysis.title": "Analisis AI",
  "analysis.run": "Jalankan analisis",
  "analysis.running": "Sedang menganalisis…",
  "analysis.runningHint": "Beberapa agen berjalan berurutan. Ini bisa memakan waktu.",
  "analysis.empty": "Belum ada analisis untuk emiten ini.",
  "analysis.failed": "Analisis gagal.",
  "analysis.history": "Riwayat",
  "analysis.agentsRan": "Agen yang berjalan",
  "analysis.agentFindings": "Temuan tiap agen",
  "analysis.signals": "Sinyal",
  "analysis.watchItems": "Yang perlu diperhatikan",
  "analysis.disagreements": "Perbedaan antar-agen",
  // Names the section it applies to. The recommendation below often *can*
  // switch on the same analysis, so "this is in one language only" without
  // saying which part reads as a contradiction of what the reader can see.
  "analysis.noAgentTranslation":
    "Temuan agen di bawah ini hanya tersedia dalam bahasa aslinya — analisis ini " +
    "dijalankan sebelum terjemahan per-agen disimpan. Jalankan ulang analisis untuk " +
    "mendapat keduanya. (Rekomendasi di bawahnya tetap mengikuti sakelar ini.)",
  "analysis.skipped": "Dilewati",
  "analysis.agentFailed": "Gagal",
  "analysis.skippedNote":
    "Agen yang dilewati menyebutkan alasannya. Ini menurunkan cakupan bukti, " +
    "dan karena itu menurunkan confidence.",

  // --- recommendation ----------------------------------------------------
  "rec.title": "Rekomendasi",
  "rec.label.buy": "Beli",
  "rec.label.sell": "Jual",
  "rec.label.hold": "Tahan",
  "rec.label.watchlist": "Pantau",
  "rec.label.strong_buy": "Beli kuat",
  "rec.label.strong_sell": "Jual kuat",

  "rec.confidence": "Confidence",
  "rec.confidenceBasis": "Dasar perhitungan",
  "rec.confidenceExplain":
    "Dihitung dari cakupan bukti, tingkat kesepakatan antar agen, dan keseimbangan " +
    "argumen — bukan angka yang disebutkan sendiri oleh model.",
  "rec.modelSelfReported": "Confidence menurut model",
  "rec.modelSelfReportedNote":
    "Ditampilkan untuk perbandingan saja. Angka inilah yang justru tidak dipakai.",

  "rec.reasoning": "Alasan",
  "rec.supporting": "Faktor pendukung",
  "rec.conflicting": "Faktor yang bertentangan",
  "rec.risks": "Risiko",
  "rec.bullish": "Skenario naik",
  "rec.bearish": "Skenario turun",
  "rec.support": "Support",
  "rec.resistance": "Resistance",
  "rec.target": "Target harga",
  "rec.stop": "Saran stop",
  "rec.horizon": "Horizon waktu",
  "rec.method": "Metode",
  "rec.noTarget": "Tidak ada",
  "rec.noTargetReason":
    "Sikap netral tidak punya dasar arah untuk menghitung target. " +
    "Mengarangnya justru meniadakan makna sikap itu sendiri.",
  "rec.provenance": "Asal keluaran",
  "rec.model": "Model",
  "rec.promptVersion": "Versi prompt",
  "rec.attempts": "Percobaan",

  "rec.components": "Komponen perhitungan",
  "rec.component.coverage": "Cakupan bukti",
  "rec.component.coverageWhat": "Berapa banyak sumber bukti yang benar-benar tersedia",
  "rec.component.agreement": "Kesepakatan arah",
  "rec.component.agreementWhat": "Seberapa sejalan arah antar agen yang berjalan",
  "rec.component.balance": "Keseimbangan bukti",
  "rec.component.balanceWhat": "Apakah faktor yang bertentangan ikut disebutkan",
  "rec.signals": "Sinyal per agen",
  "rec.signal.agent": "Agen",
  "rec.signal.direction": "Arah",
  "rec.signal.sufficiency": "Kecukupan data",
  "rec.direction.bullish": "Naik",
  "rec.direction.bearish": "Turun",
  "rec.direction.neutral": "Netral",
  "rec.rawBasis": "Data mentah",

  // --- portfolio ---------------------------------------------------------
  "portfolio.title": "Portofolio",
  "portfolio.empty": "Belum ada kepemilikan tercatat.",
  "portfolio.emptyHint": "Tambahkan kepemilikan secara manual untuk melihat analisisnya.",
  "portfolio.addHolding": "Tambah kepemilikan",
  "portfolio.ticker": "Emiten",
  "portfolio.quantity": "Jumlah lot/lembar",
  "portfolio.avgPrice": "Harga rata-rata",
  "portfolio.value": "Nilai",
  "portfolio.weight": "Bobot",
  "portfolio.pnl": "Untung/rugi",
  "portfolio.totalValue": "Nilai total",
  "portfolio.analyse": "Analisis portofolio",
  "portfolio.analysing": "Menganalisis…",
  "portfolio.concentration": "Konsentrasi",
  "portfolio.unpriced": "Belum ada harga",
  "portfolio.unpricedNote":
    "Kepemilikan tanpa harga tersimpan tidak dinilai, dan ditandai — bukan dianggap nol.",
  "portfolio.manualOnly":
    "Data kepemilikan diinput manual. Platform ini tidak terhubung ke broker mana pun.",
  "portfolio.remove": "Hapus",

  // --- journal -----------------------------------------------------------
  "journal.title": "Jurnal investasi",
  "journal.empty": "Belum ada catatan.",
  "journal.emptyHint": "Catat alasan keputusan Anda, supaya bisa ditinjau nanti.",
  "journal.add": "Tambah catatan",
  "journal.content": "Keputusan",
  "journal.contentPlaceholder": "Apa yang Anda putuskan, dan kenapa?",
  "journal.note": "Catatan",
  "journal.tags": "Tag",
  "journal.reflection": "Minta refleksi",
  "journal.reflecting": "Menyusun refleksi…",
  "journal.summary": "Ringkasan",
  "journal.delete": "Hapus",

  // --- chat --------------------------------------------------------------
  "chat.title": "Tanya AI",
  "chat.placeholder": "Tanyakan sesuatu tentang pasar atau emiten…",
  "chat.send": "Kirim",
  "chat.sending": "Mengirim…",
  "chat.empty": "Belum ada percakapan.",
  "chat.emptyHint": "Ajukan pertanyaan untuk memulai.",
  "chat.you": "Anda",
  "chat.assistant": "AI",

  // --- strategy: sudah punya vs belum punya -------------------------------
  "tab.strategy": "Strategi",
  "strategy.title": "Apa artinya bagi posisi Anda",
  "strategy.empty": "Belum ada rekomendasi tersimpan untuk emiten ini.",
  "strategy.emptyHint": "Jalankan analisis dulu — strategi diturunkan darinya, bukan dibuat terpisah.",
  "strategy.notHolding": "Jika belum punya",
  "strategy.holding": "Jika sudah punya",
  "strategy.language": "Bahasa rekomendasi",
  "strategy.bothNote":
    "Keduanya ditampilkan, apa pun posisi Anda. Emiten yang layak dipertahankan tetapi " +
    "tidak layak dibeli hari ini adalah situasi nyata dan umum — menampilkan satu sisi saja " +
    "akan menyembunyikannya.",
  "strategy.conditions": "Syarat",
  "strategy.invalidatedIf": "Batal jika",
  "strategy.levels": "Level acuan",

  "stance.entry_candidate": "Kandidat masuk",
  "stance.wait_for_level": "Tunggu level",
  "stance.no_entry_basis": "Tidak ada dasar masuk",
  "stance.avoid": "Hindari",
  "stance.maintain": "Pertahankan",
  "stance.accumulate_candidate": "Kandidat tambah",
  "stance.trim_candidate": "Kandidat kurangi",
  "stance.exit_candidate": "Kandidat keluar",

  // --- stock picks --------------------------------------------------------
  "nav.picks": "Stock Pick",
  "picks.title": "Stock pick",
  "picks.horizon": "Horizon",
  "picks.horizonNote":
    "Horizon menyebut jendela waktu kondisi itu biasanya dibaca — bukan berapa lama " +
    "sesuatu akan terjadi.",
  "picks.empty": "Tidak ada emiten yang memenuhi kondisi ini.",
  "picks.emptyHint": "Kondisi bisa dilonggarkan, atau data harga belum cukup.",
  "picks.considered": "{count} emiten dipertimbangkan",
  "picks.insufficient": "{count} dilewati karena riwayat harga belum cukup",
  "picks.score": "Skor",
  "picks.met": "Kondisi terpenuhi",
  "picks.unmet": "Tidak terpenuhi",
  "picks.watchlistOnly": "Hanya watchlist saya",
  "picks.nearLimitOnly": "Hanya yang mendekati ARA",
  "picks.limitProximity": "Pemakaian band ARA",
  "picks.limitCeiling": "Batas atas sesi",
  "picks.notAForecast": "Ini penyaringan, bukan ramalan",

  // --- monitoring ---------------------------------------------------------
  "nav.monitoring": "Pantauan",
  "monitoring.title": "Pantauan & alert",
  "monitoring.quotes": "Harga terakhir",
  "monitoring.pollNow": "Perbarui sekarang",
  "monitoring.polling": "Memperbarui…",
  "monitoring.empty": "Belum ada emiten yang dipantau.",
  "monitoring.emptyHint": "Tambahkan emiten ke watchlist untuk mulai memantaunya.",
  "monitoring.neverPolled": "Belum pernah diambil",
  "monitoring.delayed": "Tertunda",
  "monitoring.delayedNote":
    "Sumber gratis tertunda sekitar 15 menit. Ditampilkan apa adanya — antarmuka yang " +
    "menyajikan harga tertunda seolah terkini mengundang keputusan atas angka yang sudah berubah.",
  "monitoring.observedAt": "Diamati",

  "alerts.title": "Alert",
  "alerts.empty": "Belum ada alert.",
  "alerts.emptyHint": "Alert muncul saat level ditembus, sikap berubah, atau band ARA hampir habis.",
  "alerts.unacknowledgedOnly": "Hanya yang belum dibaca",
  "news.empty": "Belum ada berita untuk emiten ini.",
  "news.emptyHint": "Berita masuk saat sumber RSS diambil. Admin bisa menekan “Ambil semua” di halaman admin.",
  "news.alsoAbout": "Juga membahas:",
  "news.matched.ticker_code": "cocok lewat kode emiten",
  "news.matched.company_name": "cocok lewat nama perusahaan",
  "news.matched.alias": "cocok lewat nama populer",
  "alerts.acknowledge": "Tandai dibaca",
  "alerts.selectAll": "Pilih semua yang tampil",
  "alerts.selectOne": "Pilih alert {ticker}",
  "alerts.selectedCount": "{count} dipilih",
  "alerts.clearSelection": "Batalkan pilihan",
  "alerts.readSelected": "Tandai dibaca",
  "alerts.deleteSelected": "Hapus terpilih",
  "alerts.readAll": "Tandai semua dibaca",
  "alerts.deleteAll": "Hapus semua",
  "alerts.batchDone": "{count} alert diperbarui",
  "alerts.deleteSelectedTitle": "Hapus alert terpilih?",
  "alerts.deleteSelectedBody": "{count} alert akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.",
  "alerts.deleteAllTitle": "Hapus semua alert?",
  "alerts.deleteAllBody": "Seluruh riwayat alert Anda akan dihapus permanen, termasuk yang belum dibaca. Tindakan ini tidak bisa dibatalkan.",
  "alerts.acknowledged": "Sudah dibaca",
  "alerts.note":
    "Alert menyatakan apa yang terjadi, bukan apa yang harus dilakukan. Sikap dan " +
    "confidence-nya ada di layar analisis, lengkap dengan faktor yang bertentangan.",
  "alert.level_approached": "Mendekati level",
  "alert.level_crossed": "Menembus level",
  "alert.stance_changed": "Sikap berubah",
  "alert.limit_proximity": "Mendekati batas ARA",
  "alert.suggested_stop_reached": "Mencapai level stop",
  "alert.unusual_move": "Pergerakan tidak biasa",
  "alert.stanceFrom": "Dari",
  "alert.stanceTo": "Menjadi",

  // --- translation --------------------------------------------------------
  "translate.show": "Tampilkan dalam Bahasa Inggris",
  "translate.showOriginal": "Tampilkan aslinya",
  "translate.working": "Menerjemahkan…",
  "translate.failed": "Terjemahan gagal.",
  "translate.machineNote":
    "Terjemahan mesin dari analisis di atas. Aslinya tetap yang otoritatif — label, " +
    "harga, dan confidence tidak diterjemahkan.",

  // --- admin -------------------------------------------------------------
  "nav.admin": "Admin",
  "admin.title": "Dashboard admin",
  "admin.forbidden": "Halaman ini hanya untuk admin.",
  "admin.forbiddenHint":
    "Akun baru mendapat peran investor. Promosi dilakukan dari shell, bukan lewat API — " +
    "endpoint yang membagikan peran admin adalah celah eskalasi hak akses. Jalankan: " +
    "python -m aidss.cli grant-admin {email}",

  "admin.tab.overview": "Ringkasan",
  "admin.tab.users": "Pengguna",
  "admin.tab.news": "Sumber berita",

  // --- account administration -------------------------------------------
  "admin.users.title": "Kelola pengguna",
  "admin.users.selectAll": "Pilih semua",
  "admin.users.select": "Pilih {email}",
  "admin.users.selected": "{count} akun dipilih",
  "admin.users.clearSelection": "Batal pilih",
  "admin.users.appliesTo": "Berlaku untuk:",
  "admin.users.batchProgress": "Memproses {done} dari {total}...",
  "admin.users.batchResult": "Hasil",
  "admin.users.batchSummary": "{done} dari {total} akun berhasil diproses.",
  "admin.users.batchFailed": "{count} gagal:",
  "admin.users.suspendTitleMany": "Suspend {count} akun",
  "admin.users.banTitleMany": "Ban {count} akun",
  "admin.users.roleTitleMany": "Peran untuk {count} akun",
  "admin.users.reasonNoteMany":
    "Alasan yang sama ditampilkan kepada setiap pemilik akun saat ia mencoba masuk.",
  "admin.users.deleteWarningMany":
    "Hapus {count} akun? Watchlist, portofolio, dan jurnal masing-masing ikut terhapus. " +
    "Tindakan ini tidak bisa dibatalkan.",
  "admin.users.typeCount": "Ketik {count} untuk mengonfirmasi",

  "admin.users.searchPlaceholder": "Cari email atau nama...",
  "admin.users.empty": "Tidak ada akun yang cocok.",
  "admin.users.account": "Akun",
  "admin.users.role": "Peran",
  "admin.users.status": "Status",
  "admin.users.since": "Terdaftar",
  "admin.users.you": "akun Anda",
  "admin.users.changeRole": "Peran",
  "admin.users.suspend": "Suspend",
  "admin.users.ban": "Ban",
  "admin.users.reinstate": "Pulihkan",
  "admin.users.delete": "Hapus",
  "admin.users.caveat":
    "Suspend dan ban dapat dibatalkan; hapus tidak. Menghapus akun ikut menghapus " +
    "watchlist, portofolio, dan jurnalnya.",

  "admin.users.status.active": "Aktif",
  "admin.users.status.suspended": "Disuspend",
  "admin.users.status.banned": "Diban",
  "admin.users.statusExpired": "Suspend berakhir",
  "admin.users.until": "sampai {when}",

  "admin.users.role.viewer": "Viewer \u2014 hanya membaca",
  "admin.users.role.investor": "Investor \u2014 kelola data sendiri",
  "admin.users.role.admin": "Admin \u2014 kelola sistem",
  "admin.users.roleTitle": "Peran untuk {email}",
  "admin.users.roleNote":
    "Viewer hanya membaca. Investor mengelola data miliknya sendiri. Admin mengelola " +
    "penyedia data, antrean, dan akun.",
  "admin.users.stepDownWarning":
    "Anda menurunkan peran akun Anda sendiri. Tidak ada endpoint yang bisa " +
    "mengembalikannya \u2014 pemulihan hanya lewat perintah shell di server.",

  "admin.users.suspendTitle": "Suspend {email}",
  "admin.users.banTitle": "Ban {email}",
  "admin.users.banNote":
    "Ban berlaku tanpa batas waktu dan tidak pernah dicabut oleh waktu. Akun beserta " +
    "riwayatnya tetap ada, dan admin masih bisa memulihkannya.",
  "admin.users.duration": "Durasi",
  "admin.users.days": "{count} hari",
  "admin.users.indefinite": "Tanpa batas",
  "admin.users.reason": "Alasan",
  "admin.users.reasonPlaceholder": "mis. Sedang ditinjau",
  "admin.users.reasonNote":
    "Alasan ini ditampilkan kepada pemilik akun saat ia mencoba masuk.",
  "admin.users.deleteTitle": "Hapus akun",
  "admin.users.deleteWarning":
    "Hapus {email}? Watchlist, portofolio, dan jurnalnya ikut terhapus. " +
    "Tindakan ini tidak bisa dibatalkan \u2014 gunakan ban jika Anda ingin bisa memulihkannya.",

  // --- news sources -------------------------------------------------------
  "admin.news.title": "Sumber berita (RSS/Atom)",
  "admin.news.searchPlaceholder": "Cari nama, URL, atau emiten...",
  "admin.news.filter": "Saring",
  "admin.news.filter.all": "Semua",
  "admin.news.filter.active": "Aktif",
  "admin.news.filter.off": "Nonaktif",
  "admin.news.filter.failing": "Bermasalah",
  "admin.news.noMatches": "Tidak ada sumber yang cocok.",
  "admin.news.clearFilters": "Bersihkan saringan",
  "admin.news.add": "+ Tambah sumber",
  "admin.news.sweep": "Ambil semua",
  "admin.news.sweeping": "Mengambil…",
  "admin.news.sweepHint": "Baca setiap feed aktif sekarang dan simpan isinya ke basis data",
  "admin.news.sweepQueued": "Pengambilan berita dimulai",
  "admin.news.issuerSync": "Sinkron emiten",
  "admin.news.issuerSyncHint": "Perbarui direktori perusahaan tercatat IDX yang dipakai untuk menandai berita",
  "admin.news.issuerSyncQueued": "Sinkronisasi direktori emiten dimulai",
  "admin.news.addTitle": "Tambah sumber berita",
  "admin.news.edit": "Ubah",
  "admin.news.editTitle": "Ubah {name}",
  "admin.news.empty": "Belum ada sumber berita.",
  "admin.news.emptyHint":
    "Tanpa sumber, pengambilan berita tidak punya tempat untuk mencari dan jadwal " +
    "akan melaporkan kegagalan.",
  "admin.news.name": "Nama",
  "admin.news.namePlaceholder": "mis. Google News \u2014 per emiten",
  "admin.news.url": "URL feed",
  "admin.news.urlHint":
    "Pakai {ticker} di dalam URL agar disubstitusi per emiten \u2014 penerbitnya yang mencari.",
  "admin.news.ticker": "Khusus emiten",
  "admin.news.tickerHint":
    "Kosongkan agar feed dibaca untuk semua emiten dan disaring per kode dan nama perusahaan.",
  "admin.news.templated": "per emiten",
  "admin.news.templatedNote":
    "URL ini memuat {ticker}, jadi feed-nya sudah spesifik per emiten. Hasilnya tidak " +
    "disaring lagi.",
  "admin.news.suggestions": "Titik awal",
  "admin.news.off": "nonaktif",
  "admin.news.test": "Uji",
  "admin.news.enable": "Aktifkan",
  "admin.news.disable": "Nonaktifkan",
  "admin.news.remove": "Hapus",
  "admin.news.removeTitle": "Hapus sumber",
  "admin.news.removeWarning":
    "Hapus {name}? Berita yang sudah tersimpan tetap ada; hanya sumbernya yang berhenti dibaca.",
  "admin.news.neverRead": "Belum pernah dibaca.",
  "admin.news.lastOk": "{count} entri, terakhir dibaca {when}",
  "admin.news.lastFailed": "Gagal dibaca {when}",
  "admin.news.failureStreak": "{count} kegagalan berturut-turut",
  "admin.news.testTitle": "Uji {name}",
  "admin.news.testOk": "Feed terbaca \u2014 {count} entri.",
  "admin.news.testNewest": "Terbaru: {when}",
  "admin.news.testEmpty": "Feed valid tapi kosong. Periksa apakah URL-nya benar.",
  "admin.news.testFailed": "Feed tidak bisa dibaca.",
  "admin.news.caveat":
    "Judul dan ringkasan diambil apa adanya dari penerbit. Feed umum disaring dengan " +
    "mencocokkan kode emiten dan nama perusahaan, sehingga artikel yang hanya menyebut " +
    "julukan bisa terlewat.",

  "admin.tab.queue": "Antrean",
  "admin.tab.budget": "Biaya AI",
  "admin.tab.audit": "Jejak audit",

  "admin.window": "Jendela",
  "admin.windowDays": "{days} hari",
  "admin.generatedAt": "Dihasilkan {time}",
  "admin.attention": "Perlu perhatian",
  "admin.attentionNone": "Tidak ada yang perlu perhatian.",
  "admin.inventory": "Inventaris",
  "admin.ingestion": "Aliran data",
  "admin.aiUsage": "Pemakaian AI",
  "admin.byAgent": "Per agen",
  "admin.agent": "Agen",
  "admin.calls": "Panggilan",
  "admin.tokens": "Token",
  "admin.cost": "Biaya",
  "admin.totalTokens": "Total token",
  "admin.totalCalls": "Total panggilan",
  "admin.estimatedCost": "Perkiraan biaya",
  "admin.successRate": "Tingkat keberhasilan",
  "admin.runs": "Pengambilan",
  "admin.failedRuns": "Gagal",
  "admin.barsIngested": "Bar tersimpan",
  "admin.barsRejected": "Bar ditolak",
  "admin.lastRun": "Terakhir dijalankan",
  "admin.recentFailures": "Kegagalan terakhir",
  "admin.noFailures": "Tidak ada",
  "admin.neverRun": "Belum pernah",
  "admin.users": "Pengguna",
  "admin.assets": "Emiten",
  "admin.priceBars": "Bar harga",
  "admin.newsItems": "Berita",
  "admin.analyses": "Analisis",
  "admin.recommendations": "Rekomendasi",
  "admin.activeSchedules": "Jadwal aktif",
  "admin.providersActive": "Provider aktif",
  "admin.providersRegistered": "Adapter terdaftar",
  "admin.providerNote":
    "Mengganti provider adalah perubahan konfigurasi, bukan perubahan kode (FR-07). " +
    "Daftar ini menunjukkan kedua sisinya: apa yang tersedia, dan mana yang dipakai.",

  "admin.queue.depth": "Kedalaman antrean",
  "admin.queue.types": "Tipe job yang dikenali",
  "admin.queue.leader": "Leader scheduler",
  "admin.queue.noLeader": "Tidak ada",
  "admin.queue.noLeaderWarning":
    "Tidak ada proses yang menjadwalkan pekerjaan. Ini terlihat persis seperti " +
    "“tidak ada jadwal yang jatuh tempo”, sehingga harus dinyatakan.",
  "admin.queue.expiresAt": "Kedaluwarsa",
  "admin.jobs": "Job terakhir",
  "admin.job.type": "Tipe",
  "admin.job.status": "Status",
  "admin.job.retries": "Percobaan",
  "admin.job.error": "Galat terakhir",
  "admin.job.created": "Dibuat",
  "admin.job.filterAll": "Semua status",
  "admin.jobsEmpty": "Belum ada job.",

  "admin.budget.spent": "Terpakai",
  "admin.budget.ceiling": "Plafon harian",
  "admin.budget.utilisation": "Pemakaian",
  "admin.budget.state": "Status",
  "admin.budget.windowStart": "Sejak",
  "admin.budget.noCeiling": "Tanpa plafon",

  "admin.audit.actor": "Pelaku",
  "admin.audit.action": "Aksi",
  "admin.audit.entity": "Entitas",
  "admin.audit.when": "Waktu",
  "admin.audit.filterEntity": "Saring entitas",
  "admin.audit.empty": "Belum ada catatan audit.",
  "admin.audit.changes": "Perubahan",

  // --- notifications -----------------------------------------------------
  // The subject and body come from the server already written. What lives here
  // is the chrome around them, plus a label per event so the panel can group
  // without parsing the sentence.
  // The body is composed here, not read from the server's `message`. A stored
  // sentence is written once in one language and cannot follow a switch the
  // reader makes afterwards; `context` carries the facts, so both languages
  // describe the same stored event. `message` remains the fallback for an
  // event this build does not recognise.
  "notif.body.analysis_ready": "Analisis {ticker} selesai — {agents} agen melapor.",
  "notif.body.monitoring_alert": "Pantauan menemukan {count} hal pada {tickers}.",

  "toast.translationReady": "Terjemahan siap",
  "toast.translationReadyFor": "Analisis {ticker} kini tersedia dalam dua bahasa.",
  "notif.title": "Notifikasi",
  "notif.open": "Buka notifikasi",
  "notif.unread": "{count} belum dibaca",
  "notif.empty": "Belum ada notifikasi.",
  "notif.emptyHint":
    "Notifikasi muncul saat sebuah analisis selesai atau pantauan menemukan sesuatu.",
  "notif.mute": "Matikan suara notifikasi",
  "notif.unmute": "Nyalakan suara notifikasi",
  "notif.markRead": "Tandai sudah dibaca",
  "notif.markAllRead": "Tandai semua",
  "notif.showRead": "Tampilkan yang sudah dibaca",
  "notif.viewAll": "Lihat semua",
  "notif.openAnalysis": "Buka analisis",
  "notif.openAlerts": "Buka pantauan",
  // Rendered from `context`, never from the message text - the stance travels
  // as data, and the panel shows it beside a link to where the reasoning is.
  "notif.stance": "Sikap",
  "notif.confidence": "Keyakinan",

  "notif.event.analysis_ready": "Analisis",
  "notif.event.monitoring_alert": "Pantauan",
  "notif.event.recommendation_updated": "Rekomendasi",
  "notif.event.news_ingested": "Berita",
  "notif.event.schedule_needs_attention": "Jadwal",
  "notif.event.ingestion_failed": "Pengambilan data",
  "notif.event.budget_threshold_reached": "Anggaran AI",
  "notif.event.report_ready": "Laporan",
  "notif.event.unknown": "Sistem",

  // --- generic -----------------------------------------------------------
  "common.loading": "Memuat…",
  "common.error": "Terjadi kesalahan.",
  "common.retry": "Coba lagi",
  "common.cancel": "Batal",
  "common.delete": "Hapus",
  "common.save": "Simpan",
  "common.saving": "Menyimpan…",
  "common.close": "Tutup",
  "common.search": "Cari",
  "common.none": "—",
  "common.optional": "opsional",
  "common.required": "Wajib diisi",
} as const;

export type MessageKey = keyof typeof id;

export const en: Record<MessageKey, string> = {
  "app.name": "AI Investment Decision Support",
  "app.shortName": "AIDSS",
  "app.tagline": "A decision-support tool — not a trading bot",

  "export.pdf": "Export PDF",
  "export.entry": "Entry price",
  "export.generated": "Generated",
  "export.timeframe": "Timeframe",
  "export.agents": "What each agent found",
  "export.page": "page",
  "pager.none": "Nothing to show",
  "pager.range": "{first}–{last} of {total}",
  "pager.perPage": "Per page",
  "pager.previous": "Previous",
  "pager.next": "Next",
  "admin.tab.settings": "Settings",
  "admin.tab.providers": "AI providers",
  "admin.users.create": "+ Create account",
  "admin.users.createTitle": "Create an account",
  "admin.users.createHint": "For when registration is closed, or to create a second admin.",
  "admin.users.created": "Account created",
  "admin.settings.title": "Platform settings",
  "admin.settings.registration": "Registration open",
  "admin.settings.registrationHint": "When closed, only an admin can create accounts. The first account on an empty instance is always allowed.",
  "admin.settings.newsCron": "News sweep schedule (cron)",
  "admin.settings.newsCronHint": "Empty turns it off. Read in exchange time (WIB). Example: 0 */2 * * *",
  "admin.settings.saved": "Settings saved",
  "admin.settings.caveat": "Closing registration does not affect existing accounts. The cron is read in exchange time (WIB), and a change takes effect on the next scheduler tick.",
  "admin.providers.title": "AI providers",
  "admin.providers.add": "+ Add provider",
  "admin.providers.empty": "No providers configured.",
  "admin.providers.emptyHint": "With none, the platform uses the provider from the environment. Add one here to change models without redeploying.",
  "admin.providers.name": "Name",
  "admin.providers.model": "Model",
  "admin.providers.role": "Role",
  "admin.providers.priority": "Priority",
  "admin.providers.priorityHint": "Lower is tried first in the fallback chain.",
  "admin.providers.baseUrl": "Base URL",
  "admin.providers.apiKey": "API key",
  "admin.providers.apiKeyKeep": "Leave empty to keep the stored key. Type a space then clear it to remove the key.",
  "admin.providers.apiKeyStored": "Stored key: {hint}",
  "admin.providers.timeout": "Timeout (seconds)",
  "admin.providers.selfHosted": "Self-hosted inference",
  "admin.providers.selfHostedHint": "Decides whether personal financial data may be sent here.",
  "admin.providers.costIn": "Cost per 1K input tokens",
  "admin.providers.costOut": "Cost per 1K output tokens",
  "admin.providers.test": "Test",
  "admin.providers.testOk": "Answered in {ms} ms",
  "admin.providers.active": "Active",
  "admin.providers.caveat": "Keys are stored encrypted and never returned by the API. Changing AIDSS_JWT_SECRET makes stored keys unreadable and they must be re-entered.",
  "nav.group.research": "Research",
  "nav.group.watching": "Watching",
  "nav.group.positions": "Positions",
  "nav.group.administration": "Administration",
  "nav.openMenu": "Open menu",
  "admin.tab.issuers": "Issuers",
  "admin.issuers.title": "Listed-company directory",
  "admin.issuers.sync": "Sync from IDX",
  "admin.issuers.syncQueued": "Refreshing the directory",
  "admin.issuers.saved": "Aliases saved",
  "admin.issuers.searchPlaceholder": "Search a code or company name…",
  "admin.issuers.listedOnly": "Listed only",
  "admin.issuers.empty": "The directory is empty.",
  "admin.issuers.emptyHint": "Sync from IDX so news tagging has a list of companies to match against.",
  "admin.issuers.name": "Name",
  "admin.issuers.sector": "Sub-sector",
  "admin.issuers.aliases": "Aliases",
  "admin.issuers.delisted": "delisted",
  "admin.issuers.edit": "Edit aliases",
  "admin.issuers.automatic": "Automatic (index + derived from the name) — not editable here",
  "admin.issuers.extraAliases": "Extra aliases",
  "admin.issuers.extraHint": "One per line. Avoid a single common word: it will tag hundreds of unrelated stories.",
  "admin.issuers.syncedAt": "Synced {when}",
  "admin.issuers.caveat": "Aliases match on word boundaries, case-insensitively. Ticker codes match case-sensitively, because BANK and LABA are also ordinary Indonesian words.",
  "nav.watchlist": "Watchlist",
  "nav.portfolio": "Portfolio",
  "nav.journal": "Journal",
  "nav.chat": "Ask AI",
  "nav.signOut": "Sign out",
  "nav.language": "Language",

  "disclaimer.short": "Informational. Not investment advice.",
  "disclaimer.long":
    "Everything here is informational and is not investment advice. This platform " +
    "cannot place orders, is not connected to any broker, and executes nothing. " +
    "Every decision, and its risk, is yours.",
  "disclaimer.title": "A decision-support tool, not a trading bot",

  "auth.signIn": "Sign in",
  "auth.signUp": "Sign up",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.fullName": "Full name",
  "auth.noAccount": "No account yet?",
  "auth.haveAccount": "Already have an account?",
  "auth.signingIn": "Signing in…",
  "auth.signingUp": "Signing up…",
  "auth.failed": "Wrong email or password.",
  "auth.registerFailed": "Registration failed.",
  "auth.sessionExpired": "Your session ended. Please sign in again.",
  "auth.passwordHint": "At least 10 characters.",

  "login.lede":
    "Multi-agent analysis of IDX issuers, with the reasoning written out in full - " +
    "including the evidence against it.",
  "login.point1.title": "Every stance carries its counter-argument",
  "login.point1.body":
    "A recommendation with no conflicting factors is rejected before it is stored. What " +
    "you read always contains the other side.",
  "login.point2.title": "Confidence is calculated, not claimed",
  "login.point2.body":
    "The figure comes from evidence coverage, agreement between agents, and how balanced " +
    "they are - never from the model's opinion of itself.",
  "login.point3.title": "Delayed data says it is delayed",
  "login.point3.body":
    "The free sources run about fifteen minutes behind. Every observation records its own " +
    "freshness rather than implying one it does not have.",
  "login.constraint":
    "This platform cannot place orders, is not connected to any broker, and executes " +
    "nothing. Every decision, and its risk, is yours.",
  "login.welcomeBack": "Welcome back",
  "login.welcomeBackHint": "Sign in to continue.",
  "login.createAccount": "Create an account",
  "login.createAccountHint": "Free, and your watchlist is yours alone.",


  "watchlist.title": "Watchlist",
  "watchlist.empty": "Your watchlist is empty.",
  "watchlist.emptyHint": "Add a ticker to start following it.",
  "watchlist.add": "Add ticker",
  "watchlist.addPlaceholder": "Ticker, e.g. BBCA",
  "watchlist.note": "Note",
  "watchlist.notePlaceholder": "Why are you watching this one? (optional)",
  "watchlist.remove": "Remove",
  "watchlist.added": "Added",
  "watchlist.adding": "Adding…",
  "watchlist.addFailed": "Could not add that ticker.",
  "watchlist.confirmRemove": "Remove {ticker} from {category}?",

  "watchlist.category": "Category",
  "watchlist.categoryPlaceholder": "e.g. Banks, Dividends",
  "watchlist.categoryHint": "Categories are created the first time you use one.",
  "watchlist.categoryEmpty": "This category is empty.",
  "watchlist.allCategories": "All categories",
  "watchlist.move": "Move",
  "watchlist.moveTitle": "Move {ticker}",
  "watchlist.currentCategory": "current",
  "watchlist.moveHint":
    "A ticker sits in one category at a time. Moving it keeps your note.",
  "watchlist.categoryExists": "A category named {name} already exists.",
  "watchlist.sameTickerNote":
    "One ticker may sit in several categories — a bank that pays dividends belongs in both.",
  "watchlist.expandAll": "Expand all",
  "watchlist.collapseAll": "Collapse all",
  "watchlist.newCategory": "+ New category",
  "watchlist.newCategoryName": "Category name",
  "watchlist.createCategory": "+ New category",
  "watchlist.createCategoryTitle": "Create a category",
  "watchlist.create": "Create",
  "watchlist.emptyCategoryHint": "An empty category is fine — fill it whenever you like.",
  "watchlist.rename": "Rename",
  "watchlist.renameTitle": "Rename {name}",
  "watchlist.deleteCategory": "Delete category",
  "watchlist.confirmDeleteCategory":
    "Delete {name}? Its {count} tickers move to Default rather than being removed.",
  "watchlist.categoryActionFailed": "The category action failed.",

  "watchlist.search": "Search",
  "watchlist.searchPlaceholder": "Ticker, company, sector, or your own note…",
  "watchlist.searchHint": "Your notes are searched too — that is where the reason usually lives.",
  "watchlist.searchResults": "{count} results for “{query}”",
  "watchlist.searchNothing": "Nothing matches “{query}”.",
  "watchlist.clearSearch": "Clear search",
  "watchlist.item": "ticker",
  "watchlist.items": "tickers",

  "asset.price": "Price",
  "asset.change": "Change",
  "asset.notFound": "Ticker not found.",
  "asset.notFoundHint": "This ticker is not registered yet. Add it from the watchlist first.",
  "asset.ingest": "Fetch price data",
  "asset.ingesting": "Fetching…",
  "asset.ingestDone": "{count} bars stored.",
  "asset.noCandles": "No price data for this ticker yet.",
  "asset.noCandlesHint": "Fetch price data first, and indicators will be computed.",

  "tab.chart": "Chart",
  "tab.indicators": "Indicators",
  "tab.fundamentals": "Fundamentals",
  "tab.analysis": "Analysis",
  "tab.news": "News",

  "timeframe.label": "Timeframe",

  "indicators.title": "Technical indicators",
  "indicators.empty": "No indicators computed yet.",
  "indicators.emptyHint": "Fetch price data first — indicators are computed from stored candles.",
  "indicators.asOf": "As of {date}",
  "indicators.bars": "Bars",
  "indicators.lastClose": "Last close",
  "indicators.structure": "Market structure",
  "indicators.structure.ranging": "Ranging",
  "indicators.structure.uptrend": "Uptrend",
  "indicators.structure.downtrend": "Downtrend",
  "indicators.levels": "Support & resistance",
  "indicators.support": "Support",
  "indicators.resistance": "Resistance",
  "indicators.breakout": "Breakout",
  "indicators.breakout.direction": "Direction",
  "indicators.breakout.none": "None",
  "indicators.breakout.up": "Up",
  "indicators.breakout.down": "Down",
  "indicators.breakout.level": "Level",
  "indicators.breakout.lookback": "Window",
  "indicators.breakoutNote":
    "The breakout window excludes the current bar, so a signal does not appear mid-session " +
    "and vanish again by the close.",
  "indicators.features": "Derived features",
  "indicators.levelsNote":
    "Levels are computed from past prices, not targets. They mark where price has turned " +
    "before, not where it will turn.",

  "fundamentals.title": "Fundamental data",
  "fundamentals.empty": "No fundamental data stored yet.",
  "fundamentals.emptyHint":
    "Fetch fundamentals for this ticker, or the provider may not cover it.",
  "fundamentals.ingest": "Fetch fundamentals",
  "fundamentals.metric": "Metric",
  "fundamentals.value": "Value",
  "fundamentals.period": "Period",
  "fundamentals.source": "Source",
  "fundamentals.basis": "Basis",
  "fundamentals.basis.ytd": "Year to date",
  "fundamentals.basis.annual": "Annual",
  "fundamentals.basis.quarterly": "Quarterly",
  "fundamentals.basis.ttm": "Trailing 12 months",
  "fundamentals.basisNote":
    "Year-to-date figures cover part of a fiscal year, not a whole one. " +
    "Comparing them against annual figures is an easy mistake to make.",

  "analysis.title": "AI analysis",
  "analysis.run": "Run analysis",
  "analysis.running": "Analysing…",
  "analysis.runningHint": "Several agents run in sequence. This can take a while.",
  "analysis.empty": "No analysis for this ticker yet.",
  "analysis.failed": "The analysis failed.",
  "analysis.history": "History",
  "analysis.agentsRan": "Agents that ran",
  "analysis.agentFindings": "What each agent found",
  "analysis.signals": "Signals",
  "analysis.watchItems": "Watch items",
  "analysis.disagreements": "Where the agents disagreed",
  "analysis.noAgentTranslation":
    "The agent findings below exist only in their original language - this analysis ran " +
    "before per-agent translations were stored. Run the analysis again to get both. " +
    "(The recommendation further down still follows this switch.)",
  "analysis.skipped": "Skipped",
  "analysis.agentFailed": "Failed",
  "analysis.skippedNote":
    "A skipped agent says why. It lowers evidence coverage, and therefore lowers confidence.",

  "rec.title": "Recommendation",
  "rec.label.buy": "Buy",
  "rec.label.sell": "Sell",
  "rec.label.hold": "Hold",
  "rec.label.watchlist": "Watch",
  "rec.label.strong_buy": "Strong buy",
  "rec.label.strong_sell": "Strong sell",

  "rec.confidence": "Confidence",
  "rec.confidenceBasis": "How it was calculated",
  "rec.confidenceExplain":
    "Computed from evidence coverage, agreement between agents, and the balance of " +
    "argument — not a number the model reported about itself.",
  "rec.modelSelfReported": "Model's own confidence",
  "rec.modelSelfReportedNote":
    "Shown for comparison only. This is precisely the number that is not used.",

  "rec.reasoning": "Reasoning",
  "rec.supporting": "Supporting factors",
  "rec.conflicting": "Conflicting factors",
  "rec.risks": "Risks",
  "rec.bullish": "Bullish scenario",
  "rec.bearish": "Bearish scenario",
  "rec.support": "Support",
  "rec.resistance": "Resistance",
  "rec.target": "Target price",
  "rec.stop": "Suggested stop",
  "rec.horizon": "Time horizon",
  "rec.method": "Method",
  "rec.noTarget": "None",
  "rec.noTargetReason":
    "A neutral stance has no directional basis for a target. Inventing one would " +
    "defeat the point of the stance.",
  "rec.provenance": "Provenance",
  "rec.model": "Model",
  "rec.promptVersion": "Prompt version",
  "rec.attempts": "Attempts",

  "rec.components": "How the figure was built",
  "rec.component.coverage": "Evidence coverage",
  "rec.component.coverageWhat": "How many evidence sources were actually available",
  "rec.component.agreement": "Directional agreement",
  "rec.component.agreementWhat": "How far the agents that ran pointed the same way",
  "rec.component.balance": "Evidence balance",
  "rec.component.balanceWhat": "Whether counter-evidence was named at all",
  "rec.signals": "Per-agent signals",
  "rec.signal.agent": "Agent",
  "rec.signal.direction": "Direction",
  "rec.signal.sufficiency": "Data sufficiency",
  "rec.direction.bullish": "Bullish",
  "rec.direction.bearish": "Bearish",
  "rec.direction.neutral": "Neutral",
  "rec.rawBasis": "Raw data",

  "portfolio.title": "Portfolio",
  "portfolio.empty": "No holdings recorded yet.",
  "portfolio.emptyHint": "Add holdings manually to see the analysis.",
  "portfolio.addHolding": "Add holding",
  "portfolio.ticker": "Ticker",
  "portfolio.quantity": "Quantity",
  "portfolio.avgPrice": "Average price",
  "portfolio.value": "Value",
  "portfolio.weight": "Weight",
  "portfolio.pnl": "Profit / loss",
  "portfolio.totalValue": "Total value",
  "portfolio.analyse": "Analyse portfolio",
  "portfolio.analysing": "Analysing…",
  "portfolio.concentration": "Concentration",
  "portfolio.unpriced": "Unpriced",
  "portfolio.unpricedNote":
    "Holdings with no stored price are not valued, and are flagged — not counted as zero.",
  "portfolio.manualOnly":
    "Holdings are entered manually. This platform is not connected to any broker.",
  "portfolio.remove": "Remove",

  "journal.title": "Investment journal",
  "journal.empty": "No entries yet.",
  "journal.emptyHint": "Record why you decided something, so you can review it later.",
  "journal.add": "Add entry",
  "journal.content": "Decision",
  "journal.contentPlaceholder": "What did you decide, and why?",
  "journal.note": "Note",
  "journal.tags": "Tags",
  "journal.reflection": "Ask for a reflection",
  "journal.reflecting": "Writing a reflection…",
  "journal.summary": "Summary",
  "journal.delete": "Delete",

  "chat.title": "Ask AI",
  "chat.placeholder": "Ask something about the market or a ticker…",
  "chat.send": "Send",
  "chat.sending": "Sending…",
  "chat.empty": "No conversation yet.",
  "chat.emptyHint": "Ask a question to start.",
  "chat.you": "You",
  "chat.assistant": "AI",

  "tab.strategy": "Strategy",
  "strategy.title": "What this means for your position",
  "strategy.empty": "No stored recommendation for this ticker yet.",
  "strategy.emptyHint":
    "Run an analysis first — the strategy is derived from one, never produced independently.",
  "strategy.notHolding": "If you do not hold it",
  "strategy.holding": "If you hold it",
  "strategy.language": "Recommendation language",
  "strategy.bothNote":
    "Both are shown whatever you hold. An asset worth keeping but not worth buying today " +
    "is a real and common situation, and showing only your own side would hide it.",
  "strategy.conditions": "Conditions",
  "strategy.invalidatedIf": "Invalidated if",
  "strategy.levels": "Reference levels",

  "stance.entry_candidate": "Entry candidate",
  "stance.wait_for_level": "Wait for a level",
  "stance.no_entry_basis": "No basis to enter",
  "stance.avoid": "Avoid",
  "stance.maintain": "Maintain",
  "stance.accumulate_candidate": "Candidate to add",
  "stance.trim_candidate": "Candidate to trim",
  "stance.exit_candidate": "Candidate to exit",

  "nav.picks": "Stock picks",
  "picks.title": "Stock picks",
  "picks.horizon": "Horizon",
  "picks.horizonNote":
    "The horizon names the window each condition is conventionally read over — not how " +
    "long anything will take to happen.",
  "picks.empty": "No ticker meets these conditions.",
  "picks.emptyHint": "Loosen the conditions, or there may not be enough price history yet.",
  "picks.considered": "{count} tickers considered",
  "picks.insufficient": "{count} skipped for want of price history",
  "picks.score": "Score",
  "picks.met": "Conditions met",
  "picks.unmet": "Not met",
  "picks.watchlistOnly": "My watchlist only",
  "picks.nearLimitOnly": "Near the auto-reject ceiling only",
  "picks.limitProximity": "Auto-reject band used",
  "picks.limitCeiling": "Session ceiling",
  "picks.notAForecast": "This is a screen, not a forecast",

  "nav.monitoring": "Monitoring",
  "monitoring.title": "Monitoring & alerts",
  "monitoring.quotes": "Latest observations",
  "monitoring.pollNow": "Refresh now",
  "monitoring.polling": "Refreshing…",
  "monitoring.empty": "Nothing is being monitored yet.",
  "monitoring.emptyHint": "Add a ticker to your watchlist to start following it.",
  "monitoring.neverPolled": "Never observed",
  "monitoring.delayed": "Delayed",
  "monitoring.delayedNote":
    "The free sources are delayed by roughly 15 minutes. Shown rather than implied — an " +
    "interface presenting a delayed price as current invites decisions on numbers that " +
    "have already moved.",
  "monitoring.observedAt": "Observed",

  "alerts.title": "Alerts",
  "alerts.empty": "No alerts yet.",
  "alerts.emptyHint":
    "Alerts appear when a level is crossed, a stance changes, or the auto-reject band is nearly used.",
  "alerts.unacknowledgedOnly": "Unread only",
  "news.empty": "No news for this ticker yet.",
  "news.emptyHint": "Articles arrive when the RSS sources are read. An admin can press “Fetch all” on the admin page.",
  "news.alsoAbout": "Also about:",
  "news.matched.ticker_code": "matched on the ticker code",
  "news.matched.company_name": "matched on the company name",
  "news.matched.alias": "matched on a well-known name",
  "alerts.acknowledge": "Mark read",
  "alerts.selectAll": "Select all shown",
  "alerts.selectOne": "Select the {ticker} alert",
  "alerts.selectedCount": "{count} selected",
  "alerts.clearSelection": "Clear selection",
  "alerts.readSelected": "Mark read",
  "alerts.deleteSelected": "Delete selected",
  "alerts.readAll": "Mark all read",
  "alerts.deleteAll": "Delete all",
  "alerts.batchDone": "{count} alerts updated",
  "alerts.deleteSelectedTitle": "Delete the selected alerts?",
  "alerts.deleteSelectedBody": "{count} alerts will be permanently removed. This cannot be undone.",
  "alerts.deleteAllTitle": "Delete every alert?",
  "alerts.deleteAllBody": "Your whole alert history will be permanently removed, including alerts you have not read. This cannot be undone.",
  "alerts.acknowledged": "Read",
  "alerts.note":
    "An alert states what happened, not what to do about it. The stance and its confidence " +
    "live on the analysis screen, with the factors arguing against it.",
  "alert.level_approached": "Level approached",
  "alert.level_crossed": "Level crossed",
  "alert.stance_changed": "Stance changed",
  "alert.limit_proximity": "Near the auto-reject ceiling",
  "alert.suggested_stop_reached": "Suggested stop reached",
  "alert.unusual_move": "Unusual move",
  "alert.stanceFrom": "From",
  "alert.stanceTo": "To",

  "translate.show": "Show in Indonesian",
  "translate.showOriginal": "Show the original",
  "translate.working": "Translating…",
  "translate.failed": "The translation failed.",
  "translate.machineNote":
    "A machine translation of the analysis above. The original remains authoritative — " +
    "labels, prices, and confidence are not translated.",

  "nav.admin": "Admin",
  "admin.title": "Admin dashboard",
  "admin.forbidden": "This page is for administrators.",
  "admin.forbiddenHint":
    "New accounts are investors. Promotion happens from a shell rather than the API — " +
    "an endpoint that hands out the admin role is a privilege-escalation surface. Run: " +
    "python -m aidss.cli grant-admin {email}",

  "admin.tab.overview": "Overview",
  "admin.tab.users": "Users",
  "admin.tab.news": "News sources",

  "admin.users.title": "Manage users",
  "admin.users.selectAll": "Select all",
  "admin.users.select": "Select {email}",
  "admin.users.selected": "{count} accounts selected",
  "admin.users.clearSelection": "Clear",
  "admin.users.appliesTo": "Applies to:",
  "admin.users.batchProgress": "Processing {done} of {total}...",
  "admin.users.batchResult": "Result",
  "admin.users.batchSummary": "{done} of {total} accounts processed.",
  "admin.users.batchFailed": "{count} failed:",
  "admin.users.suspendTitleMany": "Suspend {count} accounts",
  "admin.users.banTitleMany": "Ban {count} accounts",
  "admin.users.roleTitleMany": "Role for {count} accounts",
  "admin.users.reasonNoteMany":
    "The same reason is shown to every one of these account holders when they sign in.",
  "admin.users.deleteWarningMany":
    "Delete {count} accounts? Each one's watchlists, portfolios, and journal go with it. " +
    "This cannot be undone.",
  "admin.users.typeCount": "Type {count} to confirm",

  "admin.users.searchPlaceholder": "Search email or name...",
  "admin.users.empty": "No accounts match.",
  "admin.users.account": "Account",
  "admin.users.role": "Role",
  "admin.users.status": "Status",
  "admin.users.since": "Registered",
  "admin.users.you": "your account",
  "admin.users.changeRole": "Role",
  "admin.users.suspend": "Suspend",
  "admin.users.ban": "Ban",
  "admin.users.reinstate": "Reinstate",
  "admin.users.delete": "Delete",
  "admin.users.caveat":
    "Suspend and ban can be undone; delete cannot. Deleting an account also deletes " +
    "its watchlists, portfolios, and journal.",

  "admin.users.status.active": "Active",
  "admin.users.status.suspended": "Suspended",
  "admin.users.status.banned": "Banned",
  "admin.users.statusExpired": "Suspension expired",
  "admin.users.until": "until {when}",

  "admin.users.role.viewer": "Viewer \u2014 read only",
  "admin.users.role.investor": "Investor \u2014 manages their own data",
  "admin.users.role.admin": "Admin \u2014 manages the system",
  "admin.users.roleTitle": "Role for {email}",
  "admin.users.roleNote":
    "Viewer reads. Investor manages their own data. Admin manages providers, the " +
    "queue, and accounts.",
  "admin.users.stepDownWarning":
    "You are demoting your own account. No endpoint can restore it \u2014 recovery is a " +
    "shell command on the server.",

  "admin.users.suspendTitle": "Suspend {email}",
  "admin.users.banTitle": "Ban {email}",
  "admin.users.banNote":
    "A ban is indefinite and is never lifted by the clock. The account and its history " +
    "are kept, and an admin can still reinstate it.",
  "admin.users.duration": "Duration",
  "admin.users.days": "{count} days",
  "admin.users.indefinite": "Indefinite",
  "admin.users.reason": "Reason",
  "admin.users.reasonPlaceholder": "e.g. Under review",
  "admin.users.reasonNote": "This reason is shown to the account holder when they sign in.",
  "admin.users.deleteTitle": "Delete account",
  "admin.users.deleteWarning":
    "Delete {email}? Their watchlists, portfolios, and journal go with it. This cannot " +
    "be undone \u2014 use ban if you want to be able to reverse it.",

  "admin.news.title": "News sources (RSS/Atom)",
  "admin.news.searchPlaceholder": "Search name, URL, or ticker...",
  "admin.news.filter": "Filter",
  "admin.news.filter.all": "All",
  "admin.news.filter.active": "Active",
  "admin.news.filter.off": "Off",
  "admin.news.filter.failing": "Failing",
  "admin.news.noMatches": "No sources match.",
  "admin.news.clearFilters": "Clear filters",
  "admin.news.add": "+ Add source",
  "admin.news.sweep": "Fetch all",
  "admin.news.sweeping": "Fetching…",
  "admin.news.sweepHint": "Read every active feed now and store what it carries",
  "admin.news.sweepQueued": "Reading the news sources",
  "admin.news.issuerSync": "Sync issuers",
  "admin.news.issuerSyncHint": "Refresh the IDX listed-company directory that news tagging matches against",
  "admin.news.issuerSyncQueued": "Refreshing the issuer directory",
  "admin.news.addTitle": "Add a news source",
  "admin.news.edit": "Edit",
  "admin.news.editTitle": "Edit {name}",
  "admin.news.empty": "No news sources yet.",
  "admin.news.emptyHint":
    "With none configured, news ingestion has nowhere to look and schedules report failure.",
  "admin.news.name": "Name",
  "admin.news.namePlaceholder": "e.g. Google News \u2014 per ticker",
  "admin.news.url": "Feed URL",
  "admin.news.urlHint":
    "Put {ticker} in the URL to have it substituted per asset \u2014 the publisher searches.",
  "admin.news.ticker": "Bind to one ticker",
  "admin.news.tickerHint":
    "Leave empty to read this feed for every asset, filtered on the code and company name.",
  "admin.news.templated": "per ticker",
  "admin.news.templatedNote":
    "This URL contains {ticker}, so the feed is already per-asset. Its entries are not " +
    "filtered again.",
  "admin.news.suggestions": "Starting points",
  "admin.news.off": "off",
  "admin.news.test": "Test",
  "admin.news.enable": "Enable",
  "admin.news.disable": "Disable",
  "admin.news.remove": "Remove",
  "admin.news.removeTitle": "Remove source",
  "admin.news.removeWarning":
    "Remove {name}? Articles already stored stay; only the source stops being read.",
  "admin.news.neverRead": "Never read.",
  "admin.news.lastOk": "{count} entries, last read {when}",
  "admin.news.lastFailed": "Failed {when}",
  "admin.news.failureStreak": "{count} consecutive failures",
  "admin.news.testTitle": "Test {name}",
  "admin.news.testOk": "Feed read \u2014 {count} entries.",
  "admin.news.testNewest": "Newest: {when}",
  "admin.news.testEmpty": "Valid feed, but empty. Check the URL is the one you meant.",
  "admin.news.testFailed": "The feed could not be read.",
  "admin.news.caveat":
    "Headlines and summaries are taken from the publisher as written. General feeds are " +
    "filtered by matching the ticker code and company name, so an article that only uses " +
    "a nickname can be missed.",

  "admin.tab.queue": "Queue",
  "admin.tab.budget": "AI spend",
  "admin.tab.audit": "Audit log",

  "admin.window": "Window",
  "admin.windowDays": "{days} days",
  "admin.generatedAt": "Generated {time}",
  "admin.attention": "Needs attention",
  "admin.attentionNone": "Nothing needs attention.",
  "admin.inventory": "Inventory",
  "admin.ingestion": "Data flow",
  "admin.aiUsage": "AI usage",
  "admin.byAgent": "By agent",
  "admin.agent": "Agent",
  "admin.calls": "Calls",
  "admin.tokens": "Tokens",
  "admin.cost": "Cost",
  "admin.totalTokens": "Total tokens",
  "admin.totalCalls": "Total calls",
  "admin.estimatedCost": "Estimated cost",
  "admin.successRate": "Success rate",
  "admin.runs": "Runs",
  "admin.failedRuns": "Failed",
  "admin.barsIngested": "Bars ingested",
  "admin.barsRejected": "Bars rejected",
  "admin.lastRun": "Last run",
  "admin.recentFailures": "Recent failures",
  "admin.noFailures": "None",
  "admin.neverRun": "Never",
  "admin.users": "Users",
  "admin.assets": "Assets",
  "admin.priceBars": "Price bars",
  "admin.newsItems": "News items",
  "admin.analyses": "Analyses",
  "admin.recommendations": "Recommendations",
  "admin.activeSchedules": "Active schedules",
  "admin.providersActive": "Active providers",
  "admin.providersRegistered": "Registered adapters",
  "admin.providerNote":
    "Swapping a provider is a configuration change, never a code change (FR-07). This " +
    "shows both halves: what is available, and what is selected.",

  "admin.queue.depth": "Queue depth",
  "admin.queue.types": "Recognised job types",
  "admin.queue.leader": "Scheduler leader",
  "admin.queue.noLeader": "None",
  "admin.queue.noLeaderWarning":
    "No process is scheduling work. This looks exactly like “nothing is due”, which is " +
    "why it has to be stated.",
  "admin.queue.expiresAt": "Expires",
  "admin.jobs": "Recent jobs",
  "admin.job.type": "Type",
  "admin.job.status": "Status",
  "admin.job.retries": "Attempts",
  "admin.job.error": "Last error",
  "admin.job.created": "Created",
  "admin.job.filterAll": "All statuses",
  "admin.jobsEmpty": "No jobs yet.",

  "admin.budget.spent": "Spent",
  "admin.budget.ceiling": "Daily ceiling",
  "admin.budget.utilisation": "Utilisation",
  "admin.budget.state": "State",
  "admin.budget.windowStart": "Since",
  "admin.budget.noCeiling": "No ceiling",

  "admin.audit.actor": "Actor",
  "admin.audit.action": "Action",
  "admin.audit.entity": "Entity",
  "admin.audit.when": "When",
  "admin.audit.filterEntity": "Filter entity",
  "admin.audit.empty": "No audit entries yet.",
  "admin.audit.changes": "Changes",

  "notif.body.analysis_ready": "Analysis for {ticker} finished — {agents} agent(s) reporting.",
  "notif.body.monitoring_alert": "Monitoring observed {count} thing(s) on {tickers}.",

  "toast.translationReady": "Translation ready",
  "toast.translationReadyFor": "The {ticker} analysis is now available in both languages.",
  "notif.title": "Notifications",
  "notif.open": "Open notifications",
  "notif.unread": "{count} unread",
  "notif.empty": "No notifications yet.",
  "notif.emptyHint":
    "They appear when an analysis finishes or monitoring observes something.",
  "notif.mute": "Mute notification sound",
  "notif.unmute": "Unmute notification sound",
  "notif.markRead": "Mark as read",
  "notif.markAllRead": "Mark all",
  "notif.showRead": "Show read",
  "notif.viewAll": "See all",
  "notif.openAnalysis": "Open analysis",
  "notif.openAlerts": "Open monitoring",
  "notif.stance": "Stance",
  "notif.confidence": "Confidence",

  "notif.event.analysis_ready": "Analysis",
  "notif.event.monitoring_alert": "Monitoring",
  "notif.event.recommendation_updated": "Recommendation",
  "notif.event.news_ingested": "News",
  "notif.event.schedule_needs_attention": "Schedule",
  "notif.event.ingestion_failed": "Ingestion",
  "notif.event.budget_threshold_reached": "AI budget",
  "notif.event.report_ready": "Report",
  "notif.event.unknown": "System",

  "common.loading": "Loading…",
  "common.error": "Something went wrong.",
  "common.retry": "Try again",
  "common.cancel": "Cancel",
  "common.delete": "Delete",
  "common.save": "Save",
  "common.saving": "Saving…",
  "common.close": "Close",
  "common.search": "Search",
  "common.none": "—",
  "common.optional": "optional",
  "common.required": "Required",
};

export const locales = { id, en } as const;
export type Locale = keyof typeof locales;
