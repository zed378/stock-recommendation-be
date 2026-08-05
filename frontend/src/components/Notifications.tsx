import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n/context";
import { Empty, ErrorNote, Loading } from "@/components/primitives";

/**
 * The notification bell and its panel.
 *
 * Two deliberate choices, both about not becoming noise:
 *
 *   * **The badge polls; the list does not.** The count is one integer from a
 *     dedicated endpoint, so keeping the badge current does not mean fetching
 *     fifty rows every half minute. The list is fetched when the panel opens.
 *   * **Nothing here says what to do.** The server writes each message as a
 *     statement of what happened, and the stance - where one exists - arrives
 *     as data in `context`. This renders it as a labelled value beside a link
 *     back to the analysis, never folded into the sentence, because a line read
 *     in two seconds without the confidence or the counter-evidence around it
 *     must not read as a call to transact.
 */

const POLL_INTERVAL = 45_000;

type Notification = {
  id: string;
  subject: string | null;
  message: string;
  status: string;
  created_at: string;
  event?: string | null;
  context?: Record<string, unknown> | null;
};

/** The event vocabulary is closed on the server, so this map can be too. */
const EVENT_LABELS: Record<string, MessageKey> = {
  analysis_ready: "notif.event.analysis_ready",
  monitoring_alert: "notif.event.monitoring_alert",
  recommendation_updated: "notif.event.recommendation_updated",
  news_ingested: "notif.event.news_ingested",
  schedule_needs_attention: "notif.event.schedule_needs_attention",
  ingestion_failed: "notif.event.ingestion_failed",
  budget_threshold_reached: "notif.event.budget_threshold_reached",
  report_ready: "notif.event.report_ready",
};

export function NotificationBell() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  const unread = useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: async () => {
      const { data, error } = await api.GET("/notifications/unread-count");
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return data?.unread ?? 0;
    },
    refetchInterval: POLL_INTERVAL,
  });

  // Closing on an outside click and on Escape, because a panel that only
  // closes via its own button traps anyone who opened it by accident.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const count = unread.data ?? 0;

  return (
    <div ref={container} className="relative">
      <button
        onClick={() => setOpen((was) => !was)}
        aria-label={count > 0 ? t("notif.unread", { count }) : t("notif.open")}
        aria-expanded={open}
        className={`relative rounded-md px-2 py-1.5 transition-colors ${
          open ? "bg-hover text-ink" : "text-muted hover:bg-hover/60 hover:text-ink"
        }`}
      >
        <BellIcon />
        {count > 0 && (
          <span
            // The number, not just a dot: "three things happened" and "thirty
            // things happened" are different situations and deserve different
            // urgency. Capped so the badge cannot widen without limit.
            //
            // Neutral ink rather than a palette colour. Every colour in this
            // theme already means something - green is a rise, amber is a
            // `watchlist` stance - and a badge borrowing one would say
            // something about the contents it has not read.
            className="absolute -right-0.5 -top-0.5 min-w-[1.05rem] rounded-full bg-ink px-1 text-[0.625rem] font-semibold leading-[1.05rem] text-surface"
          >
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {open && <NotificationPanel onClose={() => setOpen(false)} />}
    </div>
  );
}

function NotificationPanel({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [includeRead, setIncludeRead] = useState(false);

  const list = useQuery({
    queryKey: ["notifications", includeRead],
    queryFn: async () => {
      const { data, error } = await api.GET("/notifications", {
        params: { query: { include_read: includeRead, limit: 50 } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
      return (data ?? []) as Notification[];
    },
  });

  const markRead = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.POST("/notifications/{notification_id}/read", {
        params: { path: { notification_id: id } },
      });
      if (error) throw new Error(errorMessage(error, t("common.error")));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  const unreadRows = (list.data ?? []).filter((row) => row.status !== "read");

  return (
    <div
      role="dialog"
      aria-label={t("notif.title")}
      className="absolute right-0 top-full z-30 mt-2 w-[min(24rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
    >
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-sm font-medium text-ink">{t("notif.title")}</span>
        {unreadRows.length > 0 && (
          <button
            onClick={() => unreadRows.forEach((row) => markRead.mutate(row.id))}
            className="ml-auto text-xs text-muted transition-colors hover:text-ink"
          >
            {t("notif.markAllRead")}
          </button>
        )}
      </div>

      <div className="max-h-104 overflow-y-auto">
        {list.isLoading && <Loading label={t("common.loading")} />}
        {list.error && (
          <ErrorNote
            message={(list.error as Error).message}
            onRetry={() => list.refetch()}
          />
        )}
        {list.data && list.data.length === 0 && (
          <Empty message={t("notif.empty")} hint={t("notif.emptyHint")} />
        )}
        {list.data?.map((row) => (
          <NotificationRow
            key={row.id}
            notification={row}
            onRead={() => markRead.mutate(row.id)}
            onNavigate={onClose}
          />
        ))}
      </div>

      <div className="border-t border-line px-3 py-2">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={includeRead}
            onChange={(event) => setIncludeRead(event.target.checked)}
            className="h-3.5 w-3.5 rounded border-line"
          />
          {t("notif.showRead")}
        </label>
      </div>
    </div>
  );
}

function NotificationRow({
  notification,
  onRead,
  onNavigate,
}: {
  notification: Notification;
  onRead: () => void;
  onNavigate: () => void;
}) {
  const { t, dateTime } = useI18n();
  const context = notification.context ?? {};
  const isUnread = notification.status !== "read";

  const eventKey = notification.event ?? "";
  const label = EVENT_LABELS[eventKey] ?? "notif.event.unknown";

  const ticker = typeof context.ticker === "string" ? context.ticker : null;
  const stance = typeof context.stance === "string" ? context.stance : null;
  const confidence =
    typeof context.confidence === "number" ? context.confidence : null;

  // Where the reader goes to find the reasoning. An analysis notification
  // names one asset, so it can link straight to it; a monitoring notification
  // may cover several, so it links to the screen that lists them all.
  const destination =
    eventKey === "monitoring_alert"
      ? { to: "/monitoring", label: t("notif.openAlerts") }
      : ticker
        ? { to: `/assets/${ticker}`, label: t("notif.openAnalysis") }
        : null;

  return (
    <div
      className={`border-b border-line px-3 py-2.5 last:border-b-0 ${
        isUnread ? "bg-hover/30" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="rounded bg-hover px-1.5 py-0.5 text-[0.6875rem] uppercase tracking-wide text-muted">
          {t(label)}
        </span>
        <span className="ml-auto text-[0.6875rem] text-faint">
          {dateTime(notification.created_at)}
        </span>
      </div>

      <p className="mt-1.5 text-sm leading-snug text-ink">{body(notification, t)}</p>

      {(stance || confidence !== null) && (
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {stance && (
            <span>
              {t("notif.stance")}:{" "}
              <span className="font-medium text-ink">{stance.replace("_", " ")}</span>
            </span>
          )}
          {confidence !== null && (
            <span>
              {t("notif.confidence")}:{" "}
              <span className="font-medium text-ink">{Math.round(confidence)}%</span>
            </span>
          )}
        </div>
      )}

      <div className="mt-2 flex items-center gap-3 text-xs">
        {destination && (
          <Link
            to={destination.to}
            onClick={onNavigate}
            className="text-muted transition-colors hover:text-rise"
          >
            {destination.label}
          </Link>
        )}
        {isUnread && (
          <button
            onClick={onRead}
            className="ml-auto text-faint transition-colors hover:text-muted"
          >
            {t("notif.markRead")}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * The sentence, composed in the reader's language.
 *
 * The server's `message` is written once, in one language, at the moment the
 * event happened - so it cannot follow a language switch made afterwards. The
 * facts travel in `context` instead, and both languages describe the same
 * stored event from them. `message` is the fallback for an event this build
 * does not know how to phrase, which is the honest behaviour when the server
 * has grown a vocabulary the frontend has not caught up with.
 */
function body(
  notification: Notification,
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
): string {
  const context = notification.context ?? {};

  if (
    notification.event === "analysis_ready" &&
    typeof context.ticker === "string" &&
    typeof context.agents === "number"
  ) {
    return t("notif.body.analysis_ready", {
      ticker: context.ticker,
      agents: context.agents,
    });
  }

  if (
    notification.event === "monitoring_alert" &&
    typeof context.count === "number" &&
    Array.isArray(context.tickers)
  ) {
    const tickers = context.tickers.filter(
      (value): value is string => typeof value === "string",
    );
    // Truncated with the remainder stated rather than silently dropped: a list
    // of five that was really twelve reads as a smaller event than it was.
    const listed =
      tickers.length > 5
        ? `${tickers.slice(0, 5).join(", ")} +${tickers.length - 5}`
        : tickers.join(", ");
    return t("notif.body.monitoring_alert", {
      count: context.count,
      tickers: listed,
    });
  }

  return notification.message;
}

function BellIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-4 w-4"
    >
      <path d="M10 2.5a4.5 4.5 0 0 0-4.5 4.5c0 3.5-1.25 4.75-1.25 4.75h11.5S14.5 10.5 14.5 7A4.5 4.5 0 0 0 10 2.5Z" />
      <path d="M8.5 14.75a1.75 1.75 0 0 0 3 0" />
    </svg>
  );
}
