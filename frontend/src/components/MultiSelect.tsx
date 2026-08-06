import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/i18n/context";
import { inputClass } from "@/components/primitives";

/**
 * Pick several from a long list, by typing.
 *
 * A plain `<select multiple>` would be less code and worse: it shows about six
 * of its options at a time, requires ctrl-click to add a second, and cannot be
 * searched at all. The list this exists for is IDX's sub-sectors - dozens of
 * them, with names nobody recalls exactly - so typing is how anybody finds one.
 *
 * Built rather than installed, because the alternative is a combobox library
 * heavier than the rest of the page for one control.
 */
export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder,
  label,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  label: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const container = useRef<HTMLDivElement>(null);

  // Closed by clicking away, which is what people do instead of finding the
  // control again. Bound on the document rather than on a backdrop element so
  // the rest of the page stays interactive while it is open.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const matching = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((o) => o.toLowerCase().includes(needle)) : options;
  }, [options, query]);

  const toggle = (option: string) => {
    // A new array rather than a mutated one: the caller holds this in state
    // and a mutated array is the same reference, so nothing re-renders.
    onChange(
      selected.includes(option)
        ? selected.filter((value) => value !== option)
        : [...selected, option],
    );
  };

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className={`${inputClass} flex min-w-48 items-center gap-2 text-left`}
      >
        <span className="flex-1 truncate text-xs">
          {selected.length === 0 ? (
            <span className="text-faint">{placeholder ?? label}</span>
          ) : (
            // Named while they fit, counted after. Three chips is information;
            // twenty is a wall that pushes the rest of the toolbar off screen.
            <span className="text-ink">
              {selected.length <= 2
                ? selected.join(", ")
                : t("multiSelect.count", { count: String(selected.length) })}
            </span>
          )}
        </span>
        <span className="text-faint">▾</span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-72 max-w-[80vw] rounded-lg border border-line bg-raised p-2 shadow-lg">
          <input
            autoFocus
            className={`${inputClass} mb-2 text-xs`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("common.search")}
          />

          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mb-1 w-full rounded px-2 py-1 text-left text-xs text-faint hover:bg-hover hover:text-ink"
            >
              {t("multiSelect.clear")}
            </button>
          )}

          <ul className="max-h-64 overflow-y-auto">
            {matching.length === 0 ? (
              <li className="px-2 py-1.5 text-xs text-faint">{t("multiSelect.noMatches")}</li>
            ) : (
              matching.map((option) => (
                <li key={option}>
                  <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs text-ink hover:bg-hover">
                    <input
                      type="checkbox"
                      className="accent-rise"
                      checked={selected.includes(option)}
                      onChange={() => toggle(option)}
                    />
                    <span className="truncate">{option}</span>
                  </label>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
