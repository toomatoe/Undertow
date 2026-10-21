/**
 * Small zero-dependency force simulation for the Event graph (no React, no DOM).
 *
 * Forces per tick, all scaled by `alpha` (which cools towards 0, then the simulation stops):
 * - short-range repulsion + collision between nodes, found through a uniform grid (O(n) per tick),
 * - long-range repulsion between cluster centroids (O(clusters^2)), so clusters spread apart,
 * - link springs (rest length LINK_LEN), stiffer for heavier edges,
 * - attraction of each node towards its cluster centroid ("other" = cluster -1 is pulled weakly),
 * - centering (the mean position is kept at the origin).
 */

export interface SimNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  cluster: number;
}

export interface SimLink {
  /** Index into the node array. */
  s: number;
  t: number;
  w: number;
}

const LINK_LEN = 28;
const CELL = 48; // grid cell size: short-range repulsion cut-off
const REPULSE = 180;
const CLUSTER_REPULSE = 40000;
const CLUSTER_PULL = 0.09;
const OTHER_PULL = 0.006;
const VELOCITY_DECAY = 0.55;
const ALPHA_MIN = 0.002;
const ALPHA_DECAY = 1 - Math.pow(ALPHA_MIN, 1 / 300); // ~300 ticks from alpha 1 to ALPHA_MIN

/** Deterministic PRNG (mulberry32) so the same data gives the same starting layout. */
function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Starting positions: the server's x/y hint when every node has one (normalised to a disc), otherwise each cluster
 * gets a spot on a circle and its members a small jittered spiral around it.
 */
export function initialPositions(
  items: { x: number | null; y: number | null; cluster: number }[],
  clusterOrder: number[],
): { x: number; y: number }[] {
  const n = items.length;
  const spread = 22 * Math.sqrt(Math.max(n, 1));
  const hinted = n > 0 && items.every((it) => Number.isFinite(it.x) && Number.isFinite(it.y));
  if (hinted) {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const it of items) {
      minX = Math.min(minX, it.x as number);
      maxX = Math.max(maxX, it.x as number);
      minY = Math.min(minY, it.y as number);
      maxY = Math.max(maxY, it.y as number);
    }
    const sx = maxX - minX || 1;
    const sy = maxY - minY || 1;
    const rand = prng(n);
    return items.map((it) => ({
      x: (((it.x as number) - minX) / sx - 0.5) * 2 * spread + (rand() - 0.5),
      y: (((it.y as number) - minY) / sy - 0.5) * 2 * spread + (rand() - 0.5),
    }));
  }
  const slot = new Map<number, number>();
  clusterOrder.forEach((id, i) => slot.set(id, i));
  const k = Math.max(clusterOrder.length, 1);
  const counters = new Map<number, number>();
  const rand = prng(n * 7919 + k);
  return items.map((it) => {
    const i = slot.get(it.cluster);
    const angle = i === undefined ? rand() * Math.PI * 2 : (i / k) * Math.PI * 2;
    const ring = i === undefined ? spread * 1.1 : spread * 0.6;
    const cx = Math.cos(angle) * ring;
    const cy = Math.sin(angle) * ring;
    const m = counters.get(it.cluster) ?? 0;
    counters.set(it.cluster, m + 1);
    const a = m * 2.399963; // golden angle spiral
    const d = 6 * Math.sqrt(m + 1);
    return { x: cx + Math.cos(a) * d + (rand() - 0.5) * 4, y: cy + Math.sin(a) * d + (rand() - 0.5) * 4 };
  });
}

export class ForceSim {
  readonly nodes: SimNode[];
  readonly links: SimLink[];
  alpha = 1;
  private grid = new Map<number, number[]>();

  constructor(nodes: SimNode[], links: SimLink[]) {
    this.nodes = nodes;
    const max = links.reduce((m, l) => Math.max(m, l.w), 0) || 1;
    // Normalise weights to (0, 1] so link strength does not depend on the server's weight scale.
    this.links = links.map((l) => ({ ...l, w: Math.max(0.05, l.w / max) }));
  }

  get settled(): boolean {
    return this.alpha < ALPHA_MIN;
  }

  /** Re-heat (e.g. after new data); 1 = full restart. */
  reheat(alpha = 0.6): void {
    this.alpha = Math.max(this.alpha, alpha);
  }

  /** Run `count` ticks synchronously (reduced motion: settle without animating). */
  run(count: number): void {
    for (let i = 0; i < count && !this.settled; i++) this.tick();
  }

  tick(): void {
    const nodes = this.nodes;
    const n = nodes.length;
    if (n === 0) {
      this.alpha = 0;
      return;
    }
    const alpha = this.alpha;

    // 1. Short-range repulsion + collision through a grid.
    const grid = this.grid;
    grid.clear();
    const key = (cx: number, cy: number) => ((cx + 32768) << 16) | (cy + 32768);
    for (let i = 0; i < n; i++) {
      const p = nodes[i];
      const k = key(Math.floor(p.x / CELL), Math.floor(p.y / CELL));
      const cell = grid.get(k);
      if (cell) cell.push(i);
      else grid.set(k, [i]);
    }
    for (let i = 0; i < n; i++) {
      const p = nodes[i];
      const cx = Math.floor(p.x / CELL);
      const cy = Math.floor(p.y / CELL);
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const cell = grid.get(key(cx + dx, cy + dy));
          if (!cell) continue;
          for (const j of cell) {
            if (j <= i) continue;
            const q = nodes[j];
            let ddx = q.x - p.x;
            let ddy = q.y - p.y;
            let d2 = ddx * ddx + ddy * ddy;
            if (d2 === 0) {
              ddx = ((i * 31 + j) % 7) - 3 || 1;
              ddy = ((i * 17 + j) % 5) - 2 || 1;
              d2 = ddx * ddx + ddy * ddy;
            }
            if (d2 > CELL * CELL) continue;
            const d = Math.sqrt(d2);
            let f = (REPULSE * alpha) / d2;
            const minD = p.r + q.r + 1.5;
            if (d < minD) f += ((minD - d) / d) * 0.5; // collision: push overlapping nodes apart
            const fx = ddx * f;
            const fy = ddy * f;
            p.vx -= fx;
            p.vy -= fy;
            q.vx += fx;
            q.vy += fy;
          }
        }
      }
    }

    // 2. Cluster centroids: attraction of members, repulsion between centroids.
    const cent = new Map<number, { x: number; y: number; n: number }>();
    for (const p of nodes) {
      const c = cent.get(p.cluster);
      if (c) {
        c.x += p.x;
        c.y += p.y;
        c.n++;
      } else cent.set(p.cluster, { x: p.x, y: p.y, n: 1 });
    }
    const cs = [...cent.entries()].map(([id, c]) => ({ id, x: c.x / c.n, y: c.y / c.n, n: c.n, fx: 0, fy: 0 }));
    for (let a = 0; a < cs.length; a++) {
      for (let b = a + 1; b < cs.length; b++) {
        const A = cs[a];
        const B = cs[b];
        const dx = B.x - A.x || 0.5;
        const dy = B.y - A.y || 0.5;
        const d2 = Math.max(dx * dx + dy * dy, 900);
        const f = (CLUSTER_REPULSE * alpha * Math.sqrt(A.n * B.n)) / d2 / Math.sqrt(d2);
        A.fx -= (dx * f) / A.n;
        A.fy -= (dy * f) / A.n;
        B.fx += (dx * f) / B.n;
        B.fy += (dy * f) / B.n;
      }
    }
    const byId = new Map(cs.map((c) => [c.id, c]));
    for (const p of nodes) {
      const c = byId.get(p.cluster);
      if (!c) continue;
      const pull = (p.cluster === -1 ? OTHER_PULL : CLUSTER_PULL) * alpha;
      p.vx += (c.x - p.x) * pull + c.fx;
      p.vy += (c.y - p.y) * pull + c.fy;
    }

    // 3. Link springs.
    for (const l of this.links) {
      const a = nodes[l.s];
      const b = nodes[l.t];
      const dx = b.x + b.vx - a.x - a.vx || 0.01;
      const dy = b.y + b.vy - a.y - a.vy || 0.01;
      const d = Math.sqrt(dx * dx + dy * dy);
      const f = ((d - LINK_LEN) / d) * alpha * 0.08 * l.w;
      const fx = dx * f;
      const fy = dy * f;
      b.vx -= fx;
      b.vy -= fy;
      a.vx += fx;
      a.vy += fy;
    }

    // 4. Integrate, with velocity decay; 5. centering.
    let mx = 0;
    let my = 0;
    for (const p of nodes) {
      p.vx *= VELOCITY_DECAY;
      p.vy *= VELOCITY_DECAY;
      p.x += p.vx;
      p.y += p.vy;
      mx += p.x;
      my += p.y;
    }
    mx /= n;
    my /= n;
    for (const p of nodes) {
      p.x -= mx;
      p.y -= my;
    }

    this.alpha += (0 - this.alpha) * ALPHA_DECAY;
  }
}
