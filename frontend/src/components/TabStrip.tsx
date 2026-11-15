import { useEffect, useRef } from "react";

export interface TabItem<T extends string> {
  id: T;
  label: string;
}

/**
 * A row of tabs that never widens the page.
 *
 * The asset page has six tabs, which add up to about 520px. A plain flex row of that
 * width pushed the whole document past a 375px phone screen, so the page scrolled
 * sideways. The strip now scrolls inside itself instead: every tab keeps its full label
 * (`shrink-0 whitespace-nowrap`), and the one that is selected is scrolled into view, so
 * restoring or switching to a tab that starts off-screen does not leave it hidden.
 *
 * Under `sm` the tabs get a 44px tap height; from `sm` up they keep the compact desktop
 * size.
 */
export function TabStrip<T extends string>({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: TabItem<T>[];
  active: T;
  onChange: (id: T) => void;
  label?: string;
}) {
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Optional call: jsdom does not implement it.
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [active]);

  return (
    <nav
      aria-label={label}
      className="flex gap-1 overflow-x-auto overscroll-x-contain border-b border-line"
    >
      {tabs.map((item) => {
        const selected = active === item.id;
        return (
          <button
            key={item.id}
            ref={selected ? activeRef : undefined}
            type="button"
            aria-current={selected ? "page" : undefined}
            onClick={() => onChange(item.id)}
            className={`shrink-0 whitespace-nowrap border-b-2 px-3 py-3 text-sm transition-colors sm:py-2 ${
              selected ? "border-rise text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}
