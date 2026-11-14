import { useEffect, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/context";
import { Backdrop } from "@/components/Backdrop";
import { useI18n } from "@/i18n/context";

type SpecimenTab = "deterministic" | "debate" | "stance";

const SPECIMEN_TABS: readonly SpecimenTab[] = ["deterministic", "debate", "stance"];

export function Landing() {
  const { user } = useAuth();
  const { locale, setLocale, t } = useI18n();
  const [activeTab, setActiveTab] = useState<SpecimenTab>("deterministic");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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

  return (
    <div className="relative min-h-dvh bg-surface text-ink flex flex-col">
      <Backdrop />

      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:bg-ink focus:text-surface focus:px-4 focus:py-2.5 focus:rounded focus:text-sm focus:font-medium"
      >
        {t("landing.skipToMain")}
      </a>

      <header className="relative z-20 border-b border-line bg-surface/95">
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
                IDX / OHLCV
              </span>
            </Link>

            <nav
              aria-label="Primary"
              className="hidden md:flex items-center gap-1"
            >
              <a
                href="#pipeline"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.pipeline")}
              </a>
              <a
                href="#architecture"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.debate")}
              </a>
              <a
                href="#boundaries"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {t("landing.nav.boundaries")}
              </a>
              <a
                href="#modules"
                className="min-h-11 inline-flex items-center px-3 text-sm text-muted hover:text-ink rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
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
                    className={`min-h-10 min-w-10 px-2.5 text-xs font-mono uppercase rounded-sm cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink ${
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
              className="hidden sm:inline-flex items-center justify-center min-h-11 px-4 rounded bg-ink text-surface text-sm font-medium hover:bg-ink/90 active:bg-ink/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              {primaryLabel}
            </Link>

            <button
              type="button"
              onClick={() => setMobileMenuOpen((prev) => !prev)}
              aria-expanded={mobileMenuOpen}
              aria-controls="landing-mobile-nav"
              className="md:hidden inline-flex items-center justify-center min-h-11 px-3 rounded border border-faint bg-raised text-sm text-ink hover:bg-hover cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
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
              className="mt-2 min-h-11 flex items-center justify-center px-4 rounded bg-ink text-surface text-sm font-medium"
            >
              {primaryLabel}
            </Link>
          </nav>
        )}
      </header>

      <main id="main-content" className="relative z-10 flex-1">
        {/* Hero: Asymmetric 7/5 split */}
        <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 sm:py-14 lg:py-20 border-b border-line">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-start">
            <div className="lg:col-span-7 flex flex-col">
              <p className="font-mono text-xs tracking-wider uppercase text-muted mb-4">
                {t("landing.hero.coordinate")}
              </p>

              <h1
                className="font-semibold tracking-tight text-ink leading-[1.12] max-w-[24ch]"
                style={{ fontSize: "clamp(1.85rem, 3.2vw + 0.9rem, 3.1rem)" }}
              >
                {t("landing.hero.title")}
              </h1>

              <p className="mt-5 text-base sm:text-lg text-muted leading-relaxed max-w-[62ch]">
                {t("landing.hero.lead")}
              </p>

              <div className="mt-7 flex flex-wrap items-center gap-3">
                <Link
                  to={primaryHref}
                  className="inline-flex items-center justify-center min-h-11 px-5 rounded bg-ink text-surface text-sm font-medium hover:bg-ink/90 active:bg-ink/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                >
                  {primaryLabel}
                </Link>
                <a
                  href="#pipeline"
                  className="inline-flex items-center justify-center min-h-11 px-4 rounded border border-faint bg-raised text-ink text-sm font-medium hover:bg-hover active:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                >
                  {t("landing.cta.inspectPipeline")}
                </a>
                {user && (
                  <Link
                    to="/picks"
                    className="inline-flex items-center justify-center min-h-11 px-4 rounded border border-faint bg-surface text-muted hover:text-ink text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                  >
                    {t("landing.cta.browsePicks")}
                  </Link>
                )}
              </div>

              <div className="mt-8 pt-6 border-t border-line max-w-[62ch]">
                <p className="text-xs font-mono uppercase tracking-wider text-muted">
                  {t("disclaimer.title")}
                </p>
                <p className="mt-1.5 text-sm text-muted leading-relaxed">
                  {t("landing.hero.boundaryNote")}
                </p>
              </div>
            </div>

            {/* Right 5 cols: Interactive Specimen Inspector */}
            <div className="lg:col-span-5 rounded-md border border-faint bg-raised overflow-hidden">
              <div className="px-4 py-3 border-b border-line bg-surface flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted">
                  {t("landing.specimen.header")}
                </span>
                <span className="font-mono text-xs text-ink font-medium">
                  {t("landing.specimen.ticker")}
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
                      className={`min-h-11 px-3 py-2 text-left text-xs font-mono cursor-pointer border-b-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ink ${
                        selected
                          ? "border-ink bg-raised text-ink font-medium"
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
                className="p-4 sm:p-5 space-y-4"
              >
                {activeTab === "deterministic" && (
                  <>
                    <p className="text-xs text-muted leading-relaxed">
                      {t("landing.specimen.det.caption")}
                    </p>
                    <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-xs font-mono tnum">
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">CLOSE (IDR)</dt>
                        <dd className="mt-1 text-sm text-ink font-medium">9,850</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">RSI (14)</dt>
                        <dd className="mt-1 text-sm text-ink font-medium">56.4</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">ATR (14)</dt>
                        <dd className="mt-1 text-sm text-ink font-medium">145</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">SUPPORT 1</dt>
                        <dd className="mt-1 text-sm text-rise font-medium">9,625</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">RESISTANCE 1</dt>
                        <dd className="mt-1 text-sm text-ink font-medium">10,125</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">KRONOS 5D</dt>
                        <dd className="mt-1 text-sm text-rise font-medium">+1.83%</dd>
                      </div>
                    </dl>
                    <ul className="space-y-2 text-xs text-muted border-t border-line pt-3">
                      <li className="flex items-start gap-2">
                        <span className="font-mono text-ink shrink-0">[IND]</span>
                        <span>{t("landing.specimen.det.indicators")}</span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="font-mono text-ink shrink-0">[LVL]</span>
                        <span>{t("landing.specimen.det.levels")}</span>
                      </li>
                      <li className="flex items-start gap-2">
                        <span className="font-mono text-ink shrink-0">[KRN]</span>
                        <span>{t("landing.specimen.det.kronos")}</span>
                      </li>
                    </ul>
                  </>
                )}

                {activeTab === "debate" && (
                  <>
                    <p className="text-xs text-muted leading-relaxed">
                      {t("landing.specimen.debate.caption")}
                    </p>
                    <div className="space-y-2.5 text-xs">
                      <div className="p-3 rounded bg-surface border-l-2 border-rise">
                        <p className="text-ink leading-relaxed">
                          {t("landing.specimen.debate.bull")}
                        </p>
                      </div>
                      <div className="p-3 rounded bg-surface border-l-2 border-fall">
                        <p className="text-ink leading-relaxed">
                          {t("landing.specimen.debate.bear")}
                        </p>
                      </div>
                      <div className="p-3 rounded bg-surface border-l-2 border-faint">
                        <p className="text-muted leading-relaxed">
                          {t("landing.specimen.debate.risk")}
                        </p>
                      </div>
                    </div>
                  </>
                )}

                {activeTab === "stance" && (
                  <>
                    <p className="text-xs text-muted leading-relaxed">
                      {t("landing.specimen.stance.caption")}
                    </p>
                    <dl className="grid grid-cols-3 gap-2.5 text-xs font-mono tnum">
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">{t("landing.specimen.stance.label")}</dt>
                        <dd className="mt-1 text-sm text-rise font-semibold">BUY</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">{t("landing.specimen.stance.confidence")}</dt>
                        <dd className="mt-1 text-sm text-ink font-medium">0.74</dd>
                      </div>
                      <div className="p-2.5 rounded bg-surface border border-line">
                        <dt className="text-muted">{t("landing.specimen.stance.stopMethod")}</dt>
                        <dd className="mt-1 text-sm text-ink font-medium">ATR 2.0x</dd>
                      </div>
                    </dl>
                    <div className="p-3 rounded bg-surface border border-line">
                      <p className="text-xs font-mono uppercase text-ink mb-2">
                        {t("landing.specimen.stance.conflictsTitle")}
                      </p>
                      <ul className="space-y-1.5 text-xs text-muted list-disc pl-4">
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

        {/* Section 1: Asymmetric 4/8 Pipeline Ledger */}
        <section
          id="pipeline"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16 border-b border-line"
        >
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-start">
            <div className="lg:col-span-4">
              <p className="font-mono text-xs uppercase tracking-wider text-muted">
                {t("landing.pipeline.kicker")}
              </p>
              <h2 className="mt-2 text-xl sm:text-2xl font-semibold text-ink tracking-tight leading-snug">
                {t("landing.pipeline.title")}
              </h2>
              <p className="mt-3 text-sm sm:text-base text-muted leading-relaxed">
                {t("landing.pipeline.body")}
              </p>
            </div>

            <div className="lg:col-span-8 rounded-md border border-line bg-raised overflow-hidden">
              <div className="hidden sm:grid sm:grid-cols-12 px-4 py-2.5 border-b border-line bg-surface text-xs font-mono uppercase text-muted">
                <div className="col-span-4">{t("landing.pipeline.col.stage")}</div>
                <div className="col-span-3">{t("landing.pipeline.col.module")}</div>
                <div className="col-span-5">{t("landing.pipeline.col.responsibility")}</div>
              </div>

              <div className="divide-y divide-line">
                {[
                  {
                    name: t("landing.pipeline.s1.name"),
                    module: "src/aidss/collectors/",
                    desc: t("landing.pipeline.s1.desc"),
                  },
                  {
                    name: t("landing.pipeline.s2.name"),
                    module: "src/aidss/indicators/ + forecasting/",
                    desc: t("landing.pipeline.s2.desc"),
                  },
                  {
                    name: t("landing.pipeline.s3.name"),
                    module: "src/aidss/agents/trading_agents/",
                    desc: t("landing.pipeline.s3.desc"),
                  },
                  {
                    name: t("landing.pipeline.s4.name"),
                    module: "src/aidss/recommendation/",
                    desc: t("landing.pipeline.s4.desc"),
                  },
                ].map((row) => (
                  <div
                    key={row.module}
                    className="p-4 sm:grid sm:grid-cols-12 sm:gap-4 items-start"
                  >
                    <div className="sm:col-span-4 font-medium text-sm text-ink">
                      {row.name}
                    </div>
                    <div className="mt-1 sm:mt-0 sm:col-span-3 font-mono text-xs text-muted break-all">
                      {row.module}
                    </div>
                    <div className="mt-2 sm:mt-0 sm:col-span-5 text-sm text-muted leading-relaxed">
                      {row.desc}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Section 2: Research & Debate Graph + Look-Ahead-Safe Situation Memory */}
        <section
          id="architecture"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16 border-b border-line"
        >
          <div className="max-w-3xl">
            <p className="font-mono text-xs uppercase tracking-wider text-muted">
              {t("landing.debate.kicker")}
            </p>
            <h2 className="mt-2 text-xl sm:text-2xl font-semibold text-ink tracking-tight">
              {t("landing.debate.title")}
            </h2>
            <p className="mt-3 text-sm sm:text-base text-muted leading-relaxed">
              {t("landing.debate.body")}
            </p>
          </div>

          <div className="mt-8 grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
            <div className="lg:col-span-7 rounded-md border border-line bg-raised p-5 sm:p-6 flex flex-col justify-between">
              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
                  <h3 className="text-base font-semibold text-ink">
                    {t("landing.debate.leftTitle")}
                  </h3>
                  <span className="font-mono text-xs text-muted">
                    {t("landing.debate.leftSub")}
                  </span>
                </div>

                <ol className="mt-4 space-y-4">
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
                      className="p-3.5 rounded bg-surface border border-line flex items-start gap-3.5"
                    >
                      <span className="font-mono text-xs text-ink bg-raised border border-faint px-2 py-1 rounded shrink-0">
                        {item.step}
                      </span>
                      <div>
                        <p className="text-sm font-medium text-ink">{item.role}</p>
                        <p className="mt-1 text-xs sm:text-sm text-muted leading-relaxed">
                          {item.detail}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
            </div>

            <div className="lg:col-span-5 rounded-md border border-line bg-raised p-5 sm:p-6 flex flex-col justify-between">
              <div>
                <h3 className="text-base font-semibold text-ink border-b border-line pb-3">
                  {t("landing.debate.rightTitle")}
                </h3>
                <p className="mt-4 text-sm text-muted leading-relaxed">
                  {t("landing.debate.rightBody")}
                </p>
              </div>

              <div className="mt-6 p-4 rounded bg-surface border border-faint">
                <p className="font-mono text-xs text-ink uppercase tracking-wider">
                  SQL INVARIANT · situation_memory.py
                </p>
                <p className="mt-2 font-mono text-xs text-rise">
                  WHERE settled_at IS NOT NULL AND settled_at &lt;= :as_of_timestamp
                </p>
                <p className="mt-2 text-xs text-muted leading-relaxed">
                  {t("landing.debate.rightGuard")}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Section 3: System Boundaries & Direct Module Links */}
        <section
          id="boundaries"
          className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12 sm:py-16"
        >
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10">
            <div className="lg:col-span-6">
              <p className="font-mono text-xs uppercase tracking-wider text-muted">
                {t("landing.boundaries.kicker")}
              </p>
              <h2 className="mt-2 text-xl sm:text-2xl font-semibold text-ink tracking-tight">
                {t("landing.boundaries.title")}
              </h2>
              <p className="mt-3 text-sm sm:text-base text-muted leading-relaxed">
                {t("landing.boundaries.body")}
              </p>

              <dl className="mt-6 space-y-4">
                {[
                  {
                    title: t("landing.boundaries.b1.title"),
                    desc: t("landing.boundaries.b1.desc"),
                  },
                  {
                    title: t("landing.boundaries.b2.title"),
                    desc: t("landing.boundaries.b2.desc"),
                  },
                  {
                    title: t("landing.boundaries.b3.title"),
                    desc: t("landing.boundaries.b3.desc"),
                  },
                  {
                    title: t("landing.boundaries.b4.title"),
                    desc: t("landing.boundaries.b4.desc"),
                  },
                ].map((b) => (
                  <div
                    key={b.title}
                    className="p-4 rounded-md border border-line bg-raised"
                  >
                    <dt className="text-sm font-semibold text-ink">{b.title}</dt>
                    <dd className="mt-1 text-sm text-muted leading-relaxed">
                      {b.desc}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>

            <div id="modules" className="lg:col-span-6 flex flex-col justify-between">
              <div>
                <p className="font-mono text-xs uppercase tracking-wider text-muted">
                  WORKSPACE ROUTES
                </p>
                <h2 className="mt-2 text-xl sm:text-2xl font-semibold text-ink tracking-tight">
                  {t("landing.modules.title")}
                </h2>

                <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {[
                    {
                      to: "/watchlist",
                      pathLabel: "/watchlist",
                      name: t("landing.modules.watchlist.name"),
                      desc: t("landing.modules.watchlist.desc"),
                    },
                    {
                      to: "/picks",
                      pathLabel: "/picks",
                      name: t("landing.modules.picks.name"),
                      desc: t("landing.modules.picks.desc"),
                    },
                    {
                      to: "/portfolio",
                      pathLabel: "/portfolio",
                      name: t("landing.modules.portfolio.name"),
                      desc: t("landing.modules.portfolio.desc"),
                    },
                    {
                      to: "/monitoring",
                      pathLabel: "/monitoring",
                      name: t("landing.modules.monitoring.name"),
                      desc: t("landing.modules.monitoring.desc"),
                    },
                  ].map((mod) => (
                    <Link
                      key={mod.to}
                      to={mod.to}
                      className="group p-4 rounded-md border border-faint bg-raised hover:bg-hover transition-colors flex flex-col justify-between focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                    >
                      <div>
                        <span className="font-mono text-xs text-muted group-hover:text-ink">
                          {mod.pathLabel}
                        </span>
                        <h3 className="mt-1.5 text-sm font-semibold text-ink">
                          {mod.name}
                        </h3>
                        <p className="mt-1.5 text-xs sm:text-sm text-muted leading-relaxed">
                          {mod.desc}
                        </p>
                      </div>
                      <span className="mt-4 inline-flex items-center text-xs font-mono text-ink">
                        {primaryLabel} &rarr;
                      </span>
                    </Link>
                  ))}
                </div>
              </div>

              <div className="mt-6 p-4 rounded-md border border-line bg-surface flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-ink">{t("app.name")}</p>
                  <p className="text-xs text-muted mt-0.5">{t("disclaimer.short")}</p>
                </div>
                <Link
                  to={primaryHref}
                  className="inline-flex items-center justify-center min-h-11 px-4 rounded bg-ink text-surface text-sm font-medium hover:bg-ink/90 shrink-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                >
                  {primaryLabel}
                </Link>
              </div>
            </div>
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
