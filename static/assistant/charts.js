// Wykres ocen z suwaków w czasie (moduł B). Bez bibliotek zewnętrznych — działa offline.
// Użycie: <div class="t-chart" data-chart='{"criteria":[...],"series":{...}}' data-link="#"></div>
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
  const W = 640, H = 220, L = 34, R = 12, T = 12, B = 28;
  const POINTS = [1, 3, 5, 7, 9];
  const LABELS = { 1: "znacznie poniżej", 3: "poniżej", 5: "na poziomie", 7: "powyżej", 9: "znacznie powyżej" };

  const el = (name, attrs = {}, parent) => {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  };
  const day = (iso) => new Date(iso + "T00:00:00").getTime();
  const pl = (iso) => iso.slice(8, 10) + "." + iso.slice(5, 7) + "." + iso.slice(0, 4);
  const tone = (v) => (v <= 2 ? "l1" : v <= 4 ? "l2" : v <= 6 ? "l3" : v <= 8 ? "l4" : "l5");

  function draw(box, svgHost, points, linkBase) {
    svgHost.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", class: "t-chart-svg" }, svgHost);
    const y = (v) => T + (9 - v) / 8 * (H - T - B);
    for (const p of POINTS) {
      el("line", { x1: L, x2: W - R, y1: y(p), y2: y(p), class: "t-grid" }, svg);
      const t = el("text", { x: L - 8, y: y(p) + 4, class: "t-axis", "text-anchor": "end" }, svg);
      t.textContent = p;
      el("title", {}, t).textContent = LABELS[p];
    }
    if (!points.length) {
      const t = el("text", { x: W / 2, y: H / 2, class: "t-axis", "text-anchor": "middle" }, svg);
      t.textContent = "Brak ocen z suwaków dla tego kryterium";
      svg.setAttribute("aria-label", "brak danych");
      return;
    }
    let x0 = day(points[0][0]), x1 = day(points[points.length - 1][0]);
    if (x1 - x0 < 30 * 864e5) { x0 -= 15 * 864e5; x1 += 15 * 864e5; }
    const x = (iso) => L + 8 + (day(iso) - x0) / (x1 - x0) * (W - L - R - 16);

    // osie miesięcy: co 1, 2, 3 albo 6 miesięcy, żeby etykiety się nie nakładały
    const start = new Date(x0), months = (new Date(x1).getFullYear() - start.getFullYear()) * 12 + new Date(x1).getMonth() - start.getMonth();
    const step = months <= 8 ? 1 : months <= 16 ? 2 : months <= 30 ? 3 : 6;
    let first = true;
    for (let m = new Date(start.getFullYear(), start.getMonth() + 1, 1); m.getTime() <= x1; m.setMonth(m.getMonth() + step), first = false) {
      const xp = L + 8 + (m.getTime() - x0) / (x1 - x0) * (W - L - R - 16);
      el("line", { x1: xp, x2: xp, y1: H - B, y2: H - B + 4, class: "t-tick" }, svg);
      const t = el("text", { x: xp, y: H - 8, class: "t-axis", "text-anchor": "middle" }, svg);
      t.textContent = MONTHS[m.getMonth()] + (m.getMonth() === 0 || first ? " " + m.getFullYear() : "");
    }

    const d = points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
    el("path", { d, class: "t-line" }, svg);
    for (const [iso, v, noteId] of points) {
      const a = el("a", { href: (linkBase || "") + "#" + noteId }, svg);
      const c = el("circle", { cx: x(iso), cy: y(v), r: 5.5, class: "t-dot " + tone(v) }, a);
      el("title", {}, c).textContent = `${pl(iso)}: ${String(v).replace(".", ",")} pkt`;
    }
    const avg = points.reduce((s, p) => s + p[1], 0) / points.length;
    svg.setAttribute("aria-label", `${points.length} ocen, średnia ${avg.toFixed(1).replace(".", ",")}`);
  }

  document.querySelectorAll(".t-chart[data-chart]").forEach((box) => {
    const data = JSON.parse(box.dataset.chart);
    const linkBase = box.dataset.link || "";
    const pick = box.querySelector(".t-chart-pick");
    const host = box.querySelector(".t-chart-area");
    let current = box.dataset.selected && data.series[box.dataset.selected] ? box.dataset.selected : "";
    const render = () => {
      pick.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.code === current)));
      draw(box, host, data.series[current] || [], linkBase);
    };
    for (const c of data.criteria) {
      const n = (data.series[c.code] || []).length;
      if (!n && c.code) continue;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "t-pill";
      b.dataset.code = c.code;
      b.textContent = c.name + (n ? ` (${n})` : "");
      b.addEventListener("click", () => { current = c.code; render(); });
      pick.appendChild(b);
    }
    render();
  });
})();
