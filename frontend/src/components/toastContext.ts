import { createContext, useContext } from "react";

/**
 * The toast context and its hook, kept apart from the provider component.
 *
 * Not a style preference, and not the linter being fussy. A module that exports
 * both a component and a hook cannot be hot-reloaded: Fast Refresh replaces the
 * module, `createContext` runs again, and every consumer suddenly holds a
 * different context object from the one the provider is filling. This project
 * has already lost an afternoon to exactly that - the i18n context did it, the
 * app white-screened on any edit, and the warning had been dismissed as
 * "only costs HMR state".
 */

export type Toast = {
  id: number;
  title: string;
  body?: string;
  tone?: "info" | "success";
};

export type ToastApi = { show: (toast: Omit<Toast, "id">) => void };

export const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  // A no-op rather than a throw. A toast is never the only place something is
  // said - the notification carries the same fact - so a component rendered
  // outside the provider should keep working rather than crash over a nicety.
  return context ?? { show: () => {} };
}
