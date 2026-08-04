import { createContext, useContext } from "react";
import type { components } from "@/api/schema";

/**
 * Auth context and hook, separated from the provider for the same reason as
 * the i18n pair: a module exporting both a component and a hook cannot be hot
 * reloaded without the context identity changing underneath every consumer,
 * which throws rather than degrading.
 */

export type User = components["schemas"]["UserResponse"];

export interface Auth {
  user: User | null;
  /** True until the stored token has been checked against the server. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, fullName: string) => Promise<void>;
  signOut: () => void;
  /** Set when a session ended on its own, so login can say why. */
  expiredNotice: boolean;
  dismissExpiredNotice: () => void;
}

export const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an AuthProvider");
  return context;
}
