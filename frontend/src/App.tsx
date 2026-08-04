import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthContext";
import { useAuth } from "@/auth/context";
import { I18nProvider } from "@/i18n";
import { Layout } from "@/components/Layout";
import { Loading } from "@/components/primitives";
import { Login } from "@/pages/Login";
import { Watchlist } from "@/pages/Watchlist";
import { AssetDetail } from "@/pages/AssetDetail";
import { Portfolio } from "@/pages/Portfolio";
import { Journal } from "@/pages/Journal";
import { Chat } from "@/pages/Chat";
import { Admin } from "@/pages/Admin";

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
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Public />} />
              <Route element={<Protected />}>
                <Route path="/watchlist" element={<Watchlist />} />
                <Route path="/assets/:ticker" element={<AssetDetail />} />
                <Route path="/portfolio" element={<Portfolio />} />
                <Route path="/journal" element={<Journal />} />
                <Route path="/chat" element={<Chat />} />
                {/* Registered for everyone; the page itself explains the role
                    requirement. An unlinked route is still reachable by typing
                    it, so hiding the link is not the control - the backend is,
                    and this says why rather than 403ing every panel. */}
                <Route path="/admin" element={<Admin />} />
              </Route>
              <Route path="*" element={<Navigate to="/watchlist" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
