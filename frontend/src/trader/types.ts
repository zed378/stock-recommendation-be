/**
 * Response bodies of the Trader API, derived from the OpenAPI schema generated
 * by `python -m aidss_trader.api.openapi` and `openapi-typescript`.
 *
 * Money and quantities arrive as strings (docs/07-API-CONTRACTS/00) and stay
 * strings until they are shown, so the UI never rounds a quantity differently
 * from what will be sent.
 */

import type { components } from "@/api/trader-schema";

type Schemas = components["schemas"];

export type TradingState = Schemas["StatusData"]["trading_state"];
export type Mode = Schemas["StrategyItem"]["mode"];

export type Status = Schemas["StatusData"];
export type OpenOrder = Schemas["OpenOrderModel"];
export type PendingApproval = Schemas["PendingApprovalModel"];
export type Dashboard = Schemas["DashboardData"];
export type Approval = Schemas["ApprovalCardModel"];
export type Intent = Schemas["IntentItem"];
export type Gate = Schemas["GateModel"];
export type Strategy = Schemas["StrategyItem"];
export type Promotion = Schemas["PromotionData"];
export type TradingEvent = Schemas["TradingEventItem"];
export type Limits = Schemas["LimitsData"];
export type Reconciliation = Schemas["ReconciliationData"];
export type KillResult = Schemas["KillData"];
export type Allowlist = Schemas["AllowlistData"];
export type PairCatalog = Schemas["CatalogData"];
export type CatalogPair = Schemas["CatalogPair"];
export type PairGroups = Schemas["PairGroupsData"];
export type StrategyParams = Schemas["StrategyParamsData"];
export type PaperConfig = Schemas["PaperConfigData"];
export type CredentialKind = Schemas["CredentialItemModel"]["kind"];
export type CredentialItem = Schemas["CredentialItemModel"];
export type Credentials = Schemas["CredentialsData"];
export type PromotionThresholds = Schemas["PromotionThresholdsData"];
export type PositionItem = Schemas["PositionItemModel"];
export type OriginPortfolio = Schemas["OriginPortfolioModel"];
export type BacktestRun = Schemas["BacktestRunItem"];
export type Portfolio = Schemas["PortfolioData"];
export type StrategyDef = Schemas["StrategyDefModel"];
export type StrategyKind = Schemas["KindModel"];
export type StrategyBacktests = Schemas["StrategyBacktestData"];
export type BacktestSummary = Schemas["BacktestSummaryModel"];
export type StrategyPaper = Schemas["StrategyPaperData"];
export type BacktestJob = Schemas["BacktestJobData"];
export type Order = Schemas["OrderItem"];
export type LedgerEntry = Schemas["LedgerItem"];
export type AuditEntry = Schemas["AuditItem"];
