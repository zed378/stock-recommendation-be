import { useEffect, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useI18n } from "@/i18n/context";
import { unwrap, TraderError, type Envelope } from "@/trader/client";

type Fetcher = () => Promise<{ data?: unknown; error?: unknown; response: Response }>;

/**
 * One poll interval for everything on the operator surface.
 *
 * Short on purpose: the Trader's own loops run every ten seconds, and a state
 * bar that lags a halt by a minute would show a stopped system as running.
 * `retry: false` because a failed read is a fact to show, not something to hide
 * behind two silent retries; the panel says it could not load and offers a retry.
 */
export const TRADER_POLL_MS = 10_000;

export function useTraderQuery<T>(
  key: readonly unknown[],
  fetcher: Fetcher,
  options: { enabled?: boolean; interval?: number | false } = {},
): UseQueryResult<Envelope<T>, TraderError> {
  return useQuery<Envelope<T>, TraderError>({
    queryKey: ["trader", ...key],
    queryFn: () => unwrap<T>(fetcher()),
    refetchInterval: options.interval ?? TRADER_POLL_MS,
    // Polling continues in a background tab: a kill-switch state read an hour
    // ago must not be what greets the user when they switch back.
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
    retry: false,
    enabled: options.enabled ?? true,
  });
}

/** A clock that ticks, so "updated 12 s ago" keeps counting between polls. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** "12 s", "3 m", "2 h" for the age of a reading. */
export function useAgeLabel() {
  const { t } = useI18n();
  return (seconds: number) =>
    seconds < 60
      ? t("trader.age.seconds", { n: seconds })
      : seconds < 3600
        ? t("trader.age.minutes", { n: Math.floor(seconds / 60) })
        : t("trader.age.hours", { n: Math.floor(seconds / 3600) });
}

