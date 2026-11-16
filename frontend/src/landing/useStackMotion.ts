import { useEffect, type RefObject } from "react";

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// Where the browser cannot say (no matchMedia), the page stays still: motion is opt-in, not the default.
const query = (media: string, fallback: boolean) =>
  typeof window.matchMedia === "function" ? window.matchMedia(media).matches : fallback;

/**
 * Drives the stack from the page, without React state: it writes CSS custom properties, so a scroll
 * or a pointer move never re-renders anything.
 *
 * - `scroll`: `--p` (how far the layers are pulled apart) follows how far `region` has scrolled away.
 * - `tilt`: `--rx` and `--ry` follow the pointer over `region`, on devices that have a fine pointer.
 *
 * Under `prefers-reduced-motion: reduce` it writes one resting value and attaches nothing.
 */
export function useStackMotion(
  target: RefObject<HTMLElement | null>,
  region: RefObject<HTMLElement | null>,
  options: { scroll?: boolean; tilt?: boolean; rest?: number } = {},
) {
  const { scroll = false, tilt = false, rest = 0.62 } = options;

  useEffect(() => {
    const el = target.current;
    const zone = region.current;
    if (!el || !zone) return;

    if (query("(prefers-reduced-motion: reduce)", true)) {
      el.style.setProperty("--p", String(rest));
      return;
    }

    let frame = 0;
    let pending: (() => void) | null = null;
    const schedule = (work: () => void) => {
      pending = work;
      if (!frame) {
        frame = requestAnimationFrame(() => {
          frame = 0;
          pending?.();
        });
      }
    };

    const cleanups: Array<() => void> = [];

    if (scroll) {
      const update = () => {
        const box = zone.getBoundingClientRect();
        const progress = clamp(-box.top / Math.max(box.height * 0.42, 1), 0, 1);
        el.style.setProperty("--p", String(0.3 + progress * 0.7));
      };
      const onScroll = () => schedule(update);
      update();
      window.addEventListener("scroll", onScroll, { passive: true });
      cleanups.push(() => window.removeEventListener("scroll", onScroll));
    } else {
      el.style.setProperty("--p", String(rest));
    }

    if (tilt && query("(pointer: fine)", false)) {
      const onMove = (event: PointerEvent) => {
        const box = zone.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width - 0.5;
        const y = (event.clientY - box.top) / box.height - 0.5;
        schedule(() => {
          el.style.setProperty("--rx", String(clamp(-y * 7, -4, 4)));
          el.style.setProperty("--ry", String(clamp(x * 9, -5, 5)));
        });
      };
      const onLeave = () =>
        schedule(() => {
          el.style.setProperty("--rx", "0");
          el.style.setProperty("--ry", "0");
        });
      zone.addEventListener("pointermove", onMove);
      zone.addEventListener("pointerleave", onLeave);
      cleanups.push(() => {
        zone.removeEventListener("pointermove", onMove);
        zone.removeEventListener("pointerleave", onLeave);
      });
    }

    return () => {
      cleanups.forEach((fn) => fn());
      if (frame) cancelAnimationFrame(frame);
    };
  }, [target, region, scroll, tilt, rest]);
}
