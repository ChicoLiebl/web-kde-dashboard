"use strict";
// Pixel crabs: one per Claude session, showing what it's doing (its pose) and the kind of work
// (its hat, and the tools it works with). Original sprites, drawn here cell by cell; the style
// is inspired by brushknight/agents-deck's critters.
//
// Each kind + pose becomes one horizontal sprite sheet (a frame every W cells), drawn once on a
// canvas and cached as a data URL. The page animates a sheet with CSS steps, so the animation
// keeps running when the dashboard re-renders its cards (several times a second).
const CRAB = (() => {
  const W = 28, H = 18;          // one frame, in cells
  const BX = 3, BY = 8;          // the body: 12×6 cells from here
  const EYES = [6, 11];          // eye columns (each eye 1×2), on body rows 2–3
  const LEGS = [4, 6, 11, 13];

  const PAL = {
    O: "#d97757",  // body
    S: "#86716a",  // body, dozing (marked idle)
    e: "#121418",  // eyes
    w: "#eef0f4", W: "#9aa3b2", k: "#0b0d10", d: "#3a404d", q: "#7d8596", p: "#d5dae3",
    b: "#4c8dff", B: "#2f5fb3", g: "#3fb950", G: "#1f7a3a", y: "#f2c94c", Y: "#c99a1e",
    o: "#e0b040", c: "#7fd4ff", C: "#2f7f9a", r: "#c3cad6", R: "#8b2b2b", L: "#ff5a5a", l: "#5a1c1c",
    n: "#8a6a45", h: "#5a4030", s: "#9aa4b2", K: "#353b47", V: "#4a5262",
  };

  // Hats, 14×4 cells from (BX-1, BY-4): the brim sits on the body's top edge.
  const HATS = {
    software: [  // a beanie
      "......ww......",
      "....bbbbbb....",
      "..bbbbbbbbbb..",
      ".BBBBBBBBBBBB.",
    ],
    firmware: [  // a headband with an antenna; its LED (1) blinks while working
      "..........1...",
      "..........s...",
      "..........s...",
      ".GGGGGGGGGGGG.",
    ],
    pcb: [  // a headband with a jeweller's loupe
      "........rrr...",
      ".......rcwcr..",
      ".......rcccr..",
      ".dddddddrrrdd.",
    ],
    cad: [  // a hard hat
      "....yyYYyy....",
      "...yyyYYyyy...",
      "..yyyyYYyyyy..",
      "YYYYYYYYYYYYYY",
    ],
  };

  const KINDS = ["software", "firmware", "pcb", "cad"];
  const KIND_LABEL = { software: "software", firmware: "firmware", pcb: "PCB", cad: "CAD" };

  // Poses: frames, ms per frame, and what each frame looks like.
  //   eyes: open | up | right | upright | closed | happy     arms: down | up | typeA | typeB | flag
  //   legs: stand | walkA | walkB | tuck                     dy: hop height (negative = up)
  const POSES = {
    work:     { n: 4, ms: 160, label: "working (kind's tools)",
                f: f => ({ eyes: "right", arms: f % 2 ? "typeB" : "typeA", prop: "work" }) },
    read:     { n: 4, ms: 320, label: "reading",
                f: () => ({ eyes: "right", prop: "read" }) },
    web:      { n: 4, ms: 260, label: "on the web",
                f: () => ({ eyes: "upright", prop: "globe" }) },
    plan:     { n: 4, ms: 500, label: "planning",
                f: f => ({ eyes: "right", arms: f % 2 ? "typeB" : "typeA", prop: "checklist" }) },
    delegate: { n: 2, ms: 260, label: "subagents",
                f: f => ({ legs: f ? "walkB" : "walkA", prop: "mini" }) },
    think:    { n: 4, ms: 380, label: "thinking",
                f: f => ({ eyes: f % 2 ? "up" : "upright", arms: "typeA", prop: "thought" }) },
    run:      { n: 6, ms: 200, label: "using a tool",
                f: f => ({ legs: f % 2 ? "walkB" : "walkA", prop: "dots", dots: (f >> 1) + 1 }) },
    ask:      { n: 2, ms: 500, label: "needs you",
                f: () => ({ eyes: "up", arms: "up", prop: "mark" }) },
    celebrate:{ n: 4, ms: 170, label: "just finished",
                f: f => ({ eyes: "happy", arms: "flag", prop: "flag", dy: [0, -2, -3, -2][f],
                           legs: f ? "tuck" : "stand" }) },
    done:     { n: 4, ms: 380, label: "finished, waiting",
                f: () => ({ eyes: "up", arms: "flag", prop: "flag" }) },
    sleep:    { n: 4, ms: 650, label: "marked idle",
                f: () => ({ eyes: "closed", body: "S", prop: "zz" }) },
    idle:     { n: 3, ms: 420, label: "starting",
                f: f => ({ prop: "dots", dots: f + 1 }) },
  };

  // ---- drawing

  function painter(ctx, x0) {
    const px = (x, y, col, w = 1, h = 1) => {
      ctx.fillStyle = PAL[col] || col;
      ctx.fillRect(x0 + x, y, w, h);
    };
    const stamp = (x, y, rows, map = {}) => rows.forEach((row, j) => [...row].forEach((ch, i) => {
      const col = map[ch] ?? ch;
      if (col !== "." && col !== " ") px(x + i, y + j, col);
    }));
    const line = (xa, ya, xb, yb, col) => {  // straight or 45° lines only
      const n = Math.max(Math.abs(xb - xa), Math.abs(yb - ya));
      for (let i = 0; i <= n; i++) px(xa + Math.round((xb - xa) * i / (n || 1)), ya + Math.round((yb - ya) * i / (n || 1)), col);
    };
    const box = (x, y, w, h, col) => { px(x, y, col, w, 1); px(x, y + h - 1, col, w, 1); px(x, y, col, 1, h); px(x + w - 1, y, col, 1, h); };
    return { px, stamp, line, box };
  }

  const MARKS = {
    "?": [".yyy.", "y...y", "....y", "...y.", "..y..", ".....", "..y.."],
    "!": [".yy.", ".yy.", ".yy.", ".yy.", ".yy.", "....", ".yy."],
  };
  const Z = ["wwww", "..w.", ".w..", "wwww"];
  const LAND = [  // the globe's map, scrolled one column at a time
    "..gg....g.....",
    ".ggg...ggg....",
    "..gg..gggg..g.",
    "...g...gg..ggg",
    "........g...gg",
    "..g.........g.",
    ".ggg..........",
  ];
  const DISC = ["..xxx..", ".xxxxx.", "xxxxxxx", "xxxxxxx", "xxxxxxx", ".xxxxx.", "..xxx.."];

  // The tools of each kind of work, for the "work" pose (4 frames).
  const WORK = {
    software(d, f) {  // a terminal: ">" and a blinking cursor
      d.stamp(18, 7, ["ddddddddd", "dkkkkkkkd", "dkkkkkkkd", "dkkkkkkkd", "dkkkkkkkd", "dkkkkkkkd", "ddddddddd"]);
      d.px(20, 9, "g"); d.px(21, 10, "g"); d.px(20, 11, "g");
      if (f < 2) d.px(23, 11, "g", 2, 1);
      d.px(23, 9, "W", 1 + (f % 3), 1);
    },
    firmware(d, f) {  // a chip with a status LED
      d.stamp(17, 6, [
        "..s.s.s..",
        ".VVVVVVV.",
        "sKKKKKKKs",
        ".KKKKKKK.",
        "sKKKKKKKs",
        ".KKKKKKK.",
        "sKwKKKKKs",
        ".KKKKKKK.",
        "..s.s.s..",
      ]);
      d.px(26, 7, f < 2 ? "L" : "l");
      d.px(26, 9 + (f % 3) * 2, f % 2 ? "g" : "G");  // data on a pin
    },
    pcb(d, f) {  // a board and a soldering iron, with sparks and a wisp of smoke
      d.stamp(17, 10, [
        "GGGGGGGGGG",
        "GwooooGGwG",
        "GGGGGoGGoG",
        "GGwoooGGoG",
        "GwGGGGoooG",
        "GGGGGGGGGG",
      ]);
      d.px(22, 9, "w"); d.px(23, 8, "s"); d.px(24, 7, "s"); d.px(25, 6, "R"); d.px(26, 5, "R");
      if (f % 2 === 0) { d.px(21, 9, "y"); d.px(21, 8, "w"); }
      d.px(20 - (f % 2), 7 - f, "W");
    },
    cad(d, f) {  // a wireframe cube, turning
      const p = (f >> 1) & 1;
      const back = p ? [18, 6] : [20, 6], front = p ? [20, 8] : [18, 8];
      d.box(back[0], back[1], 6, 6, "C");
      for (const [dx, dy] of [[0, 0], [5, 0], [0, 5], [5, 5]]) d.line(back[0] + dx, back[1] + dy, front[0] + dx, front[1] + dy, "C");
      d.box(front[0], front[1], 6, 6, "c");
    },
  };

  const PROPS = {
    work: (d, f, s, kind) => (WORK[kind] || WORK.software)(d, f),
    read(d, f) {  // a page under a magnifier that scans across it
      d.stamp(19, 8, ["ppppppp", "ppppppp", "pqqqqqp", "ppppppp", "pqqqqpp", "ppppppp", "pqqqqqp", "ppppppp"]);
      const x = 18 + [0, 2, 4, 2][f], y = 7;
      d.stamp(x, y, [".rrr.", "r...r", "r...r", "r...r", ".rrr."]);
      d.px(x + 1, y + 1, "rgba(159,220,255,.45)", 3, 3);
      d.px(x, y + 5, "h"); d.px(x - 1, y + 6, "h");
    },
    globe(d, f) {
      DISC.forEach((row, j) => [...row].forEach((ch, i) => {
        if (ch !== "x") return;
        const land = LAND[j][(i + f * 2) % 14] === "g";
        d.px(19 + i, 6 + j, land ? "g" : "b");
      }));
      d.px(20, 7, "w");
    },
    checklist(d, f) {  // a clipboard, one more box ticked each frame
      d.px(18, 4, "n", 8, 12);
      d.px(19, 5, "p", 6, 10);
      d.px(20, 3, "d", 4, 2);
      for (let i = 0; i < 3; i++) {
        const y = 7 + i * 3;
        d.px(20, y, i < f ? "g" : "q", 2, 2);
        d.px(23, y, "q", 1 + (i % 2), 1);
      }
    },
    mini(d, f) {  // a small crab in tow
      const y = 11 - (f % 2);
      d.px(20, y, "O", 6, 3);
      d.px(21, y + 1, "e"); d.px(24, y + 1, "e");
      d.px(19, y + 1, "O"); d.px(26, y + 1, "O");
      for (const x of f ? [21, 24] : [20, 22, 23, 25]) d.px(x, y + 3, "O", 1, 1 + (f % 2));
    },
    thought(d, f) {
      if (f >= 1) d.px(17, 6, "W");
      if (f >= 2) d.px(19, 4, "W", 2, 2);
      if (f >= 3) d.px(22, 1, "w", 3, 3);
    },
    dots(d, f, s) {
      for (let i = 0; i < s.dots; i++) d.px(18 + i * 2, 13, "w");
    },
    mark(d, f, s) {
      const rows = MARKS[s.mark] || MARKS["?"];
      d.stamp(19, 1, rows, { y: f ? "#6b5600" : "y" });
    },
    flag(d, f) {  // a checkered flag, waving
      d.px(16, 2, "r", 1, 10);
      for (let cx = 0; cx < 6; cx++) {
        const wave = (cx + f) % 4 < 2 ? 0 : 1;
        for (let cy = 0; cy < 4; cy++) d.px(17 + cx, 2 + cy + wave, (cx + cy) % 2 ? "k" : "w");
      }
    },
    zz(d, f) {
      const a = [1, .8, .55, .3][f];
      d.stamp(18, 10 - f, Z, { w: `rgba(238,240,244,${a})` });
      d.stamp(22, 5 - f, Z, { w: `rgba(238,240,244,${a * .7})` });
    },
  };

  function drawFrame(ctx, x0, kind, s, f) {
    const d = painter(ctx, x0), dy = s.dy || 0, body = s.body || "O";
    // legs (under the body), with a shadow while it's in the air
    const legs = s.legs || "stand";
    if (dy) d.px(BX + 1, 16, "rgba(0,0,0,.35)", 10, 1);
    LEGS.forEach((x, i) => {
      let len = 2;
      if (legs === "walkA" && (i === 0 || i === 2)) len = 1;
      if (legs === "walkB" && (i === 1 || i === 3)) len = 1;
      if (legs === "tuck") len = 1;
      d.px(x, BY + 6 + dy, body, 1, len);
    });
    d.px(BX, BY + dy, body, 12, 6);
    // arms
    const arms = s.arms || "down";
    const left = arms === "up" ? [6, 3] : arms === "typeB" ? [9, 2] : [10, 2];
    const right = arms === "up" || arms === "flag" ? [6, 3] : arms === "typeA" ? [9, 2] : [10, 2];
    d.px(BX - 1, left[0] + dy, body, 1, left[1]);
    d.px(BX + 12, right[0] + dy, body, 1, right[1]);
    // eyes
    const eyes = s.eyes || "open";
    for (const ex of EYES) {
      if (eyes === "closed") d.px(ex - (ex < 9 ? 1 : 0), 11 + dy, "e", 2, 1);
      else if (eyes === "happy") { d.px(ex - 1, 11 + dy, "e"); d.px(ex, 10 + dy, "e"); d.px(ex + 1, 11 + dy, "e"); }
      else {
        const x = ex + (eyes === "right" || eyes === "upright" ? 1 : 0);
        const y = eyes === "up" || eyes === "upright" ? 9 : 10;
        d.px(x, y + dy, "e", 1, 2);
      }
    }
    // hat
    const working = !!(s.prop && ["work", "read", "globe", "checklist", "mini", "thought", "dots"].includes(s.prop));
    d.stamp(BX - 1, BY - 4 + dy, HATS[kind] || HATS.software,
      { 1: working ? (f % 2 ? "l" : "L") : "l" });
    // what it's doing
    if (s.prop) PROPS[s.prop](d, f, s, kind);
  }

  const sheets = new Map();

  // {url, n, ms} for a kind and pose; opts: {mark: "?"|"!"}
  function sheet(kind, pose, opts = {}) {
    kind = HATS[kind] ? kind : "software";
    pose = POSES[pose] ? pose : "idle";
    const key = `${kind}|${pose}|${opts.mark || ""}`;
    let s = sheets.get(key);
    if (!s) {
      const P = POSES[pose], cv = document.createElement("canvas");
      cv.width = W * P.n; cv.height = H;
      const ctx = cv.getContext("2d");
      for (let f = 0; f < P.n; f++) drawFrame(ctx, f * W, kind, { mark: opts.mark, ...P.f(f) }, f);
      s = { url: cv.toDataURL(), n: P.n, ms: P.ms };
      sheets.set(key, s);
    }
    return s;
  }

  // The crab's HTML. The negative delay keeps every copy of a pose in step with the clock, so a
  // re-rendered crab carries on where the old one was instead of restarting.
  function html(kind, pose, { title = "", mark } = {}) {
    const s = sheet(kind, pose, { mark }), period = s.n * s.ms;
    return `<div class="crab" title="${title.replace(/"/g, "&quot;")}"><img alt="" src="${s.url}" style="--n:${s.n};animation-duration:${period}ms;animation-delay:-${Date.now() % period}ms"></div>`;
  }

  // Every kind × pose, for reviewing the art: open the dashboard with #crabs.
  function gallery() {
    const rows = KINDS.map(k => `<tr><th>${KIND_LABEL[k]}</th>${Object.keys(POSES).map(p =>
      `<td>${html(k, p, { title: `${k} · ${p}` })}</td>`).join("")}</tr>`).join("");
    const head = Object.entries(POSES).map(([p, P]) => `<th>${p}<small>${P.label}</small></th>`).join("");
    return `<table class="crab-gallery"><tr><th></th>${head}</tr>${rows}
      <tr><th>asking</th><td>${html("software", "ask", { mark: "!" })}<small>permission ("!")</small></td></tr></table>`;
  }

  return { sheet, html, gallery, KINDS, POSES, W, H };
})();
