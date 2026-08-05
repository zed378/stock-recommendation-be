import type { ReactNode } from "react";
import { useI18n } from "@/i18n/context";

/** Small shared pieces, kept in one file so the pages stay about their subject. */

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-line bg-raised ${className}`}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {typeof title === "string" ? (
            <h2 className="text-sm font-medium text-ink">{title}</h2>
          ) : (
            title
          )}
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({
  variant = "primary",
  size = "md",
  busy = false,
  children,
  className = "",
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
  size?: "sm" | "md";
  busy?: boolean;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md font-medium " +
    "transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rise";
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm" };
  const variants = {
    primary: "bg-rise/15 text-rise border border-rise/30 hover:bg-rise/25",
    ghost: "bg-transparent text-muted border border-line hover:bg-hover hover:text-ink",
    danger: "bg-transparent text-fall/80 border border-fall/25 hover:bg-fall/10",
  };
  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      disabled={disabled || busy}
      {...rest}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block size-3 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink " +
  "placeholder:text-faint focus:border-rise/50 focus:outline-none";

/**
 * An empty state that says what to do next.
 *
 * "No data" on its own is a dead end; almost every empty screen here has an
 * obvious next action, and naming it is the difference between an interface
 * that stalls and one that guides.
 */
export function Empty({
  message,
  hint,
  action,
}: {
  message: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <p className="text-sm text-muted">{message}</p>
      {hint && <p className="max-w-sm text-xs text-faint">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted">
      <Spinner />
      {label ?? t("common.loading")}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col items-start gap-2 rounded-md border border-fall/25 bg-fall/5 px-3 py-2.5">
      <p className="text-sm text-fall/90">{message}</p>
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      )}
    </div>
  );
}

/**
 * A short note attached to a figure, explaining what it does and does not mean.
 *
 * Used wherever a number is easy to misread - a year-to-date figure beside an
 * annual one, a confidence score that is not a probability. The caveat travels
 * with the number rather than living in documentation nobody opens.
 */
export function Caveat({ children }: { children: ReactNode }) {
  return (
    <p className="mt-2 border-l-2 border-watch/40 pl-2.5 text-xs leading-relaxed text-faint">
      {children}
    </p>
  );
}

export function Stat({
  label,
  value,
  tone = "neutral",
  mono = true,
}: {
  label: string;
  value: ReactNode;
  // `watch` is distinct from `fall` on purpose: rejected bars are worth
  // noticing and are not a failure, and colouring the two the same would make
  // every warning read as an outage.
  tone?: "neutral" | "rise" | "fall" | "watch";
  mono?: boolean;
}) {
  const tones = {
    neutral: "text-ink",
    rise: "text-rise",
    fall: "text-fall",
    watch: "text-watch",
  };
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className={`mt-0.5 text-sm ${tones[tone]} ${mono ? "font-mono tnum" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
