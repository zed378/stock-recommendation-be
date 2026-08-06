import type { components } from "@/api/schema";

/**
 * The analysis as a PDF, built in the browser.
 *
 * Client-side on purpose. Rendering a document is per-reader work with no
 * shared result to cache, so putting it on the server buys nothing and costs a
 * request that has to hold open while a layout engine runs - the same shape of
 * mistake that made the analysis itself time out behind a proxy.
 *
 * Written as text rather than captured as an image. A screenshot of the page
 * would be simpler and would produce a file nobody can search, copy a figure
 * out of, or read with a screen reader, at several times the size.
 *
 * `jspdf` is imported dynamically by the caller so it lands in its own chunk:
 * it is around a third of the main bundle, and most sessions never export
 * anything.
 */

type Recommendation = components["schemas"]["RecommendationResponse"];
type Guidance = components["schemas"]["GuidanceResponse"];

export type ExportInput = {
  ticker: string;
  timeframe: string;
  generatedAt: string;
  recommendation?: Recommendation | null;
  guidance?: Guidance | null;
  agents: Record<string, Record<string, unknown>>;
  /** Rendered in the reader's current language, so the file matches the screen. */
  labels: PdfLabels;
};

export type PdfLabels = {
  title: string;
  generated: string;
  timeframe: string;
  recommendation: string;
  confidence: string;
  horizon: string;
  entry: string;
  target: string;
  stop: string;
  rationale: string;
  strategy: string;
  agents: string;
  disclaimer: string;
  disclaimerBody: string;
  page: string;
};

const MARGIN = 48;
const LINE = 14;

/** Keys carrying prose worth printing, in the order a reader wants them. */
const PROSE_ORDER = [
  "summary",
  "thesis",
  "rationale",
  "assessment",
  "interpretation",
  "notes",
  "agreements",
  "disagreements",
  "supporting_signals",
  "conflicting_factors",
  "risk_factors",
  "watch_items",
];

function label(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function asLines(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) {
    return value.flatMap((entry) => {
      const lines = asLines(entry);
      return lines.length ? [`• ${lines.join(" ")}`] : [];
    });
  }
  if (typeof value === "object") return [];
  const text = String(value).trim();
  return text ? [text] : [];
}

export async function buildAnalysisPdf(input: ExportInput): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ unit: "pt", format: "a4" });

  const width = doc.internal.pageSize.getWidth();
  const height = doc.internal.pageSize.getHeight();
  const usable = width - MARGIN * 2;
  let y = MARGIN;

  const breakIfNeeded = (needed = LINE) => {
    // Reserved space at the foot for the page number, so a paragraph cannot
    // run over it.
    if (y + needed > height - MARGIN - LINE) {
      doc.addPage();
      y = MARGIN;
    }
  };

  const write = (text: string, size: number, style: "normal" | "bold" = "normal") => {
    doc.setFont("helvetica", style);
    doc.setFontSize(size);
    // Split before writing rather than relying on the viewer to wrap: a PDF
    // has no reflow, so an unsplit line is simply cut off at the page edge.
    for (const line of doc.splitTextToSize(text, usable) as string[]) {
      breakIfNeeded();
      doc.text(line, MARGIN, y);
      y += size + 4;
    }
  };

  const heading = (text: string) => {
    breakIfNeeded(LINE * 3);
    y += 8;
    write(text, 12, "bold");
    doc.setDrawColor(200);
    doc.line(MARGIN, y - 6, width - MARGIN, y - 6);
    y += 4;
  };

  const field = (name: string, value: string) => {
    if (!value) return;
    write(`${name}: ${value}`, 10);
  };

  const L = input.labels;

  // --- header ---------------------------------------------------------------
  write(`${input.ticker} — ${L.title}`, 18, "bold");
  write(`${L.generated}: ${input.generatedAt}    ${L.timeframe}: ${input.timeframe}`, 9);
  y += 6;

  // --- recommendation -------------------------------------------------------
  if (input.recommendation) {
    const r = input.recommendation;
    heading(L.recommendation);
    write(String(r.label ?? "").toUpperCase().replace(/_/g, " "), 14, "bold");
    field(L.confidence, r.confidence === null || r.confidence === undefined ? "" : `${r.confidence}`);
    field(L.horizon, String(r.horizon ?? ""));
    field(L.entry, r.support_level ? String(r.support_level) : "");
    // The method travels with the price. A target with no stated basis is the
    // kind of number a reader treats as more certain than it is.
    field(
      L.target,
      [r.target_price, r.target_price_method].filter(Boolean).join(" — "),
    );
    field(
      L.stop,
      [r.suggested_stop, r.suggested_stop_method].filter(Boolean).join(" — "),
    );
    if (r.reasoning) {
      y += 4;
      write(L.rationale, 10, "bold");
      write(String(r.reasoning), 10);
    }
    for (const [key, values] of [
      ["supporting_factors", r.supporting_factors],
      ["conflicting_factors", r.conflicting_factors],
      ["risk_factors", r.risk_factors],
    ] as const) {
      const lines = asLines(values);
      if (!lines.length) continue;
      y += 2;
      write(label(key), 10, "bold");
      for (const line of lines) write(line, 10);
    }
  }

  // --- strategy -------------------------------------------------------------
  if (input.guidance) {
    heading(L.strategy);
    const g = input.guidance as unknown as Record<string, unknown>;
    for (const key of PROSE_ORDER) {
      const lines = asLines(g[key]);
      if (!lines.length) continue;
      write(label(key), 10, "bold");
      for (const line of lines) write(line, 10);
      y += 2;
    }
  }

  // --- what each agent found -------------------------------------------------
  const agentNames = Object.keys(input.agents);
  if (agentNames.length) {
    heading(L.agents);
    for (const name of agentNames) {
      const payload = input.agents[name] ?? {};
      write(label(name), 11, "bold");
      let wrote = false;
      for (const key of PROSE_ORDER) {
        const lines = asLines(payload[key]);
        if (!lines.length) continue;
        wrote = true;
        write(label(key), 9, "bold");
        for (const line of lines) write(line, 9);
      }
      if (!wrote) write("—", 9);
      y += 6;
    }
  }

  // --- the disclaimer, which is not optional --------------------------------
  //
  // Section 13 requires it on output, and a PDF is the one artefact that
  // leaves the platform entirely: it gets emailed, printed and forwarded with
  // none of the surrounding interface that carries the caveats. It goes on its
  // own page rather than as a footnote for the same reason.
  breakIfNeeded(LINE * 6);
  heading(L.disclaimer);
  write(L.disclaimerBody, 9);

  // Page numbers last, when the total is known.
  const pages = doc.getNumberOfPages();
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(130);
    doc.text(
      `${input.ticker} · ${L.page} ${page}/${pages}`,
      width - MARGIN,
      height - MARGIN / 2,
      { align: "right" },
    );
    doc.setTextColor(0);
  }

  return doc.output("blob");
}

/** Triggers the download. Kept apart so the builder stays testable. */
export function downloadPdf(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  // Revoked on the next tick rather than immediately: Safari has not started
  // reading the blob by the time click() returns.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
