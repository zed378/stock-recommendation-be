import { useEffect, useRef } from "react";

/**
 * The moving backdrop on the sign-in screen.
 *
 * Drawn, not downloaded. Consistent with the rest of this build: no image
 * asset, no request, nothing that depends on a host staying up for the login
 * page to look finished.
 *
 * **Deliberately not a chart.** A price line on a financial product's front
 * door gets read as data - someone will squint at it and wonder what it is
 * showing. This is a drifting field of points with no axis, no scale, and no
 * direction that means anything. It is wallpaper, and it should be legible as
 * wallpaper.
 *
 * Motion is skipped entirely under `prefers-reduced-motion`: a single frame is
 * painted and the loop never starts. Animation someone cannot turn off is an
 * accessibility problem, and the operating system already carries that answer.
 */

type Point = { x: number; y: number; dx: number; dy: number };

const POINT_COUNT = 44;
//: Beyond this, points stop being drawn as related. Squared, so the inner loop
//: never needs a square root.
const LINK_DISTANCE_SQ = 150 ** 2;
const SPEED = 0.12;

export function Backdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let width = 0;
    let height = 0;
    let points: Point[] = [];

    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      // Backing store scaled to the device, drawing done in CSS pixels. Without
      // this the whole field is soft on any retina display.
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    const seed = () => {
      points = Array.from({ length: POINT_COUNT }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        dx: (Math.random() - 0.5) * SPEED,
        dy: (Math.random() - 0.5) * SPEED,
      }));
    };

    const draw = () => {
      context.clearRect(0, 0, width, height);

      for (const point of points) {
        point.x += point.dx;
        point.y += point.dy;
        // Wrapped rather than bounced: a bounce puts every point on a wall
        // eventually and the field collects at the edges.
        if (point.x < 0) point.x = width;
        if (point.x > width) point.x = 0;
        if (point.y < 0) point.y = height;
        if (point.y > height) point.y = 0;
      }

      for (let i = 0; i < points.length; i += 1) {
        for (let j = i + 1; j < points.length; j += 1) {
          const dx = points[i].x - points[j].x;
          const dy = points[i].y - points[j].y;
          const distanceSq = dx * dx + dy * dy;
          if (distanceSq > LINK_DISTANCE_SQ) continue;

          // Fades with distance, so links appear and dissolve rather than
          // switching on at the threshold.
          context.globalAlpha = 0.16 * (1 - distanceSq / LINK_DISTANCE_SQ);
          context.strokeStyle = "#26a69a";
          context.lineWidth = 1;
          context.beginPath();
          context.moveTo(points[i].x, points[i].y);
          context.lineTo(points[j].x, points[j].y);
          context.stroke();
        }
      }

      context.globalAlpha = 0.5;
      context.fillStyle = "#8b98a9";
      for (const point of points) {
        context.beginPath();
        context.arc(point.x, point.y, 1.1, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;
    };

    resize();
    seed();
    draw();

    let frame = 0;
    if (!reduced) {
      const loop = () => {
        draw();
        frame = requestAnimationFrame(loop);
      };
      frame = requestAnimationFrame(loop);
    }

    const onResize = () => {
      resize();
      seed();
      if (reduced) draw();
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      // Decorative. Announcing it would put "canvas" in a screen reader's path
      // to the sign-in form for no benefit.
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}
