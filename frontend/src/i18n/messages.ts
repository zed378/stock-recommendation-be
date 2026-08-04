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
