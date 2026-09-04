/**
 * isolife.js — Isometric triangular Game of Life background animation
 *
 * Renders a triangular grid with B3/S23 cellular automaton rules,
 * stability-aware spontaneous creation, and smooth fade transitions.
 *
 * Usage:
 *   <canvas id="bg" aria-hidden="true"></canvas>
 *   <script src="/isolife.js"></script>
 *
 * Expects a <canvas id="bg"> element. Does nothing if canvas is missing
 * or user prefers reduced motion.
 */
(() => {
  const canvas = document.getElementById("bg");
  if (!canvas) return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const S = 28;
  const TH = S * 0.866;
  const TICK = 280;
  const INIT_DENSITY = 0.12;
  const SPONTANEOUS_EVERY = 5;

  let W, H, cols, rows, grid, prevGrid, grid2ago, gen, gridCanvas;
  let stableCount = 0;

  /* --- colour palette keyed by cell age --- */
  const PAL = [
    [0.88, 0.74, 0.80, 0.50],
    [0.82, 0.76, 0.88, 0.50],
    [0.74, 0.80, 0.92, 0.48],
    [0.70, 0.84, 0.90, 0.44],
    [0.76, 0.88, 0.84, 0.40],
    [0.82, 0.84, 0.82, 0.30],
  ];

  function ageColor(age) {
    const i = Math.min(age - 1, PAL.length - 1);
    const p = PAL[i];
    return `rgba(${p[0] * 255 | 0},${p[1] * 255 | 0},${p[2] * 255 | 0},${p[3]})`;
  }

  /* --- grid setup --- */
  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    cols = Math.ceil(W / (S / 2)) + 4;
    rows = Math.ceil(H / TH) + 2;
    seed();
    cacheGridLines(dpr);
  }

  function makeGrid() {
    const g = [];
    for (let r = 0; r < rows; r++) g[r] = new Int8Array(cols);
    return g;
  }

  function seed() {
    grid = makeGrid();
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++)
        grid[r][c] = Math.random() < INIT_DENSITY ? 1 : 0;
    prevGrid = grid;
    grid2ago = makeGrid();
    gen = 0;
    stableCount = 0;
  }

  /* --- pre-render faint grid lines --- */
  function cacheGridLines(dpr) {
    gridCanvas = document.createElement("canvas");
    gridCanvas.width = W * dpr;
    gridCanvas.height = H * dpr;
    const g = gridCanvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.strokeStyle = "rgba(0,0,0,0.045)";
    g.lineWidth = 0.5;
    g.beginPath();
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++)
        triPath(g, r, c);
    g.stroke();
  }

  /* --- triangle path helper --- */
  function triPath(c, r, col) {
    const up = (r + col) % 2 === 0;
    const x = col * (S / 2);
    const y = r * TH;
    if (up) {
      c.moveTo(x, y + TH);
      c.lineTo(x + S / 2, y);
      c.lineTo(x + S, y + TH);
    } else {
      c.moveTo(x, y);
      c.lineTo(x + S, y);
      c.lineTo(x + S / 2, y + TH);
    }
    c.closePath();
  }

  /* --- wrapping --- */
  function wr(r) { return ((r % rows) + rows) % rows; }
  function wc(c) { return ((c % cols) + cols) % cols; }
  function alive(r, c) { return grid[wr(r)][wc(c)] > 0 ? 1 : 0; }

  /* --- count 8 neighbours (3 edge + 5 vertex) --- */
  function count(r, c) {
    const up = (r + c) % 2 === 0;
    if (up) {
      return alive(r, c - 1) + alive(r, c + 1) + alive(r + 1, c)
           + alive(r - 1, c - 1) + alive(r - 1, c) + alive(r - 1, c + 1)
           + alive(r + 1, c - 1) + alive(r + 1, c + 1);
    }
    return alive(r, c - 1) + alive(r, c + 1) + alive(r - 1, c)
         + alive(r + 1, c - 1) + alive(r + 1, c) + alive(r + 1, c + 1)
         + alive(r - 1, c - 1) + alive(r - 1, c + 1);
  }

  /* --- step: B3/S23 + stability-aware spontaneous creation --- */
  function step() {
    prevGrid = grid;
    const next = makeGrid();
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const n = count(r, c);
        const a = grid[r][c];
        if (a > 0) {
          next[r][c] = (n === 2 || n === 3) ? Math.min(a + 1, 120) : 0;
        } else {
          next[r][c] = n === 3 ? 1 : 0;
        }
      }
    }

    /* detect stability: XOR current result with grid from 2 generations ago
       to catch both static and period-2 oscillators */
    let changed = 0;
    const total = rows * cols;
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++)
        if ((next[r][c] > 0) !== (grid2ago[r][c] > 0)) changed++;

    const changeRate = changed / total;
    if (changeRate < 0.005) stableCount++;
    else stableCount = Math.max(0, stableCount - 1);

    /* spontaneous creation — density scales with metastability */
    if (gen % SPONTANEOUS_EVERY === 0) {
      const BR = 8, BC = 16;
      const pressure = Math.min(stableCount / 5, 1);
      const emptyThreshold = 0.02 + pressure * 0.15;
      const seedCount = 5 + Math.floor(pressure * 15);

      for (let br = 0; br < rows; br += BR) {
        for (let bc = 0; bc < cols; bc += BC) {
          let pop = 0, tot = 0;
          const re = Math.min(br + BR, rows), ce = Math.min(bc + BC, cols);
          for (let r = br; r < re; r++)
            for (let c = bc; c < ce; c++) { tot++; if (next[r][c] > 0) pop++; }

          let regionChanged = 0;
          for (let r = br; r < re; r++)
            for (let c = bc; c < ce; c++)
              if ((next[r][c] > 0) !== (grid2ago[r][c] > 0)) regionChanged++;

          const regionStale = regionChanged / tot < 0.01;
          const density = pop / tot;

          if (density < emptyThreshold || (regionStale && density < 0.3)) {
            const n = regionStale ? seedCount : Math.ceil(seedCount * 0.5);
            for (let i = 0; i < n; i++) {
              const sr = br + (Math.random() * (re - br) | 0);
              const sc = bc + (Math.random() * (ce - bc) | 0);
              next[sr][sc] = 1;
            }
          }
        }
      }
    }

    grid2ago = grid;
    grid = next;
    gen++;
  }

  /* --- draw with interpolation --- */
  function draw(t) {
    ctx.clearRect(0, 0, W, H);

    ctx.globalAlpha = 1;
    ctx.drawImage(gridCanvas, 0, 0, W, H);

    const stable = new Map();
    const born = new Map();
    const dying = new Map();

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const prev = prevGrid[r][c];
        const curr = grid[r][c];
        if (curr > 0 && prev > 0) {
          const col = ageColor(curr);
          if (!stable.has(col)) stable.set(col, []);
          stable.get(col).push(r, c);
        } else if (curr > 0) {
          const col = ageColor(curr);
          if (!born.has(col)) born.set(col, []);
          born.get(col).push(r, c);
        } else if (prev > 0) {
          const col = ageColor(prev);
          if (!dying.has(col)) dying.set(col, []);
          dying.get(col).push(r, c);
        }
      }
    }

    ctx.globalAlpha = 1;
    for (const [col, cells] of stable) {
      ctx.fillStyle = col;
      ctx.beginPath();
      for (let i = 0; i < cells.length; i += 2)
        triPath(ctx, cells[i], cells[i + 1]);
      ctx.fill();
    }

    ctx.globalAlpha = t;
    for (const [col, cells] of born) {
      ctx.fillStyle = col;
      ctx.beginPath();
      for (let i = 0; i < cells.length; i += 2)
        triPath(ctx, cells[i], cells[i + 1]);
      ctx.fill();
    }

    ctx.globalAlpha = 1 - t;
    for (const [col, cells] of dying) {
      ctx.fillStyle = col;
      ctx.beginPath();
      for (let i = 0; i < cells.length; i += 2)
        triPath(ctx, cells[i], cells[i + 1]);
      ctx.fill();
    }

    ctx.globalAlpha = 1;
  }

  /* --- loop: step on tick, draw every frame; stop if canvas leaves the DOM --- */
  let raf = 0, last = 0;
  function loop(now) {
    if (!canvas.isConnected) { raf = 0; return; }
    if (now - last >= TICK) { step(); last = now; }
    const t = Math.min((now - last) / TICK, 1);
    draw(t);
    raf = requestAnimationFrame(loop);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else if (!raf) { last = performance.now(); raf = requestAnimationFrame(loop); }
  });
  addEventListener("resize", resize, { passive: true });

  resize();
  draw(1);
  last = performance.now();
  raf = requestAnimationFrame(loop);
})();
