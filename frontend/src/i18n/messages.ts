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
  "watchlist.moveTo": "Pindahkan {ticker} ke kelompok mana?",
  "watchlist.sameTickerNote":
    "Satu emiten boleh berada di lebih dari satu kelompok — bank yang membagi dividen " +
    "masuk ke keduanya.",
  "watchlist.expandAll": "Buka semua",
  "watchlist.collapseAll": "Tutup semua",
  "watchlist.newCategory": "+ Buat kelompok baru",
  "watchlist.newCategoryName": "Nama kelompok baru",
  "watchlist.rename": "Ganti nama",
  "watchlist.renamePrompt": "Ganti nama kelompok {name} menjadi:",
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
  "alerts.acknowledge": "Tandai dibaca",
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
  "admin.tab.queue": "Antrean",
  "admin.tab.providers": "Provider",
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

  // --- generic -----------------------------------------------------------
  "common.loading": "Memuat…",
  "common.error": "Terjadi kesalahan.",
  "common.retry": "Coba lagi",
  "common.cancel": "Batal",
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
  "watchlist.moveTo": "Move {ticker} to which category?",
  "watchlist.sameTickerNote":
    "One ticker may sit in several categories — a bank that pays dividends belongs in both.",
  "watchlist.expandAll": "Expand all",
  "watchlist.collapseAll": "Collapse all",
  "watchlist.newCategory": "+ New category",
  "watchlist.newCategoryName": "New category name",
  "watchlist.rename": "Rename",
  "watchlist.renamePrompt": "Rename {name} to:",
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
  "alerts.acknowledge": "Mark read",
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
  "admin.tab.queue": "Queue",
  "admin.tab.providers": "Providers",
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

  "common.loading": "Loading…",
  "common.error": "Something went wrong.",
  "common.retry": "Try again",
  "common.cancel": "Cancel",
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
