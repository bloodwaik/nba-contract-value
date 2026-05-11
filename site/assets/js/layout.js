// Shared layout: nav rendering, active page highlight, scroll animations,
// shared formatters used by every page.

// Mobile-friendly labels (mobile CSS allows wrapping to 2 lines, so 2-word labels are fine)
const PAGES = [
  { href: "index.html", label: "Overview" },
  { href: "regular-season.html", label: "Reg Season" },
  { href: "playoffs.html", label: "Playoffs" },
  { href: "daily.html", label: "Daily" },
  { href: "algorithm.html", label: "Algorithm" },
];

export function renderShell({ active } = {}) {
  document.querySelectorAll(".nav-mount").forEach((mount) => {
    const linkHTML = PAGES.map((p) => `
      <a href="${p.href}" class="nav-link ${p.href === active ? "active" : ""}">${p.label}</a>
    `).join("");
    mount.outerHTML = `
      <nav class="nav">
        <div class="nav-inner">
          <a href="index.html" class="nav-brand">
            <span class="logo">$</span>
            <span>Cap Value Lab</span>
          </a>
          <div class="nav-links">${linkHTML}</div>
        </div>
      </nav>`;
  });

  document.querySelectorAll(".footer-mount").forEach((mount) => {
    mount.outerHTML = `
      <footer>
        <div class="container">
          <div style="display:flex; justify-content:space-between; gap:20px; flex-wrap:wrap;">
            <div>
              <div style="font-weight:700; color:var(--text);">Cap Value Lab · 2025-26</div>
              <div class="tiny">Data: Basketball Reference. Model: Ridge regression on standardized box-score features.</div>
            </div>
            <div class="tiny">Built as a working demo — not investment advice.</div>
          </div>
        </div>
      </footer>`;
  });

  // Scroll-in animation (lightweight AOS substitute)
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add("in");
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.08 });
  document.querySelectorAll("[data-aos]").forEach((el) => io.observe(el));
}

export const fmt = {
  money(v) {
    if (v == null || isNaN(v)) return "—";
    const m = v / 1_000_000;
    const sign = v >= 0 ? "+" : "−";
    return `${sign}$${Math.abs(m).toFixed(2)}M`;
  },
  moneyPlain(v) {
    if (v == null || isNaN(v)) return "—";
    const m = v / 1_000_000;
    return `$${m.toFixed(2)}M`;
  },
  pct(v, digits = 1) {
    if (v == null || isNaN(v)) return "—";
    return `${(v * 100).toFixed(digits)}%`;
  },
  pctSigned(v, digits = 1) {
    if (v == null || isNaN(v)) return "—";
    const sign = v >= 0 ? "+" : "−";
    return `${sign}${Math.abs(v * 100).toFixed(digits)}%`;
  },
  num(v, digits = 1) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toFixed(digits);
  },
  int(v) {
    if (v == null || isNaN(v)) return "—";
    return Math.round(Number(v)).toString();
  },
};

export async function loadJSON(path) {
  // Bust the browser cache — data files get regenerated, but their URLs don't change.
  // Without this, refreshes serve stale JSON from disk cache forever.
  const sep = path.includes("?") ? "&" : "?";
  const res = await fetch(`${path}${sep}v=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return await res.json();
}

export function surplusPill(v) {
  if (v == null) return `<span class="pill pill-mute">—</span>`;
  const cls = v >= 0 ? "pill-good" : "pill-bad";
  return `<span class="pill ${cls}">${fmt.pctSigned(v)}</span>`;
}

export function dollarsPill(v) {
  if (v == null) return `<span class="pill pill-mute">—</span>`;
  const cls = v >= 0 ? "pill-good" : "pill-bad";
  return `<span class="pill ${cls}">${fmt.money(v)}</span>`;
}
