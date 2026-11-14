/**
 * Response bodies of the Trader API, as the Python routes build them.
 *
 * Declared by hand because the API does not declare response models yet; a
 * change in `aidss_trader/api/app.py` needs the matching change here, and the
 * `npm run typecheck` will not catch a drift. Money and quantities arrive as
 * strings (docs/07-API-CONTRACTS/00) and stay strings until they are shown, so
 * the UI never rounds a quantity differently from what will be sent.
 */

export type TradingState = "RUNNING" | "HALTED" | "CANCELLING" | "FLATTENING";
export type Mode = "PAPER" | "APPROVAL" | "AUTO";

export interface Status {
  trading_state: TradingState;
  unset_limits: string[];
  modes: Record<string, Mode>;
}

export interface OpenOrder {
  pair: string;
  side: "BUY" | "SELL";
  type: "LIMIT" | "MARKET";
  state: string;
  client_order_id: string;
}

export interface PendingApproval {
  intent_identity: string;
  expires_at: string;
}

export interface Dashboard {
  trading_state: TradingState;
  open_orders: OpenOrder[];
  approvals_pending: PendingApproval[];
}

export interface Approval {
  state: "AWAITING" | "APPROVED" | "DENIED" | "EXPIRED";
  expires_at: string;
  decided_by: string | null;
  reason: string | null;
}

export interface Intent {
  identity: string;
  origin: string;
  pair: string;
  side: "BUY" | "SELL";
  entry_price: string;
  quantity: string;
  stop_price: string | null;
  risk_amount_idr: string | null;
  state: string;
  created_at: string;
  intent_hash: string;
  approval: Approval | null;
}

export interface Gate {
  name: string;
  measured: string | null;
  threshold: string | null;
  passed: boolean;
  reason: string;
}

export interface Strategy {
  strategy_id: string;
  version: string;
  mode: Mode;
  since: string;
}

export interface Promotion {
  mode: Mode;
  next: Mode | null;
  gates: Gate[];
}

export interface TradingEvent {
  id: string;
  kind: string;
  severity: "INFO" | "WARN" | "CRITICAL";
  message: string;
  created_at: string;
  acked_at: string | null;
  mobile: string;
}

export interface Limits {
  limits: Record<string, string | null> | null;
  unset: string[];
}

export interface Reconciliation {
  runs: { started_at: string; result: string; differences: number }[];
  unresolved: {
    kind: string;
    reference: string;
    local_value: string | null;
    exchange_value: string | null;
  }[];
}

export interface KillResult {
  event_id: string;
  tier: "HALT" | "CANCEL" | "FLATTEN";
}

export interface Allowlist {
  pairs: string[];
  min_quote_volume_24h_idr: string | null;
  max_spread_pct: string | null;
  /** On the allowlist and the liquidity filter fully set. */
  active: boolean;
}

export interface StrategyParams {
  configured: boolean;
  /** Plain strings as stored, or null when never set. */
  params: Record<string, string> | null;
  version: string | null;
  mode: Mode | null;
  max_history_bars: number;
}

export interface PaperConfig {
  configured: boolean;
  slippage_pct?: string;
  partial_fill_fraction?: string;
  maker_fee_pct?: string;
  taker_fee_pct?: string;
  tax_pct?: string;
  clearing_pct?: string;
  start_equity_idr?: string;
  /** Simulated fills already recorded; they keep the numbers they were made with. */
  paper_fills: number;
}
