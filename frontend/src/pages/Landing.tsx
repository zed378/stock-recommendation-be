import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { preload } from "react-dom";
import { useAuth } from "@/auth/context";
import { useI18n, type MessageKey } from "@/i18n/context";
import type { Locale } from "@/i18n/messages";
import { DecisionStack } from "@/landing/DecisionStack";
import { useStackMotion } from "@/landing/useStackMotion";
import "@/landing/landing.css";

/**
 * The public front page.
 *
 * Everything on it is taken from what the product does today (README, the recommendation schema, the
 * navigation). Three things are deliberately absent: figures (no price, no confidence, no count of users),
 * quotations, and any claim that a market order can be placed. The platform has no order path by design,
 * and the separate Trader service has never been connected to an exchange; the page says so.
 *
 * Direction: see `landing/landing.css`.
 */

const NAV: ReadonlyArray<{ id: string; label: MessageKey }> = [
  { id: "kartu", label: "landing.nav.card" },
  { id: "lapisan", label: "landing.nav.layers" },
  { id: "batas", label: "landing.nav.limits" },
  { id: "ruang", label: "landing.nav.workspaces" },
];

// The six annotated parts of the decision card, in reading order. Each is a field of the stored
// recommendation (`RecommendationResponse`), so the page cannot describe a field that does not exist.
const PARTS = ["stance", "confidence", "factors", "scenarios", "levels", "trace"] as const;
type Part = (typeof PARTS)[number];

const STANCES: ReadonlyArray<MessageKey> = [
  "landing.stance.strongBuy",
  "landing.stance.buy",
  "landing.stance.watchlist",
  "landing.stance.hold",
  "landing.stance.reduce",
  "landing.stance.sell",
];

const LAYERS = ["data", "indicators", "forecast", "debate", "calibration"] as const;

const WORKSPACES = [
  { to: "/watchlist", key: "watchlist" },
  { to: "/picks", key: "picks" },
  { to: "/portfolio", key: "portfolio" },
  { to: "/monitoring", key: "monitoring" },
  { to: "/trader", key: "trader" },
] as const;

const EXCLUDED = ["engine", "broker", "endpoint", "table", "vocabulary"] as const;

const ACTION =
  "min-h-11 items-center justify-center rounded-[3px] px-6 text-[0.95rem] font-semibold transition-colors";

export function Landing() {
  const { user } = useAuth();
  const { locale, setLocale, t } = useI18n();
  const root = useRef<HTMLDivElement>(null);
  const hero = useRef<HTMLElement>(null);
  const heroStack = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [part, setPart] = useState<Part | null>(null);
  const [layer, setLayer] = useState(0);

  // These faces are what the first paint is made of (the headline's emphasised word is italic), so ask for them
  // early: a face that arrives after the text is painted re-flows the headline. Only this page does.
  preload("/fonts/newsreader-display.woff2", { as: "font", type: "font/woff2", crossOrigin: "anonymous" });
  preload("/fonts/newsreader-display-italic.woff2", { as: "font", type: "font/woff2", crossOrigin: "anonymous" });
  preload("/fonts/inter-latin.woff2", { as: "font", type: "font/woff2", crossOrigin: "anonymous" });

  useStackMotion(heroStack, hero, { scroll: true, tilt: true });

  // Blocks fade in as they arrive. The class that hides them is only added once this runs, so a page that
  // fails to run script still shows everything.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const targets = el.querySelectorAll<HTMLElement>(".lp-reveal");
    // A browser without IntersectionObserver gets the page fully shown rather than hidden.
    if (typeof IntersectionObserver === "undefined") return;
    el.classList.add("lp-js");
    const seen = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).dataset.in = "true";
            seen.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    targets.forEach((node) => seen.observe(node));
    return () => seen.disconnect();
  }, []);

  // Which layer's step is in the middle of the screen decides which plane of the stack is brought forward.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const steps = el.querySelectorAll<HTMLElement>("[data-step]");
    if (typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setLayer(Number((entry.target as HTMLElement).dataset.step));
        }
      },
      { rootMargin: "-42% 0px -42% 0px" },
    );
    steps.forEach((node) => watch.observe(node));
    return () => watch.disconnect();
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const entryTo = user ? "/watchlist" : "/login";
  const entryLabel = user ? t("landing.cta.open") : t("landing.cta.signIn");
  const point = (next: Part | null) => ({
    onMouseEnter: () => setPart(next),
    onMouseLeave: () => setPart(null),
    onFocus: () => setPart(next),
    onBlur: () => setPart(null),
  });
  const lit = (...names: Part[]) => (part !== null && names.includes(part) ? "true" : "false");

  return (
    <div ref={root} className="lp min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-[3px] focus:bg-[var(--lp-accent-fill)] focus:px-4 focus:py-2 focus:text-[var(--lp-ink)]"
      >
        {t("landing.skipToMain")}
      </a>

      {/* ------------------------------------------------------------ navigation */}
      <header className="sticky top-0 z-30 border-b border-[var(--lp-line)] bg-[var(--lp-ink)]">
        <div className="mx-auto flex max-w-[88rem] items-center gap-4 px-5 sm:px-8">
          <Link to="/" className="flex min-h-14 items-center gap-2.5 text-[var(--lp-text)]">
            <img src="/logo-symbol.svg" alt="" width="22" height="22" className="h-[22px] w-[22px]" />
            <span className="text-[0.95rem] font-semibold tracking-tight">{t("app.shortName")}</span>
          </Link>

          <nav aria-label={t("landing.nav.label")} className="ml-4 hidden items-center gap-0.5 md:flex lg:ml-8 lg:gap-1">
            {NAV.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                className="inline-flex min-h-11 items-center whitespace-nowrap px-2.5 text-sm text-[var(--lp-muted)] transition-colors hover:text-[var(--lp-text)] lg:px-3"
              >
                {t(item.label)}
              </a>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1 sm:gap-3">
            <LocaleSwitch locale={locale} onChange={setLocale} label={t("nav.language")} />
            <Link
              to={entryTo}
              className={`${ACTION} hidden bg-[var(--lp-accent-fill)] text-[var(--lp-ink)] hover:bg-[var(--lp-accent)] sm:inline-flex md:hidden lg:inline-flex`}
            >
              {user ? t("landing.cta.open") : t("landing.cta.signInShort")}
            </Link>
            <button
              type="button"
              aria-expanded={menuOpen}
              aria-controls="lp-menu"
              onClick={() => setMenuOpen((was) => !was)}
              className="inline-flex min-h-11 min-w-11 items-center justify-center text-sm text-[var(--lp-text)] md:hidden"
            >
              {menuOpen ? t("landing.nav.closeMenu") : t("landing.nav.menu")}
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav
            id="lp-menu"
            aria-label={t("landing.nav.label")}
            className="border-t border-[var(--lp-line)] px-5 pb-4 pt-2 md:hidden"
          >
            {NAV.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                onClick={() => setMenuOpen(false)}
                className="flex min-h-11 items-center text-[var(--lp-text)]"
              >
                {t(item.label)}
              </a>
            ))}
            <Link
              to={entryTo}
              className={`${ACTION} mt-2 flex w-full bg-[var(--lp-accent-fill)] text-[var(--lp-ink)]`}
            >
              {entryLabel}
            </Link>
          </nav>
        )}
      </header>

      <main id="main-content">
        {/* ---------------------------------------------------------- hero */}
        <section ref={hero} aria-labelledby="lp-hero-title" className="relative overflow-hidden">
          <div className="mx-auto grid max-w-[88rem] gap-8 px-5 pb-16 pt-12 sm:px-8 lg:grid-cols-12 lg:gap-4 lg:pb-28 lg:pt-24">
            <div className="min-w-0 lg:col-span-7 lg:self-center lg:pr-12">
              <h1
                id="lp-hero-title"
                className="lp-display text-[clamp(2rem,calc((100vw-40px)/8.1),2.75rem)] leading-[0.97] text-[var(--lp-text)] md:text-[clamp(2.75rem,5vw,4.3rem)]"
              >
                {t("landing.hero.titleA")}{" "}
                <em className="text-[var(--lp-accent)]">{t("landing.hero.titleEm")}</em>
                {t("landing.hero.titleB")}
              </h1>
              <p className="mt-8 max-w-[34rem] text-[1.075rem] leading-relaxed text-[var(--lp-muted)]">
                {t("landing.hero.lead")}
              </p>
              <div className="mt-10 flex flex-wrap items-center gap-x-8 gap-y-3">
                <Link
                  to={entryTo}
                  className={`${ACTION} inline-flex bg-[var(--lp-accent-fill)] text-[var(--lp-ink)] hover:bg-[var(--lp-accent)] active:translate-y-px`}
                >
                  {entryLabel}
                </Link>
                <a
                  href="#kartu"
                  className="inline-flex min-h-11 items-center text-[0.95rem] text-[var(--lp-text)] underline decoration-[var(--lp-faint)] underline-offset-[6px] transition-colors hover:decoration-[var(--lp-accent)]"
                >
                  {t("landing.cta.seeCard")}
                </a>
              </div>
              <p className="mt-6 text-sm text-[var(--lp-faint)]">{t("landing.hero.note")}</p>
            </div>

            <figure className="relative lg:col-span-5 lg:-mr-10 lg:self-center">
              <div className="mx-auto w-full max-w-[34rem] lg:max-w-none">
                <div className="relative aspect-[5/4]">
                  <DecisionStack ref={heroStack} />
                </div>
              </div>
              <figcaption className="-mt-4 max-w-[22rem] text-xs leading-relaxed text-[var(--lp-faint)] lg:ml-auto lg:mr-14">
                {t("landing.hero.figure")}
              </figcaption>
            </figure>
          </div>
        </section>

        {/* ---------------------------------------------------------- the decision card */}
        <section id="kartu" aria-labelledby="lp-card-title" className="lp-paper">
          <div className="mx-auto grid max-w-[88rem] gap-12 px-5 py-20 sm:px-8 lg:grid-cols-12 lg:gap-10 lg:py-32">
            <div className="lp-reveal lg:col-span-5">
              <h2
                id="lp-card-title"
                className="lp-display text-[clamp(2rem,4.2vw,3.6rem)] leading-[1.02]"
              >
                {t("landing.card.title")}
              </h2>
              <p className="lp-muted mt-6 max-w-md leading-relaxed">{t("landing.card.lead")}</p>

              <ol className="mt-10 border-t border-[var(--lp-paper-line)]">
                {PARTS.map((name, i) => (
                  <li key={name} className="border-b border-[var(--lp-paper-line)]">
                    <button
                      type="button"
                      onClick={() => setPart(name)}
                      {...point(name)}
                      className="grid w-full min-h-11 grid-cols-[2rem_1fr] gap-x-3 py-4 text-left"
                    >
                      <span className="lp-index mt-0.5 text-[var(--lp-paper-accent)]">{i + 1}</span>
                      <span>
                        <span className="block font-semibold">{t(`landing.part.${name}.name` as MessageKey)}</span>
                        <span className="lp-muted mt-1 block text-[0.95rem] leading-relaxed">
                          {t(`landing.part.${name}.rule` as MessageKey)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>

            <figure className="lp-reveal lg:col-span-7">
              <div aria-hidden="true" className="grid gap-3">
                <div className="lp-field p-5" data-active={lit("stance")}>
                  <FieldLabel n={1} text={t("landing.part.stance.name")} />
                  <div className="mt-4 flex flex-wrap gap-2">
                    {STANCES.map((key) => (
                      <span
                        key={key}
                        className="rounded-[3px] border border-[var(--lp-paper-line)] px-3 py-1.5 text-sm"
                      >
                        {t(key)}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="lp-field p-5" data-active={lit("confidence")}>
                  <FieldLabel n={2} text={t("landing.part.confidence.name")} />
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    {(["landing.card.calibrated", "landing.card.reported"] as const).map((key) => (
                      <div key={key}>
                        <span className="lp-muted text-sm">{t(key)}</span>
                        <div className="mt-2 h-2 rounded-[2px] border border-[var(--lp-paper-line)]" />
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  {(["support", "against", "risk"] as const).map((key) => (
                    <div key={key} className="lp-field min-h-28 p-5" data-active={lit("factors")}>
                      <FieldLabel
                        n={key === "support" ? 3 : undefined}
                        text={t(`landing.card.factor.${key}` as MessageKey)}
                      />
                    </div>
                  ))}
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  {(["up", "down"] as const).map((key) => (
                    <div key={key} className="lp-field min-h-24 p-5" data-active={lit("scenarios")}>
                      <FieldLabel
                        n={key === "up" ? 4 : undefined}
                        text={t(`landing.card.scenario.${key}` as MessageKey)}
                      />
                    </div>
                  ))}
                </div>

                <div className="lp-field p-5" data-active={lit("levels")}>
                  <FieldLabel n={5} text={t("landing.part.levels.name")} />
                  <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                    {(["support", "resistance", "target", "stop"] as const).map((key) => (
                      <div key={key}>
                        <dt className="lp-muted text-sm">{t(`landing.card.level.${key}` as MessageKey)}</dt>
                        <dd className="mt-2 h-5 border-b border-dashed border-[var(--lp-paper-line)]" />
                      </div>
                    ))}
                  </dl>
                </div>

                <div className="lp-field flex items-center gap-3 px-5 py-3" data-active={lit("trace")}>
                  <FieldLabel n={6} text={t("landing.part.trace.name")} />
                  <span className="lp-muted text-sm">{t("landing.card.traceFields")}</span>
                </div>
              </div>
              <figcaption className="lp-muted mt-4 text-sm">{t("landing.card.caption")}</figcaption>
            </figure>
          </div>
        </section>

        {/* ---------------------------------------------------------- the five layers */}
        <section id="lapisan" aria-labelledby="lp-layers-title">
          <div className="mx-auto grid max-w-[88rem] gap-10 px-5 py-20 sm:px-8 lg:grid-cols-12 lg:gap-12 lg:py-32">
            <div className="lg:col-span-5">
              <div className="lg:sticky lg:top-24">
                <h2
                  id="lp-layers-title"
                  className="lp-display max-w-md text-[clamp(2rem,4.2vw,3.6rem)] leading-[1.02]"
                >
                  {t("landing.layers.title")}
                </h2>
                <div className="mx-auto mt-20 hidden w-full max-w-[30rem] lg:block">
                  <div className="relative aspect-[6/5]">
                    <DecisionStackAtRest active={layer} />
                  </div>
                </div>
              </div>
              {/* On a phone the steps are read one after another and the stack would be off screen for all of
                  them, so it appears once, at rest, with no highlight to follow. */}
              <div className="relative mx-auto mt-10 aspect-[6/5] w-full max-w-[22rem] lg:hidden">
                <DecisionStackAtRest />
              </div>
            </div>

            <ol className="lg:col-span-7 lg:pt-2">
              {LAYERS.map((key, i) => (
                <li
                  key={key}
                  data-step={i}
                  className="lp-row grid gap-3 py-10 sm:grid-cols-[4rem_1fr] lg:min-h-[44vh] lg:py-14"
                >
                  <span className="lp-display text-3xl text-[var(--lp-accent)]" aria-hidden="true">
                    {i + 1}
                  </span>
                  <div>
                    <h3 className="lp-display text-[1.7rem] leading-tight">
                      {t(`landing.layer.${key}.name` as MessageKey)}
                    </h3>
                    <p className="mt-3 max-w-xl leading-relaxed text-[var(--lp-muted)]">
                      {t(`landing.layer.${key}.body` as MessageKey)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ---------------------------------------------------------- limits */}
        <section id="batas" aria-labelledby="lp-limits-title" className="lp-paper">
          <div className="mx-auto max-w-[88rem] px-5 py-20 sm:px-8 lg:py-32">
            <h2
              id="lp-limits-title"
              className="lp-display lp-reveal max-w-4xl text-[clamp(2.2rem,5.4vw,4.8rem)] leading-[1.0]"
            >
              {t("landing.limits.titleA")} <em>{t("landing.limits.titleEm")}</em>
              {t("landing.limits.titleB")}
            </h2>

            <div className="mt-14 grid gap-12 lg:grid-cols-12 lg:gap-10">
              <div className="lp-reveal lg:col-span-7">
                <p className="lp-muted max-w-xl leading-relaxed">{t("landing.limits.lead")}</p>
                <ul className="mt-8">
                  {EXCLUDED.map((key) => (
                    <li
                      key={key}
                      className="lp-row flex items-baseline justify-between gap-6 py-4"
                    >
                      <span className="lp-display text-[1.5rem]">
                        {t(`landing.limits.item.${key}` as MessageKey)}
                      </span>
                      <span className="lp-muted text-sm">{t("landing.limits.none")}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="lp-reveal lg:col-span-4 lg:col-start-9 lg:pt-3">
                <h3 className="font-semibold">{t("landing.trader.title")}</h3>
                <p className="lp-muted mt-3 leading-relaxed">{t("landing.trader.body")}</p>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------- workspaces */}
        <section id="ruang" aria-labelledby="lp-spaces-title">
          <div className="mx-auto grid max-w-[88rem] gap-12 px-5 py-20 sm:px-8 lg:grid-cols-12 lg:gap-10 lg:py-32">
            <div className="lg:col-span-4">
              <h2
                id="lp-spaces-title"
                className="lp-display text-[clamp(2rem,4.2vw,3.6rem)] leading-[1.02]"
              >
                {t("landing.spaces.title")}
              </h2>
              <p className="mt-6 max-w-sm leading-relaxed text-[var(--lp-muted)]">{t("landing.spaces.lead")}</p>
              <Link
                to={entryTo}
                className={`${ACTION} mt-10 inline-flex bg-[var(--lp-accent-fill)] text-[var(--lp-ink)] hover:bg-[var(--lp-accent)] active:translate-y-px`}
              >
                {entryLabel}
              </Link>
            </div>

            <ul className="lg:col-span-8">
              {WORKSPACES.map((item, i) => (
                <li key={item.key} className="lp-row">
                  <Link
                    to={item.to}
                    className="lp-index-link grid sm:grid-cols-[3rem_minmax(0,1fr)_minmax(0,1.3fr)]"
                  >
                    <span className="text-sm text-[var(--lp-faint)]">{String(i + 1).padStart(2, "0")}</span>
                    <span className="lp-index-name lp-display text-[1.65rem] leading-tight">
                      {t(`landing.spaces.${item.key}.name` as MessageKey)}
                    </span>
                    <span className="text-[0.95rem] leading-relaxed text-[var(--lp-muted)]">
                      {t(`landing.spaces.${item.key}.desc` as MessageKey)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="border-t border-[var(--lp-line)]">
        <div className="mx-auto grid max-w-[88rem] gap-10 px-5 py-12 sm:px-8 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <div className="flex items-center gap-2.5">
              <img src="/logo-symbol.svg" alt="" width="22" height="22" className="h-[22px] w-[22px]" />
              <span className="font-semibold">{t("app.shortName")}</span>
            </div>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-[var(--lp-muted)]">
              <span className="font-semibold text-[var(--lp-text)]">{t("disclaimer.title")}. </span>
              {t("disclaimer.long")}
            </p>
          </div>
          <nav aria-label={t("landing.footer.label")} className="lg:col-span-4 lg:col-start-9">
            <ul>
              {(
                [
                  ["/login", "landing.footer.login"],
                  ["/watchlist", "landing.footer.watchlist"],
                  ["/picks", "landing.footer.picks"],
                  ["/monitoring", "landing.footer.monitoring"],
                ] as const
              ).map(([to, label]) => (
                <li key={to}>
                  <Link to={to} className="inline-flex min-h-11 items-center text-sm text-[var(--lp-muted)] hover:text-[var(--lp-text)]">
                    {t(label)}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        <p className="mx-auto max-w-[88rem] px-5 pb-10 text-xs text-[var(--lp-faint)] sm:px-8">
          {t("landing.footer.copyright", { year: new Date().getFullYear() })}
        </p>
      </footer>
    </div>
  );
}

function FieldLabel({ n, text }: { n?: number; text: string }) {
  return (
    <span className="flex items-center gap-2.5 font-semibold">
      {n !== undefined && <span className="lp-index text-[var(--lp-paper-accent)]">{n}</span>}
      {text}
    </span>
  );
}

// The second stack, beside the five steps. It sits at rest (the layers pulled apart) and only the
// highlighted plane changes, so there is nothing to scroll-link here.
function DecisionStackAtRest({ active }: { active?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const zone = useRef<HTMLDivElement>(null);
  useStackMotion(ref, zone, { rest: 0.85 });
  return (
    <div ref={zone} className="absolute inset-0">
      <DecisionStack ref={ref} active={active} />
    </div>
  );
}

function LocaleSwitch({
  locale,
  onChange,
  label,
}: {
  locale: Locale;
  onChange: (next: Locale) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex border border-[var(--lp-line)] rounded-[3px]">
      {(["id", "en"] as const).map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={locale === option}
          className={`min-h-11 min-w-11 px-2.5 text-xs uppercase transition-colors ${
            locale === option
              ? "bg-[var(--lp-ink-raised)] text-[var(--lp-text)]"
              : "text-[var(--lp-muted)] hover:text-[var(--lp-text)]"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
