import type { ReactNode } from "react";
import { useI18n } from "@/i18n/context";
import { Button, Loading } from "@/components/primitives";
import { TraderError, type Meta } from "@/trader/client";
import { useAgeLabel, useNow } from "@/trader/hooks";
import { ageSeconds } from "@/trader/format";

/**
 * Where a figure comes from and how old it is.
 *
 * The age counts up on its own between polls. A value is never shown as current
 * past the point the server said it was stale, and the word "stale" is text,
 * not only a colour (docs/04-UX-UI/00 principle 3, WCAG: not colour alone).
 */
export function Freshness({
  meta,
  fetchedAt,
  failed = false,
}: {
  meta: Meta | undefined;
  fetchedAt: number;
  failed?: boolean;
}) {
  const { t } = useI18n();
  const now = useNow();
  const age = useAgeLabel();
  if (!meta) return null;
  const seconds = ageSeconds(fetchedAt, now);
  return (
    <p className="flex flex-wrap items-center gap-x-2 text-xs text-faint">
      <span>{t("trader.fresh.updated", { age: age(seconds), source: meta.source })}</span>
      {(meta.stale || failed) && (
        <span className="rounded border border-watch/40 px-1.5 py-0.5 font-medium text-watch">
          {t("trader.fresh.stale")}
        </span>
      )}
    </p>
  );
}

/**
 * The origin label sits on the figure itself.
 *
 * Paper and backtest numbers must never be read as live (FR-T28), so this is
 * rendered next to the block and carries words, not just a colour.
 */
export function OriginBadge({ origin }: { origin: Meta["origin"] }) {
  const { t } = useI18n();
  const live = origin === "LIVE";
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-wide ${
        live ? "border-line text-muted" : "border-watch/50 bg-watch/10 text-watch"
      }`}
    >
      {t(`trader.origin.${origin}`)}
    </span>
  );
}

const ERR_KEYS = {
  NETWORK: "trader.err.NETWORK",
  AUTH: "trader.err.AUTH",
  FORBIDDEN: "trader.err.FORBIDDEN",
  UNAVAILABLE: "trader.err.UNAVAILABLE",
  VALIDATION: "trader.err.VALIDATION",
  NOT_FOUND: "trader.err.NOT_FOUND",
  CONFLICT: "trader.err.CONFLICT",
  UNKNOWN: "trader.err.UNKNOWN",
} as const;

/** The cause class and reference id, never a stack trace and never a blank. */
export function TraderErrorNote({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  const e = error instanceof TraderError ? error : null;
  const cls = e?.cls ?? "UNKNOWN";
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-md border border-fall/30 bg-fall/5 px-3 py-2.5"
    >
      <p className="text-sm font-medium text-fall">{t("trader.unavailable", { cls })}</p>
      <p className="text-sm text-muted">{t(ERR_KEYS[cls])}</p>
      {e?.message && e.cls !== "NETWORK" && (
        <p className="text-xs text-faint">{e.message}</p>
      )}
      {e?.correlationId && (
        <p className="font-mono text-xs text-faint">
          {t("trader.unavailable.ref", { id: e.correlationId })}
        </p>
      )}
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      )}
    </div>
  );
}

/**
 * The four states of a panel that has data behind it: loading, unavailable,
 * empty, or content. A missing value is never drawn as zero: loading is a
 * spinner, "could not load" is an explicit note, and a lost connection keeps the
 * last data but says how old it is (docs/04-UX-UI/03).
 */
export function PanelBody<T>({
  query,
  children,
}: {
  query: {
    data: { data: T; meta: Meta } | undefined;
    error: unknown;
    isPending: boolean;
    isError: boolean;
    refetch: () => unknown;
    dataUpdatedAt: number;
  };
  children: (data: T, meta: Meta) => ReactNode;
}) {
  const { t } = useI18n();
  const now = useNow();
  const age = useAgeLabel();
  if (query.isPending) return <Loading />;
  if (!query.data) return <TraderErrorNote error={query.error} onRetry={() => query.refetch()} />;
  return (
    <div className="space-y-3">
      {query.isError && (
        <div role="alert" className="rounded-md border border-watch/40 bg-watch/5 px-3 py-2">
          <p className="text-xs text-watch">
            {t("trader.fresh.lost", { age: age(ageSeconds(query.dataUpdatedAt, now)) })}
          </p>
        </div>
      )}
      <div className={query.isError || query.data.meta.stale ? "opacity-60" : undefined}>
        {children(query.data.data, query.data.meta)}
      </div>
      <Freshness meta={query.data.meta} fetchedAt={query.dataUpdatedAt} failed={query.isError} />
    </div>
  );
}
