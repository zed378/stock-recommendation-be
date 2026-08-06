import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { storedToken } from "@/api/client";
import { useToast } from "@/components/toastContext";
import { useI18n } from "@/i18n/context";

/**
 * One socket for the whole session, turning server events into refetches.
 *
 * What it replaces is polling, not requesting. The work still runs on the job
 * queue - that is what stopped a long analysis being killed by a proxy at a
 * hundred seconds - and this is how the browser learns it finished, instead of
 * asking every few seconds whether anything has.
 *
 * **The polling underneath stays.** A socket that quietly stops delivering
 * looks exactly like a system with nothing to report, and the difference only
 * shows up as a user staring at a spinner that will never move. The intervals
 * elsewhere are slow enough to cost nothing and short enough to be a floor
 * under this: when the socket works they never fire usefully, and when a proxy
 * refuses the upgrade the product still works, just less promptly.
 *
 * **An event carries an id, never content.** The client refetches through the
 * ordinary authenticated endpoints, so the socket cannot become a second way
 * to read something REST would have refused.
 */

/** Backoff between reconnection attempts. */
const RECONNECT_MIN_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

type ServerEvent = {
  event: string;
  data?: Record<string, unknown>;
};

/** Which cached queries each event invalidates. */
const INVALIDATES: Record<string, string[][]> = {
  analysis_ready: [["analysis"], ["strategy"], ["notifications"], ["notifications-unread-count"]],
  // The rendering landed on an analysis the reader may already be looking at.
  // Invalidating `analysis` is what makes the language switch appear without a
  // reload - it only shows once both languages exist.
  translation_ready: [["analysis"], ["notifications"], ["notifications-unread-count"]],
  recommendation_updated: [["analysis"], ["strategy"]],
  monitoring_alert: [["alerts"], ["monitoring-quotes"], ["notifications"], ["notifications-unread-count"]],
  news_ingested: [["news"], ["notifications"], ["notifications-unread-count"]],
  report_ready: [["notifications"], ["notifications-unread-count"]],
  ingestion_failed: [["notifications"], ["notifications-unread-count"]],
  schedule_needs_attention: [["news-schedules"], ["notifications"], ["notifications-unread-count"]],
  budget_threshold_reached: [["admin-budget"], ["notifications"], ["notifications-unread-count"]],
};

function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/api/ws/events`;
}

export function useEvents(enabled: boolean): { connected: boolean } {
  const queryClient = useQueryClient();
  const { show } = useToast();
  const { t } = useI18n();
  const [connected, setConnected] = useState(false);
  //: Kept in a ref so the reconnect loop can be torn down from the effect
  //: cleanup without the socket itself being a dependency.
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let closed = false;
    let delay = RECONNECT_MIN_MS;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      const token = storedToken();
      // No token means signed out. Reconnecting would spin against a socket
      // that can only be refused.
      if (!token) return;

      const socket = new WebSocket(socketUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        // The token goes in the first frame rather than the URL: a browser
        // cannot set headers on a WebSocket handshake, and a query parameter
        // would put the bearer token into every access and proxy log on the
        // way.
        socket.send(JSON.stringify({ token }));
      };

      socket.onmessage = (message) => {
        let parsed: ServerEvent;
        try {
          parsed = JSON.parse(message.data as string) as ServerEvent;
        } catch {
          return;
        }

        if (parsed.event === "ready") {
          setConnected(true);
          // Reset only once the server has accepted us. Resetting on `onopen`
          // would treat a socket that opens and is immediately refused as a
          // success and retry it in a tight loop.
          delay = RECONNECT_MIN_MS;
          return;
        }
        if (parsed.event === "ping") return;

        for (const key of INVALIDATES[parsed.event] ?? []) {
          queryClient.invalidateQueries({ queryKey: key });
        }

        // A toast as well as the notification, not instead of it. The reader
        // who walked away needs the record; the one still watching the analysis
        // needs to know the switch has just become useful.
        if (parsed.event === "translation_ready") {
          const ticker = String(parsed.data?.ticker ?? "");
          show({
            tone: "success",
            title: t("toast.translationReady"),
            body: ticker ? t("toast.translationReadyFor", { ticker }) : undefined,
          });
        }
      };

      socket.onclose = () => {
        setConnected(false);
        socketRef.current = null;
        if (closed) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, RECONNECT_MAX_MS);
      };

      // `onerror` is always followed by `onclose`, so reconnection is handled
      // in one place rather than raced between two handlers.
      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      socketRef.current?.close();
      socketRef.current = null;
      setConnected(false);
    };
  }, [enabled, queryClient, show, t]);

  return { connected };
}
