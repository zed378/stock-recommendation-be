import { Component, Suspense, lazy, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthContext";
import { useAuth } from "@/auth/context";
import { useI18n } from "@/i18n/context";
import { I18nProvider } from "@/i18n";
import { Layout } from "@/components/Layout";
import { Loading } from "@/components/primitives";
import { ToastProvider } from "@/components/Toasts";
import { Landing } from "@/pages/Landing";
import { Login } from "@/pages/Login";
import { Watchlist } from "@/pages/Watchlist";
import { AssetDetail } from "@/pages/AssetDetail";
import { Portfolio } from "@/pages/Portfolio";
import { Journal } from "@/pages/Journal";
import { Chat } from "@/pages/Chat";
import { Agenda } from "@/pages/Agenda";
import { ScreenBuilder } from "@/pages/ScreenBuilder";
import { MarketChat } from "@/pages/MarketChat";
import { Shared } from "@/pages/Shared";
import { Profile } from "@/pages/Profile";
import { Admin } from "@/pages/Admin";
import { StockPicks } from "@/pages/StockPicks";
import { Monitoring } from "@/pages/Monitoring";

const Trader = lazy(() => import("@/pages/Trader").then((m) => ({ default: m.Trader })));
const TraderApprovals = lazy(() => import("@/pages/TraderApprovals").then((m) => ({ default: m.TraderApprovals })));
const TraderStrategies = lazy(() => import("@/pages/TraderStrategies").then((m) => ({ default: m.TraderStrategies })));
const TraderLimits = lazy(() => import("@/pages/TraderLimits").then((m) => ({ default: m.TraderLimits })));
const TraderParameters = lazy(() => import("@/pages/TraderParameters").then((m) => ({ default: m.TraderParameters })));
const TraderPaper = lazy(() => import("@/pages/TraderPaper").then((m) => ({ default: m.TraderPaper })));
const TraderCredentials = lazy(() => import("@/pages/TraderCredentials").then((m) => ({ default: m.TraderCredentials })));

interface ChunkBoundaryProps {
  title: string;
  body: string;
  reloadLabel: string;
  onReload?: () => void;
  children: ReactNode;
}

interface ChunkBoundaryState {
  failed: boolean;
}

class ChunkErrorBoundary extends Component<ChunkBoundaryProps, ChunkBoundaryState> {
  state: ChunkBoundaryState = { failed: false };

  static getDerivedStateFromError(): ChunkBoundaryState {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const handleReload = this.props.onReload ?? (() => window.location.reload());
    return (
      <section role="alert" className="mx-auto my-8 max-w-lg rounded-lg border border-line bg-raised p-6">
        <h1 className="text-base font-semibold text-ink">{this.props.title}</h1>
        <p className="mt-2 text-sm text-muted">{this.props.body}</p>
        <button
          type="button"
          onClick={handleReload}
          className="mt-4 inline-flex items-center rounded-md border border-line bg-hover px-3.5 py-2 text-sm font-medium text-ink transition-colors hover:border-rise focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rise"
        >
          {this.props.reloadLabel}
        </button>
      </section>
    );
  }
}

export function LazyTraderRoute({
  children,
  onReload,
}: {
  children: ReactNode;
  onReload?: () => void;
}) {
  const { pathname } = useLocation();
  const { t } = useI18n();
  return (
    <ChunkErrorBoundary
      key={pathname}
      title={t("trader.routeError.title")}
      body={t("trader.routeError.body")}
      reloadLabel={t("trader.routeError.reload")}
      onReload={onReload}
    >
      <Suspense fallback={<Loading />}>{children}</Suspense>
    </ChunkErrorBoundary>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Nothing here is a live feed, and market data goes stale on its own
      // schedule, so refetching on every window focus would spend requests to
      // redraw the same numbers.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      // One retry, not three. A 401 or a 404 does not improve by asking again,
      // and the failures that might are already retried inside the backend.
      retry: 1,
    },
  },
});

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? <Layout /> : <Navigate to="/login" replace />;
}

function Public() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? <Navigate to="/watchlist" replace /> : <Login />;
}

export default function App() {
  return (
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <ToastProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Public />} />
              <Route element={<Protected />}>
                <Route path="/watchlist" element={<Watchlist />} />
                <Route path="/assets/:ticker" element={<AssetDetail />} />
                <Route path="/portfolio" element={<Portfolio />} />
                <Route path="/journal" element={<Journal />} />
                <Route path="/picks" element={<StockPicks />} />
                <Route path="/monitoring" element={<Monitoring />} />
                {/* The Trader API enforces who may do what; the link is only hidden
                    for roles that cannot use it. */}
                <Route path="/trader" element={<LazyTraderRoute><Trader /></LazyTraderRoute>} />
                <Route path="/trader/approvals" element={<LazyTraderRoute><TraderApprovals /></LazyTraderRoute>} />
                <Route path="/trader/strategies" element={<LazyTraderRoute><TraderStrategies /></LazyTraderRoute>} />
                <Route path="/trader/limits" element={<LazyTraderRoute><TraderLimits /></LazyTraderRoute>} />
                <Route path="/trader/parameters" element={<LazyTraderRoute><TraderParameters /></LazyTraderRoute>} />
                <Route path="/trader/paper" element={<LazyTraderRoute><TraderPaper /></LazyTraderRoute>} />
                <Route path="/trader/credentials" element={<LazyTraderRoute><TraderCredentials /></LazyTraderRoute>} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/agenda" element={<Agenda />} />
                <Route path="/screens" element={<ScreenBuilder />} />
                <Route path="/market-chat" element={<MarketChat />} />
                <Route path="/shared" element={<Shared />} />
                <Route path="/profile" element={<Profile />} />
                {/* Registered for everyone; the page itself explains the role
                    requirement. An unlinked route is still reachable by typing
                    it, so hiding the link is not the control - the backend is,
                    and this says why rather than 403ing every panel. */}
                {/* The section is part of the address. As tab state, no admin
                    section could be bookmarked, linked, or survive a reload. */}
                <Route path="/admin" element={<Admin />} />
                <Route path="/admin/:section" element={<Admin />} />
              </Route>
              <Route path="*" element={<Navigate to="/watchlist" replace />} />
            </Routes>
          </BrowserRouter>
          </ToastProvider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
