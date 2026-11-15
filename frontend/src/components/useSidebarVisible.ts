import { useCallback, useState } from "react";

/**
 * Whether the desktop sidebar is shown, remembered across visits.
 *
 * Same rules as the folded groups next to it: storage is a convenience, every access is
 * guarded, and the sidebar defaults to shown when it cannot be read. On narrow screens the
 * sidebar is a drawer and this does not apply.
 */

const KEY = "aidss.nav.sidebar";

export function readSidebarVisible(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "hidden";
  } catch {
    return true;
  }
}

function write(visible: boolean): void {
  try {
    window.localStorage.setItem(KEY, visible ? "shown" : "hidden");
  } catch {
    // Not remembered this time; the sidebar still works.
  }
}

export function useSidebarVisible() {
  const [visible, setVisible] = useState<boolean>(readSidebarVisible);
  const set = useCallback((next: boolean) => {
    setVisible(next);
    write(next);
  }, []);
  return { visible, hide: useCallback(() => set(false), [set]), show: useCallback(() => set(true), [set]) };
}
