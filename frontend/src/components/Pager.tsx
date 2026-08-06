import { useI18n } from "@/i18n/context";
import { Button, inputClass } from "@/components/primitives";

/**
 * Moving through a list, and saying how much of it you are looking at.
 *
 * Shared rather than written per screen, because the part that matters is the
 * same everywhere: a list that silently shows its first fifty rows is a screen
 * that stops telling the truth on the fifty-first, and every admin list here
 * grows without bound - audit rows, jobs, issuers.
 *
 * The page size is offered rather than fixed. "Show me 200" is a real thing to
 * want when scanning for one row, and a fixed size turns it into ten clicks.
 */

export type PageState = { limit: number; offset: number };

/** Offered sizes. Small enough to render fast, large enough to scan. */
const SIZES = [25, 50, 100, 200];

export function Pager({
  total,
  shown,
  page,
  onChange,
}: {
  total: number;
  /** How many rows this page actually returned, which is not always `limit`. */
  shown: number;
  page: PageState;
  onChange: (next: PageState) => void;
}) {
  const { t, n } = useI18n();

  const first = total === 0 ? 0 : page.offset + 1;
  const last = page.offset + shown;
  const hasPrevious = page.offset > 0;
  const hasNext = last < total;

  // Rendered even for a single page: the count is the useful part, and a
  // control that appears only past some threshold makes "is that everything?"
  // unanswerable on exactly the screens where it is cheapest to answer.
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line pt-3">
      <span className="text-xs text-muted">
        {total === 0
          ? t("pager.none")
          : t("pager.range", { first: n(first, 0), last: n(last, 0), total: n(total, 0) })}
      </span>

      <label className="flex items-center gap-1.5 text-xs text-faint">
        {t("pager.perPage")}
        <select
          className={`${inputClass} py-0.5 text-xs`}
          value={page.limit}
          // Back to the start on resize. Keeping the offset would land the
          // reader in the middle of a differently-sized list, at rows they
          // have not seen and cannot place.
          onChange={(event) => onChange({ limit: Number(event.target.value), offset: 0 })}
        >
          {SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>

      <div className="ml-auto flex gap-2">
        <Button
          size="sm"
          variant="ghost"
          disabled={!hasPrevious}
          onClick={() => onChange({ ...page, offset: Math.max(0, page.offset - page.limit) })}
        >
          {t("pager.previous")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!hasNext}
          onClick={() => onChange({ ...page, offset: page.offset + page.limit })}
        >
          {t("pager.next")}
        </Button>
      </div>
    </div>
  );
}
