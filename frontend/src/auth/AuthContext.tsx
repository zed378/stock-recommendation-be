import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  api,
  clearToken,
  errorMessage,
  SESSION_EXPIRED,
  storeToken,
  storedToken,
} from "@/api/client";
import { AuthContext, type User } from "./context";

/**
 * Exports only the provider; the hook lives in `./context`, so editing either
 * hot-reloads rather than throwing "must be used inside an AuthProvider".
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [expiredNotice, setExpiredNotice] = useState(false);

  // A stored token is a claim, not proof. It is verified against /auth/me
  // before the app renders as signed in - otherwise a revoked account or a
  // rotated signing secret shows the full interface and then fails every
  // request in it, which reads as an outage rather than as a finished session.
  useEffect(() => {
    if (!storedToken()) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    api
      .GET("/auth/me")
      .then(({ data }) => {
        if (cancelled) return;
        if (data) setUser(data);
        else clearToken();
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setExpiredNotice(true);
    };
    window.addEventListener(SESSION_EXPIRED, onExpired);

    // Periodically check if the token expires while the user is idle
    const checkExpiry = () => {
      storedToken();
    };
    const interval = setInterval(checkExpiry, 5000);

    return () => {
      window.removeEventListener(SESSION_EXPIRED, onExpired);
      clearInterval(interval);
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { data, error } = await api.POST("/auth/login", {
      body: { email, password },
    });
    if (error || !data) throw new Error(errorMessage(error, "auth.failed"));

    storeToken(data.access_token, data.expires_at);
    const me = await api.GET("/auth/me");
    if (!me.data) {
      clearToken();
      throw new Error(errorMessage(me.error, "auth.failed"));
    }
    setUser(me.data);
    setExpiredNotice(false);
  }, []);

  const signUp = useCallback(
    async (email: string, password: string, fullName: string) => {
      const { error } = await api.POST("/auth/register", {
        body: { email, password, full_name: fullName || null },
      });
      if (error) throw new Error(errorMessage(error, "auth.registerFailed"));
      // Registering does not return a token, so sign in with the same
      // credentials rather than leaving the user at a form they just completed.
      await signIn(email, password);
    },
    [signIn],
  );

  const signOut = useCallback(() => {
    clearToken();
    setUser(null);
    setExpiredNotice(false);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signIn,
        signUp,
        signOut,
        expiredNotice,
        dismissExpiredNotice: () => setExpiredNotice(false),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
