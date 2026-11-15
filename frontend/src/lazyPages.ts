import { lazy } from "react";
import type { ComponentType } from "react";

/**
 * The signed-in pages, each in its own chunk.
 *
 * `Landing` and `Login` stay in the main bundle: they are what a signed-out visitor
 * sees first, and paying a second request for them would delay the one screen that
 * has to be fast. Everything behind the login is fetched when its route is opened.
 *
 * `loaders` is exported so a test can resolve every one of them. The failure this
 * guards is a page whose export was renamed: `lazy()` would then render `undefined`
 * and the route would blow up at runtime, while the type checker (which sees only the
 * `.then` callback) stays green.
 */
type PageModule = Record<string, unknown>;

function page(load: () => Promise<PageModule>, name: string) {
  return lazy(() =>
    load().then((m) => ({ default: m[name] as ComponentType })),
  );
}

export const loaders = {
  Watchlist: () => import("@/pages/Watchlist"),
  AssetDetail: () => import("@/pages/AssetDetail"),
  Portfolio: () => import("@/pages/Portfolio"),
  Journal: () => import("@/pages/Journal"),
  Chat: () => import("@/pages/Chat"),
  Agenda: () => import("@/pages/Agenda"),
  ScreenBuilder: () => import("@/pages/ScreenBuilder"),
  MarketChat: () => import("@/pages/MarketChat"),
  Shared: () => import("@/pages/Shared"),
  Profile: () => import("@/pages/Profile"),
  Admin: () => import("@/pages/Admin"),
  StockPicks: () => import("@/pages/StockPicks"),
  Monitoring: () => import("@/pages/Monitoring"),
} satisfies Record<string, () => Promise<PageModule>>;

export const Watchlist = page(loaders.Watchlist, "Watchlist");
export const AssetDetail = page(loaders.AssetDetail, "AssetDetail");
export const Portfolio = page(loaders.Portfolio, "Portfolio");
export const Journal = page(loaders.Journal, "Journal");
export const Chat = page(loaders.Chat, "Chat");
export const Agenda = page(loaders.Agenda, "Agenda");
export const ScreenBuilder = page(loaders.ScreenBuilder, "ScreenBuilder");
export const MarketChat = page(loaders.MarketChat, "MarketChat");
export const Shared = page(loaders.Shared, "Shared");
export const Profile = page(loaders.Profile, "Profile");
export const Admin = page(loaders.Admin, "Admin");
export const StockPicks = page(loaders.StockPicks, "StockPicks");
export const Monitoring = page(loaders.Monitoring, "Monitoring");
