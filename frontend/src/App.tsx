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
import {
  Watchlist,
  AssetDetail,
  Portfolio,
  Journal,
  Chat,
  Agenda,
  ScreenBuilder,
  MarketChat,
  Shared,
  Profile,
  Admin,
  StockPicks,
  Monitoring,
} from "@/lazyPages";

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

// One boundary per route, inside the layout: the sidebar stays while a chunk loads, and a
// chunk that fails to load shows a reload prompt instead of a blank screen.
export function LazyRoute({
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

export const LazyTraderRoute = LazyRoute;

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
                <Route path="/watchlist" element={<LazyRoute><Watchlist /></LazyRoute>} />
                <Route path="/assets/:ticker" element={<LazyRoute><AssetDetail /></LazyRoute>} />
                <Route path="/portfolio" element={<LazyRoute><Portfolio /></LazyRoute>} />
                <Route path="/journal" element={<LazyRoute><Journal /></LazyRoute>} />
                <Route path="/picks" element={<LazyRoute><StockPicks /></LazyRoute>} />
                <Route path="/monitoring" element={<LazyRoute><Monitoring /></LazyRoute>} />
                {/* The Trader API enforces who may do what; the link is only hidden
                    for roles that cannot use it. */}
                <Route path="/trader" element={<LazyRoute><Trader /></LazyRoute>} />
                <Route path="/trader/approvals" element={<LazyRoute><TraderApprovals /></LazyRoute>} />
                <Route path="/trader/strategies" element={<LazyRoute><TraderStrategies /></LazyRoute>} />
                <Route path="/trader/limits" element={<LazyRoute><TraderLimits /></LazyRoute>} />
                <Route path="/trader/parameters" element={<LazyRoute><TraderParameters /></LazyRoute>} />
                <Route path="/trader/paper" element={<LazyRoute><TraderPaper /></LazyRoute>} />
                <Route path="/trader/credentials" element={<LazyRoute><TraderCredentials /></LazyRoute>} />
                <Route path="/chat" element={<LazyRoute><Chat /></LazyRoute>} />
                <Route path="/agenda" element={<LazyRoute><Agenda /></LazyRoute>} />
                <Route path="/screens" element={<LazyRoute><ScreenBuilder /></LazyRoute>} />
                <Route path="/market-chat" element={<LazyRoute><MarketChat /></LazyRoute>} />
                <Route path="/shared" element={<LazyRoute><Shared /></LazyRoute>} />
                <Route path="/profile" element={<LazyRoute><Profile /></LazyRoute>} />
                {/* Registered for everyone; the page itself explains the role
                    requirement. An unlinked route is still reachable by typing
                    it, so hiding the link is not the control - the backend is,
                    and this says why rather than 403ing every panel. */}
                {/* The section is part of the address. As tab state, no admin
                    section could be bookmarked, linked, or survive a reload. */}
                <Route path="/admin" element={<LazyRoute><Admin /></LazyRoute>} />
                <Route path="/admin/:section" element={<LazyRoute><Admin /></LazyRoute>} />
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
