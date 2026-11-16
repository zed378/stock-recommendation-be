import type { Ref } from "react";

/**
 * The page's one 3D object: the five layers of an AIDSS analysis, stacked into a decision card.
 *
 * It stands for how the product is built (market data, indicators, a forecast, a debate between agents, a
 * calibrated stance), not for any market. So every drawing is schematic: no axis, no scale, no number, no
 * ticker. A chart with figures on a financial product's front door gets read as data, and there is no
 * data here.
 */

type Walk = { o: number; h: number; l: number; c: number };

// A fixed pseudo-random walk, so the drawing is the same on every render and every machine.
function walk(count: number, seed: number): Walk[] {
  let state = seed;
  const next = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const out: Walk[] = [];
  let value = 100;
  for (let i = 0; i < count; i += 1) {
    const o = value;
    const c = o + (next() - 0.46) * 7;
    out.push({ o, c, h: Math.max(o, c) + next() * 3, l: Math.min(o, c) - next() * 3 });
    value = c;
  }
  return out;
}

const SERIES = walk(26, 7);

function scale(values: number[], top: number, bottom: number) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return (v: number) => bottom - ((v - lo) / (hi - lo || 1)) * (bottom - top);
}

function DataPlane() {
  const y = scale(SERIES.flatMap((k) => [k.h, k.l]), 22, 178);
  const step = 272 / SERIES.length;
  return (
    <svg viewBox="0 0 300 200" fill="none" aria-hidden="true">
      {SERIES.map((k, i) => {
        const x = 14 + i * step + step / 2;
        const up = k.c >= k.o;
        const color = up ? "var(--lp-accent)" : "var(--lp-down)";
        const top = y(Math.max(k.o, k.c));
        const bottom = y(Math.min(k.o, k.c));
        return (
          <g key={i} stroke={color} fill={color}>
            <line x1={x} x2={x} y1={y(k.h)} y2={y(k.l)} strokeWidth="1" />
            <rect x={x - 3} y={top} width="6" height={Math.max(bottom - top, 1.5)} stroke="none" />
          </g>
        );
      })}
    </svg>
  );
}

function IndicatorPlane() {
  const closes = SERIES.map((k) => k.c);
  const y = scale(closes, 26, 128);
  const step = 272 / (closes.length - 1);
  const px = (i: number) => 14 + i * step;
  const sma = closes.map((_, i) => {
    const from = Math.max(0, i - 5);
    const slice = closes.slice(from, i + 1);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
  const line = (values: number[]) => values.map((v, i) => `${px(i)},${y(v)}`).join(" ");
  const band = [
    ...sma.map((v, i) => `${px(i)},${y(v + 4)}`),
    ...sma.map((_, i) => `${px(sma.length - 1 - i)},${y(sma[sma.length - 1 - i] - 4)}`),
  ].join(" ");
  const wave = Array.from({ length: 27 }, (_, i) => {
    const level = 175 + Math.sin(i / 2.2) * 7 + Math.sin(i / 5.1) * 5;
    return `${14 + i * 10.4},${level}`;
  }).join(" ");
  return (
    <svg viewBox="0 0 300 200" fill="none" aria-hidden="true">
      <polygon points={band} fill="var(--lp-accent)" opacity="0.1" />
      <polyline points={line(closes)} stroke="currentColor" strokeWidth="1.4" />
      <polyline points={line(sma)} stroke="var(--lp-accent)" strokeWidth="1.4" strokeDasharray="4 3" />
      <line x1="14" x2="286" y1="160" y2="160" stroke="currentColor" opacity="0.25" strokeDasharray="1 3" />
      <line x1="14" x2="286" y1="190" y2="190" stroke="currentColor" opacity="0.25" strokeDasharray="1 3" />
      <polyline points={wave} stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function ForecastPlane() {
  const history = SERIES.slice(0, 15).map((k) => k.c);
  const y = scale(history, 60, 130);
  const step = 150 / (history.length - 1);
  const px = (i: number) => 16 + i * step;
  const pts = history.map((v, i) => `${px(i)},${y(v)}`).join(" ");
  const lastX = px(history.length - 1);
  const lastY = y(history[history.length - 1]);
  return (
    <svg viewBox="0 0 300 200" fill="none" aria-hidden="true">
      <polyline points={pts} stroke="currentColor" strokeWidth="1.4" />
      <line x1={lastX} x2={lastX} y1="22" y2="182" stroke="currentColor" opacity="0.3" strokeDasharray="2 3" />
      <polygon
        points={`${lastX},${lastY} 284,${lastY - 62} 284,${lastY + 44}`}
        fill="var(--lp-accent)"
        opacity="0.16"
      />
      <polyline
        points={`${lastX},${lastY} 284,${lastY - 9}`}
        stroke="var(--lp-accent)"
        strokeWidth="1.6"
        strokeDasharray="5 3"
      />
      <circle cx={lastX} cy={lastY} r="3" fill="var(--lp-accent)" />
    </svg>
  );
}

function DebatePlane() {
  return (
    <svg viewBox="0 0 300 200" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="1" opacity="0.55">
        <line x1="150" y1="44" x2="72" y2="108" />
        <line x1="150" y1="44" x2="228" y2="108" />
        <line x1="72" y1="108" x2="72" y2="108" />
        <line x1="72" y1="108" x2="104" y2="168" />
        <line x1="228" y1="108" x2="196" y2="168" />
        <line x1="150" y1="44" x2="150" y2="168" strokeDasharray="2 3" />
        <line x1="104" y1="168" x2="196" y2="168" />
        <line x1="72" y1="108" x2="228" y2="108" strokeDasharray="2 3" />
      </g>
      <rect x="138" y="32" width="24" height="24" stroke="var(--lp-accent)" strokeWidth="1.6" />
      <circle cx="72" cy="108" r="14" stroke="var(--lp-accent)" strokeWidth="1.6" />
      <circle cx="228" cy="108" r="14" stroke="var(--lp-down)" strokeWidth="1.6" />
      <circle cx="104" cy="168" r="8" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="150" cy="168" r="8" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="196" cy="168" r="8" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function StancePlane() {
  const chips = [0, 1, 2, 3, 4, 5];
  return (
    <svg viewBox="0 0 300 200" fill="none" aria-hidden="true">
      {chips.map((c) => (
        <rect
          key={c}
          x={22 + (c % 3) * 88}
          y={26 + Math.floor(c / 3) * 32}
          width="76"
          height="22"
          rx="2"
          stroke="currentColor"
          strokeWidth="1.1"
          opacity="0.7"
        />
      ))}
      <rect x="22" y="102" width="256" height="9" rx="2" stroke="var(--lp-accent)" strokeWidth="1.2" />
      <rect x="22" y="122" width="256" height="9" rx="2" stroke="currentColor" strokeWidth="1.1" opacity="0.7" />
      <g stroke="currentColor" strokeWidth="1.1" strokeDasharray="4 3" opacity="0.8">
        <line x1="22" x2="278" y1="152" y2="152" />
        <line x1="22" x2="278" y1="170" y2="170" />
        <line x1="22" x2="278" y1="188" y2="188" />
      </g>
    </svg>
  );
}

const PLANES = [DataPlane, IndicatorPlane, ForecastPlane, DebatePlane, StancePlane] as const;

export function DecisionStack({
  active,
  ref,
}: {
  /** Index (0 to 4) of the layer to bring forward and highlight; omit to show the stack at rest. */
  active?: number;
  ref?: Ref<HTMLDivElement>;
}) {
  return (
    <div ref={ref} className="lp-stack" data-active={active} aria-hidden="true">
      <div className="lp-stack-scene">
        <div className="lp-stack-ground" />
        {PLANES.map((Plane, i) => (
          <div key={i} className="lp-plane" data-i={i} style={{ "--i": i } as React.CSSProperties}>
            <Plane />
          </div>
        ))}
      </div>
    </div>
  );
}
