"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import type { GraphEdge, GraphEdgeType, GraphNode } from "@/lib/api";

import { ForceSim, initialPositions, type SimNode } from "./force";
import styles from "./graph.module.css";
import { EDGE_DASH, EDGE_TYPES, formatWhen, PALETTE_SIZE } from "./util";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Cluster id -> palette slot (see util.buildColorIndex); missing = neutral "other". */
  colorIndex: Map<number, number>;
  /** Cluster ids in legend order (seeds the starting layout). */
  clusterOrder: number[];
  /** Epoch ms: nodes published after this are hidden (time scrubber). */
  visibleUntil: number;
  edgeTypes: Record<GraphEdgeType, boolean>;
  highlightCluster: number | null;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  clusterName: (id: number) => string;
}

interface View {
  k: number;
  tx: number;
  ty: number;
}

interface Colors {
  palette: string[];
  other: string;
  edge: string;
  text: string;
  bg: string;
}

interface Hover {
  id: number;
  sx: number;
  sy: number;
  /** Stage size when the tooltip was opened (keeps it inside the stage). */
  w: number;
  h: number;
}

/** Node radius in screen px at zoom 1, by severity (null = small). */
function radiusFor(sev: number | null): number {
  if (sev === null || sev === undefined || !Number.isFinite(sev) || sev <= 0) return 3.5;
  return Math.min(3.5 + sev * 1.4, 10);
}

function readColors(el: Element): Colors {
  const cs = getComputedStyle(el);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    palette: Array.from({ length: PALETTE_SIZE }, (_, i) => v(`--g-c${i}`, "#4f9cff")),
    other: v("--g-other", "#888888"),
    edge: v("--g-edge", "#999999"),
    text: v("--text", "#e6e9ef"),
    bg: v("--g-canvas", "#0e1218"),
  };
}

/**
 * Canvas force-directed graph: filings as circles, news as squares, coloured by cluster; edges faint and styled by type.
 * Pan (drag), zoom (wheel / pinch), reset; hover tooltip (mouse) and tap/click to select.
 * The simulation cools and stops, pauses while the tab is hidden, and with prefers-reduced-motion it is computed
 * synchronously (300 ticks) and only the settled layout is drawn.
 */
export default function GraphCanvas(props: Props) {
  const { nodes, edges, clusterOrder } = props;
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const live = useRef(props);
  const ctl = useRef<{ draw: () => void; reset: () => void } | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const [running, setRunning] = useState(false);
  const hoverRef = useRef<Hover | null>(null);

  // Latest props for the imperative renderer, then redraw (cheap: one rAF-coalesced frame).
  useEffect(() => {
    live.current = props;
    hoverRef.current = hover;
    ctl.current?.draw();
  });

  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    if (!stage || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const idx = new Map<number, number>();
    nodes.forEach((n, i) => idx.set(n.id, i));
    const times = nodes.map((n) => {
      const t = Date.parse(n.published_at);
      return Number.isFinite(t) ? t : 0;
    });
    const starts = initialPositions(nodes, clusterOrder);
    const simNodes: SimNode[] = nodes.map((n, i) => ({
      x: starts[i].x,
      y: starts[i].y,
      vx: 0,
      vy: 0,
      r: radiusFor(n.severity),
      cluster: n.cluster,
    }));
    const links = edges
      .map((e) => ({ s: idx.get(e.source), t: idx.get(e.target), w: e.weight, type: e.type }))
      .filter((l): l is { s: number; t: number; w: number; type: GraphEdgeType } => l.s !== undefined && l.t !== undefined && l.s !== l.t);
    const sim = new ForceSim(simNodes, links.map(({ s, t, w }) => ({ s, t, w: Number.isFinite(w) ? w : 1 })));
    const neighbours = new Map<number, Set<number>>();
    for (const l of links) {
      if (!neighbours.has(l.s)) neighbours.set(l.s, new Set());
      if (!neighbours.has(l.t)) neighbours.set(l.t, new Set());
      neighbours.get(l.s)!.add(l.t);
      neighbours.get(l.t)!.add(l.s);
    }

    let colors = readColors(stage);
    let size = { w: 0, h: 0, dpr: 1 };
    const view: View = { k: 1, tx: 0, ty: 0 };
    let userMoved = false;
    let raf = 0;
    let drawPending = 0;
    let stopped = false;

    const toScreen = (p: SimNode) => ({ x: p.x * view.k + size.w / 2 + view.tx, y: p.y * view.k + size.h / 2 + view.ty });
    const nodeScale = () => Math.min(Math.max(Math.sqrt(view.k), 0.6), 2.2);

    const fit = () => {
      if (simNodes.length === 0 || size.w === 0) return;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const p of simNodes) {
        minX = Math.min(minX, p.x);
        maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y);
        maxY = Math.max(maxY, p.y);
      }
      const pad = 28;
      const bw = Math.max(maxX - minX, 1);
      const bh = Math.max(maxY - minY, 1);
      const k = Math.min((size.w - pad * 2) / bw, (size.h - pad * 2) / bh, 3);
      view.k = Math.max(k, 0.05);
      view.tx = -((minX + maxX) / 2) * view.k;
      view.ty = -((minY + maxY) / 2) * view.k;
    };

    const draw = () => {
      const p = live.current;
      const { w, h, dpr } = size;
      if (w === 0 || h === 0) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const visible = (i: number) => times[i] <= p.visibleUntil;
      // Focus: selected node + its neighbours, else the highlighted cluster, else everything.
      let focus: Set<number> | null = null;
      const sel = p.selectedId !== null ? idx.get(p.selectedId) : undefined;
      if (sel !== undefined) {
        focus = new Set([sel, ...(neighbours.get(sel) ?? [])]);
      } else if (p.highlightCluster !== null) {
        focus = new Set();
        nodes.forEach((n, i) => {
          if (n.cluster === p.highlightCluster) focus!.add(i);
        });
      }
      const scr = simNodes.map(toScreen);

      // Edges: faint, styled by type, no arrows. Three alpha levels per type: focus, normal, dimmed.
      ctx.strokeStyle = colors.edge;
      ctx.lineWidth = 1;
      for (const type of EDGE_TYPES) {
        if (!p.edgeTypes[type]) continue;
        ctx.setLineDash(EDGE_DASH[type]);
        const groups: [number, number][][] = [[], [], []];
        for (const l of links) {
          if (l.type !== type || !visible(l.s) || !visible(l.t)) continue;
          const g = focus === null ? 1 : focus.has(l.s) && focus.has(l.t) ? 0 : 2;
          groups[g].push([l.s, l.t]);
        }
        const alphas = [0.6, 0.22, 0.05];
        groups.forEach((list, g) => {
          if (list.length === 0) return;
          ctx.globalAlpha = alphas[g];
          ctx.beginPath();
          for (const [a, b] of list) {
            ctx.moveTo(scr[a].x, scr[a].y);
            ctx.lineTo(scr[b].x, scr[b].y);
          }
          ctx.stroke();
        });
      }
      ctx.setLineDash([]);

      // Nodes: dimmed first, then focused on top.
      const s = nodeScale();
      const drawNode = (i: number) => {
        const n = nodes[i];
        const slot = p.colorIndex.get(n.cluster);
        ctx.fillStyle = slot === undefined ? colors.other : colors.palette[slot];
        const r = simNodes[i].r * s;
        const { x, y } = scr[i];
        if (x < -20 || y < -20 || x > w + 20 || y > h + 20) return;
        if (n.kind === "news") {
          ctx.fillRect(x - r * 0.9, y - r * 0.9, r * 1.8, r * 1.8);
        } else {
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();
        }
      };
      const order: number[] = [];
      const top: number[] = [];
      for (let i = 0; i < nodes.length; i++) {
        if (!visible(i)) continue;
        if (focus && focus.has(i)) top.push(i);
        else order.push(i);
      }
      ctx.globalAlpha = focus ? 0.16 : 0.92;
      order.forEach(drawNode);
      ctx.globalAlpha = 1;
      top.forEach(drawNode);

      // Rings: selected (thick) and hovered (thin).
      const ring = (i: number | undefined, width: number) => {
        if (i === undefined || !visible(i)) return;
        const r = simNodes[i].r * s + 3;
        ctx.globalAlpha = 1;
        ctx.strokeStyle = colors.text;
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.arc(scr[i].x, scr[i].y, r, 0, Math.PI * 2);
        ctx.stroke();
      };
      ring(sel, 2);
      const hv = hoverRef.current;
      if (hv && hv.id !== p.selectedId) ring(idx.get(hv.id), 1);
      ctx.globalAlpha = 1;
    };

    const requestDraw = () => {
      if (drawPending || stopped) return;
      drawPending = requestAnimationFrame(() => {
        drawPending = 0;
        draw();
      });
    };

    const frame = () => {
      raf = 0;
      if (stopped) return;
      if (document.hidden) return; // resumed by visibilitychange
      sim.tick();
      sim.tick();
      if (!userMoved) fit();
      draw();
      if (sim.settled) {
        setRunning(false);
        return;
      }
      raf = requestAnimationFrame(frame);
    };

    const start = () => {
      if (reduced) {
        sim.run(300);
        sim.alpha = 0;
        if (!userMoved) fit();
        requestDraw();
        return;
      }
      if (!raf && !sim.settled) {
        setRunning(true);
        raf = requestAnimationFrame(frame);
      }
    };

    const onVisibility = () => {
      if (!document.hidden && !sim.settled && !raf && !reduced) raf = requestAnimationFrame(frame);
    };

    const resize = () => {
      const rect = stage.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 3);
      size = { w: rect.width, h: rect.height, dpr };
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      if (!userMoved) fit();
      draw();
    };

    const hitTest = (sx: number, sy: number): number | null => {
      const p = live.current;
      const s = nodeScale();
      let best: number | null = null;
      let bestD = Infinity;
      for (let i = 0; i < simNodes.length; i++) {
        if (times[i] > p.visibleUntil) continue;
        const q = toScreen(simNodes[i]);
        const d = Math.hypot(q.x - sx, q.y - sy);
        const reach = Math.max(simNodes[i].r * s + 4, 10);
        if (d <= reach && d < bestD) {
          best = i;
          bestD = d;
        }
      }
      return best;
    };

    // --- pointer: drag to pan, two fingers to pinch, tap/click to select, mouse hover for the tooltip ---
    const pointers = new Map<number, { x: number; y: number }>();
    let downAt: { x: number; y: number } | null = null;
    let moved = false;
    let pinch: { d: number; k: number } | null = null;
    const local = (e: PointerEvent | WheelEvent) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const zoomAt = (mx: number, my: number, k2: number) => {
      const k = Math.min(Math.max(k2, 0.03), 12);
      const ox = mx - size.w / 2;
      const oy = my - size.h / 2;
      view.tx = ox - (ox - view.tx) * (k / view.k);
      view.ty = oy - (oy - view.ty) * (k / view.k);
      view.k = k;
      userMoved = true;
    };
    const showHover = (i: number | null, x: number, y: number) => {
      const next = i === null ? null : { id: nodes[i].id, sx: x, sy: y, w: size.w, h: size.h };
      const cur = hoverRef.current;
      if (cur?.id === next?.id && (!cur || (Math.abs(cur.sx - x) < 2 && Math.abs(cur.sy - y) < 2))) return;
      hoverRef.current = next;
      setHover(next);
    };

    const onDown = (e: PointerEvent) => {
      canvas.setPointerCapture(e.pointerId);
      const pt = local(e);
      pointers.set(e.pointerId, pt);
      if (pointers.size === 1) {
        downAt = pt;
        moved = false;
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, k: view.k };
        moved = true;
      }
    };
    const onMove = (e: PointerEvent) => {
      const pt = local(e);
      const prev = pointers.get(e.pointerId);
      if (!prev) {
        if (e.pointerType === "mouse") {
          const i = hitTest(pt.x, pt.y);
          showHover(i, pt.x, pt.y);
          requestDraw();
        }
        return;
      }
      pointers.set(e.pointerId, pt);
      if (pointers.size === 2 && pinch) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, pinch.k * (d / pinch.d));
        requestDraw();
        return;
      }
      if (downAt && !moved && Math.hypot(pt.x - downAt.x, pt.y - downAt.y) > 4) moved = true;
      if (moved) {
        view.tx += pt.x - prev.x;
        view.ty += pt.y - prev.y;
        userMoved = true;
        if (hoverRef.current) showHover(null, 0, 0);
        requestDraw();
      }
    };
    const onUp = (e: PointerEvent) => {
      const pt = local(e);
      const wasSingle = pointers.size === 1;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (wasSingle && !moved) {
        const i = hitTest(pt.x, pt.y);
        live.current.onSelect(i === null ? null : nodes[i].id);
        if (e.pointerType !== "mouse") showHover(i, pt.x, pt.y); // touch: tap shows the tooltip too
      }
      if (pointers.size === 0) downAt = null;
    };
    const onLeave = (e: PointerEvent) => {
      if (e.pointerType === "mouse" && pointers.size === 0) {
        showHover(null, 0, 0);
        requestDraw();
      }
    };
    const onWheel = (e: WheelEvent) => {
      // Plain wheel scrolls the page (the canvas is tall, so capturing it traps the reader); Ctrl/Cmd+wheel and
      // trackpad pinch (which browsers report as ctrlKey wheel events) zoom.
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const pt = local(e);
      zoomAt(pt.x, pt.y, view.k * Math.exp(-e.deltaY * 0.0015));
      requestDraw();
    };

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    document.addEventListener("visibilitychange", onVisibility);
    const ro = new ResizeObserver(resize);
    ro.observe(stage);
    const scheme = window.matchMedia("(prefers-color-scheme: light)");
    const onScheme = () => {
      colors = readColors(stage);
      requestDraw();
    };
    scheme.addEventListener("change", onScheme);

    ctl.current = {
      draw: requestDraw,
      reset: () => {
        userMoved = false;
        fit();
        requestDraw();
      },
    };
    resize();
    start();

    return () => {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      if (drawPending) cancelAnimationFrame(drawPending);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("wheel", onWheel);
      document.removeEventListener("visibilitychange", onVisibility);
      scheme.removeEventListener("change", onScheme);
      ro.disconnect();
      ctl.current = null;
      hoverRef.current = null;
      setHover(null);
      setRunning(false);
    };
  }, [nodes, edges, clusterOrder]);

  const hoverNode = hover ? nodes.find((n) => n.id === hover.id) : undefined;
  const stageW = hover?.w ?? 0;
  const stageH = hover?.h ?? 0;
  let tipStyle: CSSProperties = {};
  if (hover && hoverNode) {
    const left = hover.sx <= stageW / 2;
    const above = hover.sy > stageH / 2;
    tipStyle = {
      ...(left ? { left: hover.sx + 12 } : { right: stageW - hover.sx + 12 }),
      ...(above ? { bottom: stageH - hover.sy + 12 } : { top: hover.sy + 12 }),
      maxWidth: Math.max(140, Math.min(320, (left ? stageW - hover.sx : hover.sx) - 24)),
    };
  }

  return (
    <div ref={stageRef} className={styles.stage}>
      <canvas
        ref={canvasRef}
        className={styles.canvas}
        role="img"
        aria-label={`Event graph: ${nodes.length} filings and news items, ${edges.length} links. Use the cluster list below the graph for a text version.`}
      />
      <div className={styles.overlay}>
        <button type="button" onClick={() => ctl.current?.reset()} title="Fit the whole graph in view">
          Reset view
        </button>
      </div>
      <span className={styles.status} aria-live="polite">
        {running ? "Settling layout…" : "Drag to pan · Ctrl+scroll or pinch to zoom · click a node for details"}
      </span>
      {hover && hoverNode && (
        <div className={styles.tooltip} style={tipStyle} role="tooltip">
          <strong>{hoverNode.title}</strong>
          <div className="muted">
            {[hoverNode.ticker ? `$${hoverNode.ticker}` : null, hoverNode.kind === "filing" ? hoverNode.form ?? "Filing" : hoverNode.source_name, formatWhen(hoverNode.published_at)]
              .filter(Boolean)
              .join(" · ")}
          </div>
          {hoverNode.signal_labels.length > 0 && <div>{hoverNode.signal_labels.join(", ")}</div>}
          <div className="muted">{props.clusterName(hoverNode.cluster)}</div>
        </div>
      )}
    </div>
  );
}
