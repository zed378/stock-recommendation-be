import { useCallback, useState } from "react";

/**
 * Which navigation groups the reader has folded away, remembered across visits.
 *
 * Kept in its own module, apart from the sidebar component, for the usual reason in
 * this project: a file that exports both a hook and a component cannot be hot
 * reloaded.
 *
 * Browser storage is a convenience and nothing more. It can be empty, blocked, or throw
 * (a private window, cleared site data), so every read and write is guarded and the
 * menu simply starts fully open when it cannot be used. Nothing here is state that must
 * persist: forgetting it costs a click.
 */

const KEY = "aidss.nav.collapsed";

export type Collapsed = Record<string, boolean>;

export function readCollapsed(): Collapsed {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    // Only booleans are kept: a hand-edited or stale value must not break the menu.
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(([, v]) => typeof v === "boolean"),
    ) as Collapsed;
  } catch {
    return {};
  }
}

export function writeCollapsed(value: Collapsed): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(value));
  } catch {
    // Not remembered this time; the menu still works.
  }
}

export function useCollapsedGroups() {
  const [collapsed, setCollapsed] = useState<Collapsed>(readCollapsed);

  // Decided from the state being replaced, not from storage: when storage is blocked a read
  // returns nothing, and a toggle based on it could fold a group but never unfold it.
  const update = useCallback((group: string, next: (current: boolean) => boolean) => {
    setCollapsed((current) => {
      const was = current[group] ?? false;
      const now = next(was);
      if (now === was) return current;
      const merged = { ...current, [group]: now };
      writeCollapsed(merged);
      return merged;
    });
  }, []);

  const toggle = useCallback((group: string) => update(group, (was) => !was), [update]);
  const expand = useCallback((group: string) => update(group, () => false), [update]);

  return { collapsed, toggle, expand };
}
