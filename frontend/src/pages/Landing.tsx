import { useEffect, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/context";
import { Backdrop } from "@/components/Backdrop";
import { useI18n } from "@/i18n/context";

type SpecimenTab = "deterministic" | "debate" | "stance";
type IssuerKey = "BBCA" | "BMRI" | "TLKM";
type DebateNodeId = "analysts" | "bull" | "bear" | "judge" | "risk";

const SPECIMEN_TABS: readonly SpecimenTab[] = ["deterministic", "debate", "stance"];
const ISSUER_KEYS: readonly IssuerKey[] = ["BBCA", "BMRI", "TLKM"];

interface IssuerSpecimen {
  code: IssuerKey;
  ticker: string;
  name: string;
  sectorId: string;
  sectorEn: string;
  close: string;
  changePct: string;
  kronosBand: string;
  kronosDelta: string;
  atrStop: string;
  support1: string;
  resistance1: string;
  rsi: number;
  adx: number;
  confidence: number;
  stance: "BUY" | "WATCHLIST";
  candles: readonly { o: number; h: number; l: number; c: number }[];
  forecastUpper: readonly number[];
  forecastMid: readonly number[];
  forecastLower: readonly number[];
}

const ISSUER_SPECIMENS: Record<IssuerKey, IssuerSpecimen> = {
  BBCA: {
    code: "BBCA",
    ticker: "BBCA.JK",
    name: "PT Bank Central Asia Tbk",
    sectorId: "Perbankan Korporasi & Transaksi",
    sectorEn: "Corporate & Transaction Banking",
    close: "9,850",
    changePct: "+1.28%",
    kronosBand: "9,720 .. 10,125",
    kronosDelta: "+1.83%",
    atrStop: "9,560",
    support1: "9,625",
    resistance1: "10,125",
    rsi: 56.4,
    adx: 31.2,
    confidence: 0.74,
    stance: "BUY",
    candles: [
      { o: 48, h: 42, l: 55, c: 44 },
      { o: 44, h: 38, l: 49, c: 41 },
      { o: 41, h: 36, l: 47, c: 43 },
      { o: 43, h: 33, l: 45, c: 35 },
      { o: 35, h: 29, l: 40, c: 32 },
      { o: 32, h: 26, l: 37, c: 28 },
      { o: 28, h: 22, l: 33, c: 25 },
    ],
    forecastUpper: [25, 21, 18, 15, 13],
    forecastMid: [25, 23, 21, 19, 18],
    forecastLower: [25, 27, 26, 25, 24],
  },
  BMRI: {
    code: "BMRI",
    ticker: "BMRI.JK",
    name: "PT Bank Mandiri (Persero) Tbk",
    sectorId: "Perbankan Wholesale & Ekosistem BUMN",
    sectorEn: "Wholesale & Commercial Banking",
    close: "6,425",
    changePct: "+0.78%",
    kronosBand: "6,300 .. 6,650",
    kronosDelta: "+1.45%",
    atrStop: "6,175",
    support1: "6,250",
    resistance1: "6,600",
    rsi: 53.8,
    adx: 28.4,
    confidence: 0.71,
    stance: "BUY",
    candles: [
      { o: 52, h: 46, l: 58, c: 49 },
      { o: 49, h: 43, l: 53, c: 45 },
      { o: 45, h: 40, l: 50, c: 47 },
      { o: 47, h: 37, l: 49, c: 39 },
      { o: 39, h: 34, l: 44, c: 36 },
      { o: 36, h: 30, l: 40, c: 33 },
      { o: 33, h: 27, l: 36, c: 29 },
    ],
    forecastUpper: [29, 25, 22, 19, 17],
    forecastMid: [29, 27, 25, 23, 22],
    forecastLower: [29, 31, 30, 29, 28],
  },
  TLKM: {
    code: "TLKM",
    ticker: "TLKM.JK",
    name: "PT Telkom Indonesia (Persero) Tbk",
    sectorId: "Infrastruktur Digital & Telekomunikasi",
    sectorEn: "Digital Infrastructure & Telecom",
    close: "2,890",
    changePct: "+0.35%",
    kronosBand: "2,810 .. 2,980",
    kronosDelta: "+0.69%",
    atrStop: "2,760",
    support1: "2,820",
    resistance1: "2,960",
    rsi: 48.2,
    adx: 22.7,
    confidence: 0.64,
    stance: "WATCHLIST",
    candles: [
      { o: 42, h: 38, l: 49, c: 45 },
      { o: 45, h: 40, l: 51, c: 43 },
      { o: 43, h: 39, l: 48, c: 44 },
      { o: 44, h: 37, l: 47, c: 40 },
      { o: 40, h: 35, l: 45, c: 41 },
      { o: 41, h: 34, l: 44, c: 38 },
      { o: 38, h: 33, l: 42, c: 36 },
    ],
    forecastUpper: [36, 33, 31, 29, 28],
    forecastMid: [36, 35, 34, 33, 32],
    forecastLower: [36, 39, 39, 38, 37],
  },
};

export function Landing() {
  const { user } = useAuth();
  const { locale, setLocale, t } = useI18n();
  const [activeTab, setActiveTab] = useState<SpecimenTab>("deterministic");
  const [selectedIssuer, setSelectedIssuer] = useState<IssuerKey>("BBCA");
  const [activeNode, setActiveNode] = useState<DebateNodeId>("bull");
  const [motionPaused, setMotionPaused] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const specimen = ISSUER_SPECIMENS[selectedIssuer];

  useEffect(() => {
    if (!mobileMenuOpen) return;
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") {
        setMobileMenuOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileMenuOpen]);

  // Choreographed auto-cycle of the hero specimen unless paused or reduced-motion is active.
  useEffect(() => {
    if (motionPaused) return;
    if (
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }
    const timer = window.setInterval(() => {
      setSelectedIssuer((prev) => {
        const idx = ISSUER_KEYS.indexOf(prev);
        return ISSUER_KEYS[(idx + 1) % ISSUER_KEYS.length];
      });
    }, 4800);
    return () => window.clearInterval(timer);
  }, [motionPaused]);

  function handleTabKeyDown(e: KeyboardEvent<HTMLButtonElement>, current: SpecimenTab) {
    const idx = SPECIMEN_TABS.indexOf(current);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      const next = SPECIMEN_TABS[(idx + 1) % SPECIMEN_TABS.length];
      setActiveTab(next);
      document.getElementById(`specimen-tab-${next}`)?.focus();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      const prev = SPECIMEN_TABS[(idx - 1 + SPECIMEN_TABS.length) % SPECIMEN_TABS.length];
      setActiveTab(prev);
      document.getElementById(`specimen-tab-${prev}`)?.focus();
    }
  }

  const primaryHref = user ? "/watchlist" : "/login";
  const primaryLabel = user ? t("landing.cta.openWorkspace") : t("landing.cta.signIn");

  const debateNodes: Record<
    DebateNodeId,
    { label: string; role: string; summary: string; tone: "rise" | "fall" | "watch" | "ink" }
  > = {
    analysts: {
      label: locale === "id" ? "4 Analis Paralel" : "4 Parallel Analysts",
      role: locale === "id" ? "Pasar · Fundamental · Berita · Sentimen" : "Market · Fundamental · News · Sentiment",
      summary: t("landing.debate.step1.detail"),
      tone: "ink",
    },
    bull: {
      label: "Bull Researcher",
      role: locale === "id" ? "Tesis Ekspansi & Katalis" : "Expansion & Catalyst Thesis",
      summary: t("landing.specimen.debate.bull"),
      tone: "rise",
    },
    bear: {
      label: "Bear Researcher",
      role: locale === "id" ? "Uji Tekanan & Valuasi" : "Valuation & Downside Stress Test",
      summary: t("landing.specimen.debate.bear"),
      tone: "fall",
    },
    judge: {
      label: "Research Manager",
      role: locale === "id" ? "Sintesis Bukti Berimbang" : "Balanced Evidence Synthesis",
      summary: t("landing.debate.step2.detail"),
      tone: "ink",
    },
    risk: {
      label: locale === "id" ? "Komite Risiko (3 Sudut)" : "Risk Committee (3 Postures)",
      role: locale === "id" ? "Agresif · Netral · Konservatif" : "Aggressive · Neutral · Conservative",
      summary: t("landing.specimen.debate.risk"),
      tone: "watch",
    },
  };

  // Build SVG polygon and polyline coordinates for the Kronos 5-day forecast band
  const xStart = 205;
  const xStep = 28;
  const upperPts = specimen.forecastUpper.map((y, i) => `${xStart + i * xStep},${y}`);
  const lowerPts = [...specimen.forecastLower]
    .reverse()
    .map((y, i) => `${xStart + (specimen.forecastLower.length - 1 - i) * xStep},${y}`);
  const envelopePolygon = [...upperPts, ...lowerPts].join(" ");
  const midPolyline = specimen.forecastMid.map((y, i) => `${xStart + i * xStep},${y}`).join(" ");

  return (
    <div
      data-motion-paused={motionPaused ? "true" : "false"}
      className="relative min-h-dvh bg-surface text-ink flex flex-col"
    >
      <Backdrop />

      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:bg-ink focus:text-surface focus:px-4 focus:py-2.5 focus:rounded focus:text-sm focus:font-medium"
      >
        {t("landing.skipToMain")}
      </a>

      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur-sm">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <Link
              to="/"
              className="inline-flex items-center gap-2.5 min-h-11 px-1 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              <img
                src="/logo-symbol.svg"
                alt=""
                width={20}
                height={20}
                className="h-5 w-5 shrink-0"
              />
              <span className="font-semibold tracking-tight text-ink">
                {t("app.shortName")}
              </span>
              <span className="hidden sm:inline text-xs font-mono text-muted border-l border-line pl-2.5">
                IDX · IDR SPOT
              </span>
            </Link>

            <nav aria-label="Primary" className="hidden md:flex items-center gap-1">
              <a
                href="#pipeline"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.pipeline")}
              </a>
              <a
                href="#architecture"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.debate")}
              </a>
              <a
                href="#boundaries"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.boundaries")}
              </a>
              <a
                href="#modules"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.modules")}
              </a>
            </nav>
          </div>

          <div className="flex items-center gap-2.5">
            <div
              role="group"
              aria-label={t("nav.language")}
              className="inline-flex items-center rounded border border-faint bg-raised p-0.5"
            >
              {(["id", "en"] as const).map((code) => {
                const active = locale === code;
                return (
                  <button
                    key={code}
                    type="button"
                    onClick={() => setLocale(code)}
                    aria-pressed={active}
                    className={`min-h-10 min-w-10 px-2.5 text-xs font-mono uppercase rounded-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink ${
                      active
                        ? "bg-ink text-surface font-medium"
                        : "text-muted hover:text-ink"
                    }`}
                  >
                    {code}
                  </button>
                );
              })}
            </div>

            <Link
              to={primaryHref}
              className="hidden sm:inline-flex items-center justify-center min-h-11 px-4 rounded bg-rise text-surface text-sm font-semibold hover:bg-rise/90 active:bg-rise/80 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              {primaryLabel}
            </Link>

            <button
              type="button"
              onClick={() => setMobileMenuOpen((prev) => !prev)}
              aria-expanded={mobileMenuOpen}
              aria-controls="landing-mobile-nav"
              className="md:hidden inline-flex items-center justify-center min-h-11 px-3 rounded border border-faint bg-raised text-sm text-ink hover:bg-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              {mobileMenuOpen ? t("landing.nav.closeMenu") : t("landing.nav.menu")}
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <nav
            id="landing-mobile-nav"
            aria-label="Mobile"
            className="md:hidden border-t border-line bg-raised px-4 py-3 flex flex-col gap-1"
          >
            <a
              href="#pipeline"
              onClick={() => setMobileMenuOpen(false)}
              className="min-h-11 flex items-center px-3 rounded text-sm text-ink hover:bg-hover"
            >
              {t("landing.nav.pipeline")}
            </a>
            <a
              href="#architecture"
              onClick={() => setMobileMenuOpen(false)}
              className="min-h-11 flex items-center px-3 rounded text-sm text-ink hover:bg-hover"
            >
              {t("landing.nav.debate")}
            </a>
            <a
              href="#boundaries"
              onClick={() => setMobileMenuOpen(false)}
              className="min-h-11 flex items-center px-3 rounded text-sm text-ink hover:bg-hover"
            >
              {t("landing.nav.boundaries")}
            </a>
            <a
              href="#modules"
              onClick={() => setMobileMenuOpen(false)}
              className="min-h-11 flex items-center px-3 rounded text-sm text-ink hover:bg-hover"
            >
              {t("landing.nav.modules")}
            </a>
            <Link
              to={primaryHref}
              onClick={() => setMobileMenuOpen(false)}
              className="mt-2 min-h-11 flex items-center justify-center px-4 rounded bg-rise text-surface text-sm font-semibold"
            >
              {primaryLabel}
            </Link>
          </nav>
        )}
      </header>

      <main id="main-content" className="relative z-10 flex-1">
        {/* HERO: Asymmetric 6/6 split with framed architectural photography + live interactive Kronos & Stance stage */}
        <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 sm:py-14 lg:py-20 border-b border-line">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
            <div className="lg:col-span-6 flex flex-col">
              <p className="font-mono text-xs tracking-wider uppercase text-rise mb-3">
                {t("landing.hero.coordinate")}
              </p>

              <h1
                className="font-semibold tracking-tight text-ink leading-[1.1] max-w-[22ch]"
                style={{ fontSize: "clamp(1.95rem, 3.3vw + 0.85rem, 3.25rem)" }}
              >
                {t("landing.hero.title")}
              </h1>

              <p className="mt-5 text-base sm:text-lg text-muted leading-relaxed max-w-[58ch]">
                {t("landing.hero.lead")}
              </p>

              {/* Interactive issuer switcher driving the Hero Product Stage */}
              <div className="mt-6">
                <p className="text-xs font-mono uppercase tracking-wider text-muted mb-2">
                  {t("landing.hero.selectIssuer")}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  {ISSUER_KEYS.map((key) => {
                    const item = ISSUER_SPECIMENS[key];
                    const active = selectedIssuer === key;
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => {
                          setSelectedIssuer(key);
                          setMotionPaused(true);
                        }}
                        aria-pressed={active}
                        className={`min-h-11 px-3.5 py-2 rounded border text-left transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink ${
                          active
                            ? "border-rise bg-raised text-ink shadow-md"
                            : "border-line bg-surface/80 text-muted hover:text-ink hover:border-faint"
                        }`}
                      >
                        <span className="block font-mono text-xs font-semibold text-ink">
                          {item.ticker}
                        </span>
                        <span className="block font-mono text-[11px] tnum text-rise">
                          IDR {item.close} ({item.changePct})
                        </span>
                      </button>
                    );
                  })}

                  <button
                    type="button"
                    onClick={() => setMotionPaused((p) => !p)}
                    aria-pressed={motionPaused}
                    className="min-h-11 px-3 py-2 rounded border border-faint bg-surface text-xs font-mono text-muted hover:text-ink transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                  >
                    {motionPaused ? t("landing.motion.play") : t("landing.motion.pause")}
                  </button>
                </div>
              </div>

              <div className="mt-7 flex flex-wrap items-center gap-3">
                <Link
                  to={primaryHref}
                  className="inline-flex items-center justify-center min-h-11 px-5 rounded bg-rise text-surface text-sm font-semibold hover:bg-rise/90 active:bg-rise/80 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                >
                  {primaryLabel}
                </Link>
                <a
                  href="#pipeline"
                  className="inline-flex items-center justify-center min-h-11 px-4 rounded border border-faint bg-raised text-ink text-sm font-medium hover:bg-hover active:bg-surface transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                >
                  {t("landing.cta.inspectPipeline")}
                </a>
                {user && (
                  <Link
                    to="/picks"
                    className="inline-flex items-center justify-center min-h-11 px-4 rounded border border-faint bg-surface text-muted hover:text-ink text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                  >
                    {t("landing.cta.browsePicks")}
                  </Link>
                )}
              </div>

              <div className="mt-7 pt-5 border-t border-line max-w-[58ch]">
                <p className="text-xs font-mono uppercase tracking-wider text-muted">
                  {t("disclaimer.title")}
                </p>
                <p className="mt-1 text-xs sm:text-sm text-muted leading-relaxed">
                  {t("landing.hero.boundaryNote")}
                </p>
              </div>
            </div>

            {/* Right 6 cols: Architectural backdrop image + Floating Product Canvas */}
            <div className="lg:col-span-6">
              <div className="relative rounded-lg border border-faint bg-raised overflow-hidden shadow-2xl">
                <img
                  src="/landing/hero-jakarta-skyline.jpg"
                  alt={
                    locale === "id"
                      ? "Cakrawala distrik finansial pada malam hari sebagai latar ruang kerja keputusan AIDSS"
                      : "Night financial district skyline framing the AIDSS decision workspace"
                  }
                  width={1600}
                  height={2411}
                  fetchPriority="high"
                  className="absolute inset-0 h-full w-full object-cover object-bottom opacity-35"
                />
                {/* High-contrast dark scrim so all text exceeds WCAG AA 4.5:1 across the entire surface */}
                <div
                  aria-hidden="true"
                  className="absolute inset-0 bg-gradient-to-b from-surface/92 via-surface/88 to-surface/96"
                />

                <div className="relative z-10 p-4 sm:p-6 space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
                    <div>
                      <span className="font-mono text-[11px] uppercase tracking-wider text-muted block">
                        {t("landing.hero.liveStageLabel")}
                      </span>
                      <span className="text-base font-semibold text-ink">
                        {specimen.ticker} · {specimen.name}
                      </span>
                    </div>
                    <span
                      className={`font-mono text-xs font-semibold px-2.5 py-1 rounded border ${
                        specimen.stance === "BUY"
                          ? "border-rise/60 bg-surface text-rise"
                          : "border-watch/60 bg-surface text-watch"
                      }`}
                    >
                      {specimen.stance} · {Math.round(specimen.confidence * 100)}%
                    </span>
                  </div>

                  {/* Interactive SVG OHLCV + Kronos 5-Day Forecast Envelope */}
                  <div
                    key={specimen.code}
                    className="aidss-stage-panel rounded-md border border-line bg-surface/95 p-3 sm:p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-muted mb-2">
                      <span>
                        {locale === "id" ? specimen.sectorId : specimen.sectorEn}
                      </span>
                      <span className="text-rise">
                        KRONOS 5D {specimen.kronosDelta} ({specimen.kronosBand})
                      </span>
                    </div>

                    <svg
                      viewBox="0 0 340 84"
                      role="img"
                      aria-label={`${specimen.ticker} OHLCV & Kronos-base 5-day projection`}
                      className="w-full h-36 sm:h-44 overflow-visible"
                    >
                      {/* Resistance & ATR stop guide lines */}
                      <line
                        x1="8"
                        y1="16"
                        x2="332"
                        y2="16"
                        stroke="#5c6b7d"
                        strokeDasharray="3 3"
                        strokeWidth="0.75"
                      />
                      <text x="10" y="13" fill="#8b98a9" fontSize="6.5" fontFamily="monospace">
                        R1 {specimen.resistance1}
                      </text>

                      <line
                        x1="8"
                        y1="66"
                        x2="332"
                        y2="66"
                        stroke="#ef5350"
                        strokeDasharray="3 3"
                        strokeWidth="0.75"
                      />
                      <text x="10" y="75" fill="#ef5350" fontSize="6.5" fontFamily="monospace">
                        ATR STOP {specimen.atrStop}
                      </text>

                      {/* Divider between settled OHLCV history and 5-day Kronos projection */}
                      <line
                        x1="205"
                        y1="8"
                        x2="205"
                        y2="76"
                        stroke="#26a69a"
                        strokeDasharray="2 2"
                        strokeWidth="0.9"
                      />
                      <text x="210" y="13" fill="#26a69a" fontSize="6.5" fontFamily="monospace">
                        KRONOS +5D ENVELOPE
                      </text>

                      {/* Historical OHLCV candlesticks */}
                      {specimen.candles.map((c, idx) => {
                        const x = 25 + idx * 28;
                        const bullish = c.c <= c.o;
                        const color = bullish ? "#26a69a" : "#ef5350";
                        const top = Math.min(c.o, c.c);
                        const bodyH = Math.max(Math.abs(c.o - c.c), 2.5);
                        return (
                          <g key={x}>
                            <line
                              x1={x}
                              y1={c.h}
                              x2={x}
                              y2={c.l}
                              stroke={color}
                              strokeWidth="1.2"
                            />
                            <rect
                              x={x - 5}
                              y={top}
                              width="10"
                              height={bodyH}
                              rx="1"
                              fill={color}
                            />
                          </g>
                        );
                      })}

                      {/* Kronos uncertainty band + animated median trajectory */}
                      <polygon points={envelopePolygon} fill="#26a69a" fillOpacity="0.18" />
                      <polyline
                        points={upperPts.join(" ")}
                        fill="none"
                        stroke="#26a69a"
                        strokeOpacity="0.55"
                        strokeWidth="1"
                      />
                      <polyline
                        points={ specimen.forecastLower
                          .map((y, i) => `${xStart + i * xStep},${y}`)
                          .join(" ") }
                        fill="none"
                        stroke="#26a69a"
                        strokeOpacity="0.55"
                        strokeWidth="1"
                      />
                      <polyline
                        points={midPolyline}
                        fill="none"
                        stroke="#26a69a"
                        strokeWidth="2"
                        className="aidss-flow-line"
                      />
                      {specimen.forecastMid.map((y, i) => (
                        <circle
                          key={i}
                          cx={xStart + i * xStep}
                          cy={y}
                          r="2.4"
                          fill="#e6edf3"
                          stroke="#26a69a"
                          strokeWidth="1.2"
                        />
                      ))}
                    </svg>

                    <p className="mt-2 text-[11px] text-muted">
                      {t("landing.hero.chartCaption")}
                    </p>
                  </div>

                  {/* 4-metric product strip */}
                  <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono tnum">
                    <div className="p-2.5 rounded bg-surface/95 border border-line">
                      <dt className="text-muted">{t("landing.hero.metric.close")}</dt>
                      <dd className="mt-1 text-sm text-ink font-semibold">
                        {specimen.close}
                      </dd>
                    </div>
                    <div className="p-2.5 rounded bg-surface/95 border border-line">
                      <dt className="text-muted">{t("landing.hero.metric.kronos")}</dt>
                      <dd className="mt-1 text-sm text-rise font-semibold">
                        {specimen.kronosDelta}
                      </dd>
                    </div>
                    <div className="p-2.5 rounded bg-surface/95 border border-line">
                      <dt className="text-muted">{t("landing.hero.metric.stop")}</dt>
                      <dd className="mt-1 text-sm text-ink font-semibold">
                        {specimen.atrStop}
                      </dd>
                    </div>
                    <div className="p-2.5 rounded bg-surface/95 border border-line">
                      <dt className="text-muted">{t("landing.hero.metric.stance")}</dt>
                      <dd
                        className={`mt-1 text-sm font-semibold ${
                          specimen.stance === "BUY" ? "text-rise" : "text-watch"
                        }`}
                      >
                        {specimen.stance} ({specimen.confidence.toFixed(2)})
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* SECTION 1 (#pipeline): Interactive Product Studio with editorial photography + 3-mode interactive workspace */}
        <section
          id="pipeline"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16 lg:py-20 border-b border-line"
        >
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-start">
            {/* Left 5 cols: Editorial narrative + framed quant desk photograph */}
            <div className="lg:col-span-5 space-y-6">
              <div>
                <p className="font-mono text-xs uppercase tracking-wider text-rise">
                  {t("landing.pipeline.kicker")}
                </p>
                <h2 className="mt-2 text-2xl sm:text-3xl font-semibold text-ink tracking-tight leading-snug">
                  {t("landing.pipeline.title")}
                </h2>
                <p className="mt-3 text-sm sm:text-base text-muted leading-relaxed">
                  {t("landing.pipeline.body")}
                </p>
              </div>

              <div className="relative rounded-lg border border-faint bg-raised overflow-hidden">
                <img
                  src="/landing/quant-desk-editorial.jpg"
                  alt={
                    locale === "id"
                      ? "Tampilan dekat grafik candlestick finansial pada layar ruang analisis"
                      : "Close-up of financial candlestick charts on an institutional analysis monitor"
                  }
                  width={1200}
                  height={800}
                  loading="lazy"
                  className="h-52 sm:h-60 w-full object-cover opacity-55"
                />
                <div
                  aria-hidden="true"
                  className="absolute inset-0 bg-gradient-to-t from-surface via-surface/75 to-surface/35"
                />
                <div className="relative z-10 p-4 sm:p-5 -mt-20">
                  <div className="rounded border border-line bg-surface/95 p-3.5 space-y-2.5">
                    {[
                      {
                        step: "01",
                        name: t("landing.pipeline.s1.name"),
                        desc: t("landing.pipeline.s1.desc"),
                      },
                      {
                        step: "02",
                        name: t("landing.pipeline.s2.name"),
                        desc: t("landing.pipeline.s2.desc"),
                      },
                      {
                        step: "03",
                        name: t("landing.pipeline.s3.name"),
                        desc: t("landing.pipeline.s3.desc"),
                      },
                      {
                        step: "04",
                        name: t("landing.pipeline.s4.name"),
                        desc: t("landing.pipeline.s4.desc"),
                      },
                    ].map((layer) => (
                      <div
                        key={layer.step}
                        className="border-b border-line pb-2.5 last:border-0 last:pb-0"
                      >
                        <p className="text-xs font-semibold text-ink">{layer.name}</p>
                        <p className="mt-0.5 text-xs text-muted leading-relaxed">
                          {layer.desc}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Right 7 cols: Interactive 3-Tab Product Studio */}
            <div className="lg:col-span-7 rounded-lg border border-faint bg-raised overflow-hidden shadow-xl">
              <div className="px-4 sm:px-5 py-3.5 border-b border-line bg-surface flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted">
                  {t("landing.specimen.header")}
                </span>
                <span className="font-mono text-xs text-ink font-medium">
                  {specimen.ticker} · {specimen.name}
                </span>
              </div>

              <div
                role="tablist"
                aria-label={t("landing.specimen.header")}
                className="grid grid-cols-1 sm:grid-cols-3 border-b border-line bg-surface/60"
              >
                {SPECIMEN_TABS.map((tab) => {
                  const selected = activeTab === tab;
                  return (
                    <button
                      key={tab}
                      id={`specimen-tab-${tab}`}
                      role="tab"
                      type="button"
                      aria-selected={selected}
                      aria-controls={`specimen-panel-${tab}`}
                      tabIndex={selected ? 0 : -1}
                      onClick={() => setActiveTab(tab)}
                      onKeyDown={(e) => handleTabKeyDown(e, tab)}
                      className={`min-h-11 px-3.5 py-2.5 text-left text-xs font-mono border-b-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ink ${
                        selected
                          ? "border-rise bg-raised text-ink font-semibold"
                          : "border-transparent text-muted hover:text-ink hover:bg-hover/50"
                      }`}
                    >
                      {t(`landing.specimen.tab.${tab}`)}
                    </button>
                  );
                })}
              </div>

              <div
                id={`specimen-panel-${activeTab}`}
                role="tabpanel"
                aria-labelledby={`specimen-tab-${activeTab}`}
                className="aidss-stage-panel p-4 sm:p-6 space-y-5"
              >
                {activeTab === "deterministic" && (
                  <>
                    <p className="text-xs sm:text-sm text-muted leading-relaxed">
                      {t("landing.specimen.det.caption")}
                    </p>

                    {/* Visual indicator meters & price ladder */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-mono tnum">
                      <div className="p-3.5 rounded bg-surface border border-line space-y-2">
                        <div className="flex items-center justify-between text-muted">
                          <span>RSI (14)</span>
                          <span className="text-ink font-semibold">{specimen.rsi}</span>
                        </div>
                        <div className="h-2 rounded-sm bg-raised overflow-hidden border border-line">
                          <div
                            className="h-full bg-rise"
                            style={{ width: `${specimen.rsi}%` }}
                          />
                        </div>
                        <span className="block text-[11px] text-muted">
                          {locale === "id" ? "Zona netral-kuat (30..70)" : "Neutral-bullish band (30..70)"}
                        </span>
                      </div>

                      <div className="p-3.5 rounded bg-surface border border-line space-y-2">
                        <div className="flex items-center justify-between text-muted">
                          <span>ADX (14)</span>
                          <span className="text-ink font-semibold">{specimen.adx}</span>
                        </div>
                        <div className="h-2 rounded-sm bg-raised overflow-hidden border border-line">
                          <div
                            className="h-full bg-rise"
                            style={{ width: `${Math.min(specimen.adx * 2, 100)}%` }}
                          />
                        </div>
                        <span className="block text-[11px] text-muted">
                          {locale === "id" ? "Kekuatan tren terukur" : "Measured trend strength"}
                        </span>
                      </div>

                      <div className="p-3.5 rounded bg-surface border border-line space-y-2">
                        <div className="flex items-center justify-between text-muted">
                          <span>KRONOS 5D</span>
                          <span className="text-rise font-semibold">{specimen.kronosDelta}</span>
                        </div>
                        <div className="h-2 rounded-sm bg-raised overflow-hidden border border-line">
                          <div
                            className="h-full bg-rise"
                            style={{ width: `${Math.round(specimen.confidence * 100)}%` }}
                          />
                        </div>
                        <span className="block text-[11px] text-muted">
                          {specimen.kronosBand} IDR
                        </span>
                      </div>
                    </div>

                    <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-xs font-mono tnum">
                      <div className="p-3 rounded bg-surface border border-line">
                        <dt className="text-muted">SUPPORT 1</dt>
                        <dd className="mt-1 text-sm text-rise font-semibold">
                          IDR {specimen.support1}
                        </dd>
                      </div>
                      <div className="p-3 rounded bg-surface border border-line">
                        <dt className="text-muted">SPOT CLOSE</dt>
                        <dd className="mt-1 text-sm text-ink font-semibold">
                          IDR {specimen.close}
                        </dd>
                      </div>
                      <div className="p-3 rounded bg-surface border border-line">
                        <dt className="text-muted">RESISTANCE 1</dt>
                        <dd className="mt-1 text-sm text-ink font-semibold">
                          IDR {specimen.resistance1}
                        </dd>
                      </div>
                    </dl>

                    <ul className="space-y-2.5 text-xs sm:text-sm text-muted border-t border-line pt-4">
                      <li className="flex items-start gap-2.5">
                        <span className="font-mono text-xs text-rise shrink-0 mt-0.5">[01]</span>
                        <span>{t("landing.specimen.det.indicators")}</span>
                      </li>
                      <li className="flex items-start gap-2.5">
                        <span className="font-mono text-xs text-rise shrink-0 mt-0.5">[02]</span>
                        <span>{t("landing.specimen.det.levels")}</span>
                      </li>
                      <li className="flex items-start gap-2.5">
                        <span className="font-mono text-xs text-rise shrink-0 mt-0.5">[03]</span>
                        <span>{t("landing.specimen.det.kronos")}</span>
                      </li>
                    </ul>
                  </>
                )}

                {activeTab === "debate" && (
                  <>
                    <p className="text-xs sm:text-sm text-muted leading-relaxed">
                      {t("landing.specimen.debate.caption")}
                    </p>

                    {/* Quantexa-inspired Interactive Multi-Agent Context Graph */}
                    <div className="rounded-md border border-line bg-surface p-3 sm:p-4">
                      <svg
                        viewBox="0 0 500 130"
                        role="img"
                        aria-label="Multi-agent debate and risk committee graph"
                        className="w-full h-32 sm:h-36"
                      >
                        {/* Animated connection lines */}
                        <line
                          x1="75"
                          y1="65"
                          x2="185"
                          y2="32"
                          stroke="#26a69a"
                          strokeWidth="1.5"
                          className="aidss-flow-line"
                        />
                        <line
                          x1="75"
                          y1="65"
                          x2="185"
                          y2="98"
                          stroke="#ef5350"
                          strokeWidth="1.5"
                          className="aidss-flow-line"
                        />
                        <line
                          x1="185"
                          y1="32"
                          x2="310"
                          y2="65"
                          stroke="#26a69a"
                          strokeWidth="1.5"
                          className="aidss-flow-line"
                        />
                        <line
                          x1="185"
                          y1="98"
                          x2="310"
                          y2="65"
                          stroke="#ef5350"
                          strokeWidth="1.5"
                          className="aidss-flow-line"
                        />
                        <line
                          x1="310"
                          y1="65"
                          x2="430"
                          y2="65"
                          stroke="#b8893f"
                          strokeWidth="1.75"
                          className="aidss-flow-line"
                        />

                        {(
                          [
                            { id: "analysts", x: 65, y: 65, tag: "4 ANALYSTS", stroke: "#8b98a9" },
                            { id: "bull", x: 185, y: 32, tag: "BULL", stroke: "#26a69a" },
                            { id: "bear", x: 185, y: 98, tag: "BEAR", stroke: "#ef5350" },
                            { id: "judge", x: 310, y: 65, tag: "JUDGE", stroke: "#e6edf3" },
                            { id: "risk", x: 430, y: 65, tag: "RISK (3)", stroke: "#b8893f" },
                          ] as const
                        ).map((n) => {
                          const selected = activeNode === n.id;
                          return (
                            <g key={n.id}>
                              <rect
                                x={n.x - 46}
                                y={n.y - 16}
                                width="92"
                                height="32"
                                rx="4"
                                fill={selected ? "#1a2230" : "#121821"}
                                stroke={selected ? n.stroke : "#5c6b7d"}
                                strokeWidth={selected ? "2" : "1"}
                              />
                              <text
                                x={n.x}
                                y={n.y + 3}
                                textAnchor="middle"
                                fill="#e6edf3"
                                fontSize="8.5"
                                fontFamily="monospace"
                                fontWeight="600"
                              >
                                {n.tag}
                              </text>
                            </g>
                          );
                        })}
                      </svg>

                      {/* Accessible node selector buttons */}
                      <div className="mt-2 flex flex-wrap gap-1.5 border-t border-line pt-3">
                        {(["analysts", "bull", "bear", "judge", "risk"] as const).map((nodeId) => {
                          const node = debateNodes[nodeId];
                          const isSelected = activeNode === nodeId;
                          return (
                            <button
                              key={nodeId}
                              type="button"
                              onClick={() => setActiveNode(nodeId)}
                              aria-pressed={isSelected}
                              className={`min-h-10 px-3 py-1.5 rounded text-xs font-mono border transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink ${
                                isSelected
                                  ? "border-rise bg-raised text-ink font-semibold"
                                  : "border-line bg-surface text-muted hover:text-ink"
                              }`}
                            >
                              {node.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Active agent transcript card */}
                    <div className="p-4 rounded-md bg-surface border border-faint space-y-1.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-ink">
                          {debateNodes[activeNode].label}
                        </span>
                        <span className="font-mono text-xs text-muted">
                          {debateNodes[activeNode].role}
                        </span>
                      </div>
                      <p className="text-xs sm:text-sm text-muted leading-relaxed">
                        {debateNodes[activeNode].summary}
                      </p>
                    </div>
                  </>
                )}

                {activeTab === "stance" && (
                  <>
                    <p className="text-xs sm:text-sm text-muted leading-relaxed">
                      {t("landing.specimen.stance.caption")}
                    </p>
                    <dl className="grid grid-cols-3 gap-2.5 text-xs font-mono tnum">
                      <div className="p-3 rounded bg-surface border border-line">
                        <dt className="text-muted">{t("landing.specimen.stance.label")}</dt>
                        <dd
                          className={`mt-1 text-sm font-semibold ${
                            specimen.stance === "BUY" ? "text-rise" : "text-watch"
                          }`}
                        >
                          {specimen.stance}
                        </dd>
                      </div>
                      <div className="p-3 rounded bg-surface border border-line">
                        <dt className="text-muted">{t("landing.specimen.stance.confidence")}</dt>
                        <dd className="mt-1 text-sm text-ink font-semibold">
                          {specimen.confidence.toFixed(2)}
                        </dd>
                      </div>
                      <div className="p-3 rounded bg-surface border border-line">
                        <dt className="text-muted">{t("landing.specimen.stance.stopMethod")}</dt>
                        <dd className="mt-1 text-sm text-ink font-semibold">ATR 2.0x</dd>
                      </div>
                    </dl>

                    <div className="p-4 rounded bg-surface border border-line">
                      <p className="text-xs font-mono uppercase text-watch mb-2">
                        {t("landing.specimen.stance.conflictsTitle")}
                      </p>
                      <ul className="space-y-1.5 text-xs sm:text-sm text-muted list-disc pl-4">
                        <li>{t("landing.specimen.stance.conflict1")}</li>
                        <li>{t("landing.specimen.stance.conflict2")}</li>
                      </ul>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* SECTION 2 (#architecture): Contextual Intelligence & Temporal Integrity Showcase */}
        <section
          id="architecture"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16 lg:py-20 border-b border-line"
        >
          <div className="max-w-3xl">
            <p className="font-mono text-xs uppercase tracking-wider text-rise">
              {t("landing.debate.kicker")}
            </p>
            <h2 className="mt-2 text-2xl sm:text-3xl font-semibold text-ink tracking-tight">
              {t("landing.debate.title")}
            </h2>
            <p className="mt-3 text-sm sm:text-base text-muted leading-relaxed">
              {t("landing.debate.body")}
            </p>
          </div>

          <div className="mt-8 grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
            <div className="lg:col-span-7 rounded-lg border border-line bg-raised p-5 sm:p-6 flex flex-col justify-between">
              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
                  <h3 className="text-base font-semibold text-ink">
                    {t("landing.debate.leftTitle")}
                  </h3>
                  <span className="font-mono text-xs text-muted">
                    {t("landing.debate.leftSub")}
                  </span>
                </div>

                <ol className="mt-4 space-y-3.5">
                  {[
                    {
                      step: "01",
                      role: t("landing.debate.step1.role"),
                      detail: t("landing.debate.step1.detail"),
                    },
                    {
                      step: "02",
                      role: t("landing.debate.step2.role"),
                      detail: t("landing.debate.step2.detail"),
                    },
                    {
                      step: "03",
                      role: t("landing.debate.step3.role"),
                      detail: t("landing.debate.step3.detail"),
                    },
                  ].map((item) => (
                    <li
                      key={item.step}
                      className="p-4 rounded-md bg-surface border border-line flex items-start gap-3.5"
                    >
                      <span className="font-mono text-xs text-rise bg-raised border border-faint px-2.5 py-1 rounded shrink-0">
                        {item.step}
                      </span>
                      <div>
                        <p className="text-sm font-semibold text-ink">{item.role}</p>
                        <p className="mt-1 text-xs sm:text-sm text-muted leading-relaxed">
                          {item.detail}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
            </div>

            <div className="lg:col-span-5 rounded-lg border border-line bg-raised p-5 sm:p-6 flex flex-col justify-between">
              <div>
                <h3 className="text-base font-semibold text-ink border-b border-line pb-3">
                  {t("landing.debate.rightTitle")}
                </h3>
                <p className="mt-4 text-sm text-muted leading-relaxed">
                  {t("landing.debate.rightBody")}
                </p>

                {/* Visual Temporal Horizon Audit Timeline */}
                <div className="mt-5 space-y-2.5 font-mono text-xs">
                  <div className="p-3 rounded bg-surface border border-line flex items-center justify-between">
                    <span className="text-muted">T-30D · REGIME MATCH</span>
                    <span className="text-rise">SETTLED (ELIGIBLE)</span>
                  </div>
                  <div className="p-3 rounded bg-surface border border-rise/60 flex items-center justify-between">
                    <span className="text-ink font-semibold">T0 · EVALUATION AS_OF</span>
                    <span className="text-ink">LOCKED SNAPSHOT</span>
                  </div>
                  <div className="p-3 rounded bg-surface/60 border border-line flex items-center justify-between opacity-75">
                    <span className="text-muted">T+5D · FUTURE HORIZON</span>
                    <span className="text-watch">BLOCKED FROM PROMPT</span>
                  </div>
                </div>
              </div>

              <div className="mt-6 p-4 rounded bg-surface border border-faint">
                <p className="text-xs text-muted leading-relaxed">
                  {t("landing.debate.rightGuard")}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* SECTION 3 (#boundaries): AIDSS Trader Operator Cockpit with architectural network backdrop */}
        <section
          id="boundaries"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16 lg:py-20 border-b border-line"
        >
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-start">
            {/* Left 6 cols: Framed architectural network image + Trader Cockpit Preview */}
            <div className="lg:col-span-6 space-y-5">
              <p className="font-mono text-xs uppercase tracking-wider text-rise">
                {t("landing.boundaries.kicker")}
              </p>
              <h2 className="text-2xl sm:text-3xl font-semibold text-ink tracking-tight leading-snug">
                {t("landing.boundaries.title")}
              </h2>
              <p className="text-sm sm:text-base text-muted leading-relaxed">
                {t("landing.boundaries.body")}
              </p>

              <div className="relative rounded-lg border border-faint bg-raised overflow-hidden shadow-xl">
                <img
                  src="/landing/exchange-architecture.jpg"
                  alt={
                    locale === "id"
                      ? "Visualisasi jaringan arsitektur untuk pengawasan eksekusi spot dan batas risiko"
                      : "Architectural network visualization representing spot execution oversight and risk limits"
                  }
                  width={1200}
                  height={800}
                  loading="lazy"
                  className="h-56 sm:h-64 w-full object-cover opacity-40"
                />
                <div
                  aria-hidden="true"
                  className="absolute inset-0 bg-gradient-to-t from-surface via-surface/85 to-surface/60"
                />

                <div className="relative z-10 p-4 sm:p-5 -mt-44 sm:-mt-48 space-y-3.5">
                  <div className="rounded-md border border-line bg-surface/95 p-4 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2.5">
                      <span className="font-mono text-xs font-semibold text-ink">
                        AIDSS TRADER · INDODAX TAPIv2 (IDR)
                      </span>
                      <span className="font-mono text-xs px-2 py-0.5 rounded bg-raised border border-faint text-watch">
                        PAPER → APPROVAL → AUTO
                      </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 font-mono text-xs">
                      <div className="p-2.5 rounded bg-raised border border-line">
                        <span className="text-muted block text-[10px]">ORIGIN TAG</span>
                        <span className="text-ink font-semibold mt-0.5 block">LIVE / PAPER</span>
                      </div>
                      <div className="p-2.5 rounded bg-raised border border-line">
                        <span className="text-muted block text-[10px]">WITHDRAWAL</span>
                        <span className="text-rise font-semibold mt-0.5 block">DISABLED</span>
                      </div>
                      <div className="p-2.5 rounded bg-raised border border-line">
                        <span className="text-muted block text-[10px]">EMERGENCY</span>
                        <span className="text-fall font-semibold mt-0.5 block">HALT · FLATTEN</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right 6 cols: 4 Guardrail cards */}
            <div className="lg:col-span-6">
              <dl className="grid grid-cols-1 gap-4">
                {[
                  {
                    code: "01",
                    title: t("landing.boundaries.b1.title"),
                    desc: t("landing.boundaries.b1.desc"),
                  },
                  {
                    code: "02",
                    title: t("landing.boundaries.b2.title"),
                    desc: t("landing.boundaries.b2.desc"),
                  },
                  {
                    code: "03",
                    title: t("landing.boundaries.b3.title"),
                    desc: t("landing.boundaries.b3.desc"),
                  },
                  {
                    code: "04",
                    title: t("landing.boundaries.b4.title"),
                    desc: t("landing.boundaries.b4.desc"),
                  },
                ].map((b) => (
                  <div
                    key={b.code}
                    className="p-5 rounded-lg border border-line bg-raised flex items-start gap-4"
                  >
                    <span className="font-mono text-xs text-rise bg-surface border border-faint px-2.5 py-1 rounded shrink-0">
                      {b.code}
                    </span>
                    <div>
                      <dt className="text-base font-semibold text-ink">{b.title}</dt>
                      <dd className="mt-1.5 text-sm text-muted leading-relaxed">
                        {b.desc}
                      </dd>
                    </div>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </section>

        {/* SECTION 4 (#modules): Workspace Route Launcher */}
        <section
          id="modules"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16"
        >
          <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
            <div>
              <p className="font-mono text-xs uppercase tracking-wider text-rise">
                WORKSPACE SURFACES
              </p>
              <h2 className="mt-1.5 text-2xl sm:text-3xl font-semibold text-ink tracking-tight">
                {t("landing.modules.title")}
              </h2>
            </div>
            <Link
              to={primaryHref}
              className="inline-flex items-center justify-center min-h-11 px-5 rounded bg-rise text-surface text-sm font-semibold hover:bg-rise/90 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              {primaryLabel}
            </Link>
          </div>

          {/* Varied asymmetric composition: 2 featured wide workspaces + 3 supporting workspaces */}
          <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
            {[
              {
                to: "/watchlist",
                span: "md:col-span-3",
                badge: "IDX · OHLCV · KRONOS",
                name: t("landing.modules.watchlist.name"),
                desc: t("landing.modules.watchlist.desc"),
              },
              {
                to: "/trader",
                span: "md:col-span-3",
                badge: "INDODAX IDR · PAPER / APPROVAL / AUTO",
                name: t("landing.modules.trader.name"),
                desc: t("landing.modules.trader.desc"),
              },
              {
                to: "/picks",
                span: "md:col-span-2",
                badge: "EXCHANGE SCREENER",
                name: t("landing.modules.picks.name"),
                desc: t("landing.modules.picks.desc"),
              },
              {
                to: "/portfolio",
                span: "md:col-span-2",
                badge: "POSITIONS & JOURNAL",
                name: t("landing.modules.portfolio.name"),
                desc: t("landing.modules.portfolio.desc"),
              },
              {
                to: "/monitoring",
                span: "md:col-span-2",
                badge: "ALERTS & DISCLOSURES",
                name: t("landing.modules.monitoring.name"),
                desc: t("landing.modules.monitoring.desc"),
              },
            ].map((mod) => (
              <Link
                key={mod.to}
                to={mod.to}
                className={`${mod.span} group p-5 rounded-lg border border-faint bg-raised hover:bg-hover hover:border-rise/60 transition-all flex flex-col justify-between focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-rise">{mod.badge}</span>
                    <span className="font-mono text-xs text-muted">{mod.to}</span>
                  </div>
                  <h3 className="mt-2.5 text-base font-semibold text-ink">
                    {mod.name}
                  </h3>
                  <p className="mt-1.5 text-sm text-muted leading-relaxed">
                    {mod.desc}
                  </p>
                </div>
                <span className="mt-5 inline-flex items-center text-xs font-mono text-ink group-hover:text-rise transition-colors">
                  {primaryLabel} &rarr;
                </span>
              </Link>
            ))}
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-line bg-surface">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6 flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <img
                src="/logo-symbol.svg"
                alt=""
                width={18}
                height={18}
                className="h-4 w-4"
              />
              <span className="text-xs font-semibold text-ink">
                {t("app.shortName")}
              </span>
              <span className="text-xs text-muted">
                · {t("disclaimer.title")}
              </span>
            </div>

            <nav aria-label="Footer" className="flex flex-wrap items-center gap-2">
              <Link
                to="/login"
                className="min-h-11 inline-flex items-center px-2.5 text-xs text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.footer.loginLink")}
              </Link>
              <Link
                to="/watchlist"
                className="min-h-11 inline-flex items-center px-2.5 text-xs text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.footer.watchlistLink")}
              </Link>
              <Link
                to="/picks"
                className="min-h-11 inline-flex items-center px-2.5 text-xs text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.footer.picksLink")}
              </Link>
              <Link
                to="/monitoring"
                className="min-h-11 inline-flex items-center px-2.5 text-xs text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.footer.monitoringLink")}
              </Link>
              <Link
                to="/trader"
                className="min-h-11 inline-flex items-center px-2.5 text-xs text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("nav.trader")}
              </Link>
            </nav>
          </div>

          <p className="text-xs text-muted leading-relaxed">
            {t("disclaimer.long")}
          </p>
        </div>
      </footer>
    </div>
  );
}
