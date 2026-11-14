import { Link } from "react-router-dom";
import { useAuth } from "@/auth/context";
import { useI18n } from "@/i18n/context";
import { traderApi } from "@/trader/client";
import { useTraderQuery } from "@/trader/hooks";
import { HaltButton } from "@/trader/KillControls";
import type { Status } from "@/trader/types";

/**
 * The Trader's state, on every page, with the stop control beside it.
 *
 * It renders for the roles that operate or oversee trading and for nobody else:
 * hiding it from an investor is a convenience, the Trader API enforces who may
 * do what (docs/04-UX-UI/00 principle 8). A halted Trader must never look like
 * a quiet one, so the halted state fills the bar with a sentence instead of a
 * small label, and an unreadable state says the system is unobserved rather
 * than defaulting to "running".
 */
export function StateBar() {
  const { user } = useAuth();
  const allowed = user?.role === "trader" || user?.role === "admin";
  const status = useTraderQuery<Status>(["status"], () => traderApi.GET("/trader/v1/status"), {
    enabled: allowed,
  });
  const { t } = useI18n();
  if (!allowed) return null;

  const state = status.data?.data.trading_state;
  const unset = status.data?.data.unset_limits.length ?? 0;
  const halted = state !== undefined && state !== "RUNNING";
  const unobserved = status.isError || (!status.data && !status.isPending);

  return (
    <div
      role="region"
      aria-label={t("trader.bar.regionLabel")}
      className={`border-b px-4 py-2 ${
        halted || unobserved ? "border-fall/40 bg-fall/10" : "border-line bg-raised"
      }`}
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="text-xs font-medium uppercase tracking-wider text-faint">
          {t("trader.bar.label")}
        </span>
        {status.isPending ? (
          <span className="text-sm text-muted">{t("common.loading")}</span>
        ) : unobserved ? (
          <span role="alert" className="text-sm font-medium text-fall">
            {t("trader.bar.unavailable", {
              cls: (status.error as { cls?: string } | null)?.cls ?? "UNKNOWN",
            })}
          </span>
        ) : (
          <>
            <span
              className={`text-sm font-semibold ${halted ? "text-fall" : "text-ink"}`}
              aria-live="polite"
            >
              {state && t(`trader.state.${state}`)}
            </span>
            {halted && <span className="text-sm text-muted">{t("trader.bar.halted")}</span>}
            {!halted && unset > 0 && (
              <span className="text-sm text-watch">{t("trader.bar.unset", { count: unset })}</span>
            )}
          </>
        )}
        <span className="ml-auto flex items-center gap-2">
          <Link
            to="/trader"
            className="rounded-md px-2 py-1 text-xs text-muted transition-colors hover:bg-hover hover:text-ink"
          >
            {t("trader.bar.openControls")}
          </Link>
          {/* Offered whenever the bar is, even if the status could not load:
              stopping must not depend on being able to read the state. */}
          {user?.role && <HaltButton disabled={state !== undefined && state !== "RUNNING"} />}
        </span>
      </div>
    </div>
  );
}
