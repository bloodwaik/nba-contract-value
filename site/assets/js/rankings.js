// Renders a full rankings page: filters, spotlights, histogram, DataTable.

import { fmt, surplusPill, dollarsPill, loadJSON } from "./layout.js";

export async function renderRankings({ dataPath, mount, kind }) {
  const data = await loadJSON(dataPath);
  const players = data.players;
  const cap = data.cap;
  mount.dataset.kind = kind;

  // ---- Spotlight cards
  const best = players[0];
  const worst = players[players.length - 1];
  const sortedByPaid = [...players].sort((a, b) => b.salary - a.salary);
  const richestUnderpaid = sortedByPaid.find(p => p.surplus_cap_pct > 0) || best;

  mount.querySelector("#stat-players").textContent = players.length;
  mount.querySelector("#stat-r2").textContent = data.meta.model_r2.toFixed(3);
  mount.querySelector("#stat-mae").textContent = (data.meta.model_cv_mae_cap_pct * 100).toFixed(2) + " %";
  mount.querySelector("#stat-cap").textContent = fmt.moneyPlain(cap);

  fillSpotlight(mount.querySelector("#spotlight-best"), best, "good");
  fillSpotlight(mount.querySelector("#spotlight-worst"), worst, "bad");
  fillSpotlight(mount.querySelector("#spotlight-rich"), richestUnderpaid, "good");

  // ---- Build filter options
  const teams = Array.from(new Set(players.map(p => p.team).filter(Boolean))).sort();
  const teamSelect = mount.querySelector("#filter-team");
  teams.forEach(t => {
    const o = document.createElement("option");
    o.value = t; o.textContent = t;
    teamSelect.appendChild(o);
  });

  // ---- Build the table (desktop)
  const tbody = mount.querySelector("#rankings-tbody");
  const rowHTML = (p) => {
    const rankClass = p.rank <= 10 ? "top" : p.rank > players.length - 10 ? "bot" : "";
    return `
      <tr data-team="${p.team || ""}" data-pos="${p.position || ""}" data-age="${p.age || 0}"
          data-salary="${p.salary || 0}" data-surplus="${p.surplus_dollars || 0}">
        <td><span class="rank-badge ${rankClass}">${p.rank}</span></td>
        <td class="player">${p.name}</td>
        <td class="dim">${p.team || "—"}</td>
        <td class="center">${p.position || "—"}</td>
        <td class="right">${fmt.int(p.age)}</td>
        <td class="right">${fmt.num(p.bpm, 1)}</td>
        <td class="right dim">${fmt.int(p.total_minutes)}</td>
        <td class="right">${fmt.moneyPlain(p.salary)}</td>
        <td class="right dim">${fmt.pct(p.actual_cap_pct)}</td>
        <td class="right">${fmt.moneyPlain(p.expected_salary)}</td>
        <td class="right">${fmt.pct(p.expected_cap_pct)}</td>
        <td class="right">${surplusPill(p.surplus_cap_pct)}</td>
        <td class="right">${dollarsPill(p.surplus_dollars)}</td>
      </tr>
    `;
  };
  tbody.innerHTML = players.map(rowHTML).join("");

  // ---- Build the card list (mobile — populated for all players, paginated client-side)
  const mobileMount = mount.querySelector("#rankings-mobile");
  const PAGE_SIZE = 25;
  let visibleCount = PAGE_SIZE;

  const cardHTML = (p) => {
    const rankClass = p.rank <= 10 ? "top" : p.rank > players.length - 10 ? "bot" : "";
    const dollarsCls = p.surplus_dollars >= 0 ? "pill-good" : "pill-bad";
    return `
      <article class="mrank-card" data-team="${p.team || ""}" data-pos="${p.position || ""}"
               data-age="${p.age || 0}" data-salary="${p.salary || 0}" data-surplus="${p.surplus_dollars || 0}">
        <header class="mrank-head">
          <span class="rank-badge ${rankClass}">#${p.rank}</span>
          <div class="mrank-name">
            <div class="mrank-player">${p.name}</div>
            <div class="mrank-meta">${p.team || "—"} · ${p.position || "—"} · ${fmt.int(p.age)} yrs · BPM ${fmt.num(p.bpm, 1)}</div>
          </div>
          <span class="pill ${dollarsCls} mrank-delta">${fmt.money(p.surplus_dollars)}</span>
        </header>
        <div class="mrank-grid">
          <div><span class="mrank-k">Paid</span><span class="mrank-v">${fmt.moneyPlain(p.salary)} <span class="dim">(${fmt.pct(p.actual_cap_pct)})</span></span></div>
          <div><span class="mrank-k">Earned</span><span class="mrank-v">${fmt.moneyPlain(p.expected_salary)} <span class="dim">(${fmt.pct(p.expected_cap_pct)})</span></span></div>
          <div><span class="mrank-k">Surplus %</span><span class="mrank-v">${surplusPill(p.surplus_cap_pct)}</span></div>
        </div>
      </article>
    `;
  };

  function renderMobile() {
    if (!mobileMount) return;
    const html = players.slice(0, visibleCount).map(cardHTML).join("");
    const more = visibleCount < players.length
      ? `<button class="mrank-more" type="button">Show more (${players.length - visibleCount} left)</button>`
      : "";
    mobileMount.innerHTML = html + more;
    const btn = mobileMount.querySelector(".mrank-more");
    if (btn) btn.addEventListener("click", () => {
      visibleCount = Math.min(visibleCount + PAGE_SIZE * 2, players.length);
      renderMobile();
      applyMobileFilters();
    });
  }
  renderMobile();

  // ---- Histogram of surplus dollars
  const surplusValues = players.map(p => p.surplus_dollars || 0);
  drawHistogram(mount.querySelector("#hist-canvas"), surplusValues);

  // ---- DataTables init
  const $ = window.jQuery;
  const dt = $("#rankings-table").DataTable({
    paging: true,
    pageLength: 25,
    lengthMenu: [10, 25, 50, 100, 366],
    order: [],            // keep our pre-sorted rank order
    columnDefs: [
      { targets: [0, 4, 5, 6, 7, 8, 9, 10, 11, 12], orderable: true },
      { targets: 0, type: "num" },
      { targets: [4, 5, 6], type: "num" },
    ],
    dom: '<"top"lf>rt<"bottom"ip>',
    language: { search: "Search:", lengthMenu: "Show _MENU_ per page" },
  });

  // ---- Custom filters (team, pos, age, salary, surplus polarity)
  function readFilters() {
    return {
      team: mount.querySelector("#filter-team").value,
      pos: mount.querySelector("#filter-pos").value,
      ageMax: parseInt(mount.querySelector("#filter-age").value || "99", 10),
      salaryMax: parseFloat(mount.querySelector("#filter-salary").value || "999") * 1_000_000,
      polarity: mount.querySelector("#filter-polarity").value,
    };
  }

  function matches(f, t, p, a, s, sur) {
    if (f.team && t !== f.team) return false;
    if (f.pos && !p.includes(f.pos)) return false;
    if (a > f.ageMax) return false;
    if (s > f.salaryMax) return false;
    if (f.polarity === "pos" && sur < 0) return false;
    if (f.polarity === "neg" && sur >= 0) return false;
    return true;
  }

  function applyMobileFilters() {
    const f = readFilters();
    mobileMount?.querySelectorAll(".mrank-card").forEach(card => {
      const ok = matches(f,
        card.dataset.team, card.dataset.pos, +card.dataset.age,
        +card.dataset.salary, +card.dataset.surplus);
      card.style.display = ok ? "" : "none";
    });
  }

  function applyFilters() {
    const f = readFilters();
    $.fn.dataTable.ext.search.length = 0;
    $.fn.dataTable.ext.search.push((settings, _data, idx) => {
      const row = settings.aoData[idx].nTr;
      return matches(f,
        row.dataset.team, row.dataset.pos, +row.dataset.age,
        +row.dataset.salary, +row.dataset.surplus);
    });
    dt.draw();
    applyMobileFilters();
  }
  ["filter-team", "filter-pos", "filter-age", "filter-salary", "filter-polarity"]
    .forEach(id => mount.querySelector("#" + id).addEventListener("input", applyFilters));
  mount.querySelector("#filter-reset").addEventListener("click", () => {
    mount.querySelector("#filter-team").value = "";
    mount.querySelector("#filter-pos").value = "";
    mount.querySelector("#filter-age").value = "";
    mount.querySelector("#filter-salary").value = "";
    mount.querySelector("#filter-polarity").value = "";
    applyFilters();
  });
}

function story(p) {
  const earned = (p.expected_cap_pct * 100).toFixed(1);
  const paid = (p.actual_cap_pct * 100).toFixed(1);
  const dollars = Math.abs(p.surplus_dollars / 1_000_000).toFixed(1);
  if (p.surplus_dollars >= 0) {
    return `Plays like a player earning <strong>${earned}%</strong> of the cap, but only paid <strong>${paid}%</strong>. The team effectively gets <strong>$${dollars}M of extra cap room</strong> to spend on the rest of the roster.`;
  }
  return `Plays like a player earning <strong>${earned}%</strong> of the cap, but paid <strong>${paid}%</strong>. The contract eats <strong>$${dollars}M more</strong> of cap room than the on-court value supports.`;
}

function fillSpotlight(card, p, tone) {
  if (!card) return;
  card.querySelector(".name").textContent = p.name;
  card.querySelector(".meta").textContent =
    `${p.team || "—"} · ${p.position} · ${p.age} yrs · BPM ${fmt.num(p.bpm)} · ${fmt.int(p.total_minutes)} min`;
  const delta = card.querySelector(".delta");
  delta.textContent = fmt.money(p.surplus_dollars);
  delta.className = `delta ${tone}`;
  const detail = card.querySelector(".detail");
  if (detail) {
    detail.innerHTML = `
      Paid <strong>${fmt.pct(p.actual_cap_pct)}</strong> of cap ·
      Earned <strong>${fmt.pct(p.expected_cap_pct)}</strong> ·
      Salary ${fmt.moneyPlain(p.salary)}`;
  }
  const storyEl = card.querySelector(".story");
  if (storyEl) storyEl.innerHTML = story(p);
}

function drawHistogram(canvas, values) {
  if (!canvas || !window.Chart) return;
  const bins = 24;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const step = (max - min) / bins;
  const counts = new Array(bins).fill(0);
  const labels = [];
  for (let i = 0; i < bins; i++) {
    labels.push(`${((min + i * step) / 1e6).toFixed(1)}M`);
  }
  values.forEach(v => {
    let b = Math.floor((v - min) / step);
    if (b >= bins) b = bins - 1;
    if (b < 0) b = 0;
    counts[b]++;
  });
  const zeroIdx = Math.floor((0 - min) / step);
  const colors = counts.map((_, i) => i < zeroIdx
    ? "rgba(248, 113, 113, 0.75)"
    : "rgba(52, 211, 153, 0.75)");

  new window.Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data: counts, backgroundColor: colors, borderRadius: 4 }] },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        callbacks: {
          title: (items) => `Surplus ≈ $${items[0].label}`,
          label: (ctx) => `${ctx.parsed.y} player${ctx.parsed.y === 1 ? "" : "s"}`,
        }
      } },
      scales: {
        x: { ticks: { color: "#5b637b", maxTicksLimit: 8 }, grid: { display: false } },
        y: { ticks: { color: "#99a0b3" }, grid: { color: "rgba(255,255,255,0.04)" } }
      }
    }
  });
}
