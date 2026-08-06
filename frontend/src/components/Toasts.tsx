import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { ToastContext, type Toast } from "@/components/toastContext";

/**
 * Transient messages in the top-right corner.
 *
 * Distinct from a notification, and the distinction is the point. A
 * notification is a record: it persists, it counts towards the badge, and it is
 * still there tomorrow. A toast is an interruption for something that just
 * happened *while you were looking* - the other language finishing on the
 * analysis currently open. Both fire for the same event, because the reader who
 * walked away needs the record and the reader still watching needs the nudge.
 *
 * Nothing here is ever the only place something is said. A toast that carried
 * information available nowhere else would lose it to a missed glance.
 */


/** How long one stays up. Long enough to read a sentence, short enough not to
 *  sit over the content it is announcing. */
const DISMISS_AFTER_MS = 6000;

/** Beyond this the oldest is dropped: a stack taller than the viewport is a
 *  worse problem than a missed toast. */
const MAX_VISIBLE = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((toast: Omit<Toast, "id">) => {
    setToasts((current) => {
      const next = [...current, { ...toast, id: Date.now() + Math.random() }];
      return next.slice(-MAX_VISIBLE);
    });
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {createPortal(
        <div
          // `aria-live` polite rather than assertive: this announces something
          // that finished, not something that needs acting on, and interrupting
          // a screen reader mid-sentence for it would be rude.
          aria-live="polite"
          className="pointer-events-none fixed right-4 top-4 z-50 flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2"
        >
          {toasts.map((toast) => (
            <ToastCard key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const accent = toast.tone === "success" ? "border-rise/40" : "border-line";

  return (
    <div
      className={`pointer-events-auto rounded-lg border ${accent} bg-raised/95 p-3 shadow-lg backdrop-blur`}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">{toast.title}</p>
          {toast.body && (
            <p className="mt-0.5 text-xs leading-relaxed text-muted">{toast.body}</p>
          )}
        </div>
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded px-1 text-faint transition-colors hover:text-ink"
        >
          ×
        </button>
      </div>
    </div>
  );
}
