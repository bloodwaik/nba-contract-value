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

  // ---- Build the table
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
  const $rows = $("#rankings-table tbody tr");
  function applyFilters() {
    const team = mount.querySelector("#filter-team").value;
    const pos = mount.querySelector("#filter-pos").value;
    const ageMax = parseInt(mount.querySelector("#filter-age").value || "99", 10);
    const salaryMax = parseFloat(mount.querySelector("#filter-salary").value || "999") * 1_000_000;
    const polarity = mount.querySelector("#filter-polarity").value;

    $.fn.dataTable.ext.search.length = 0;
    $.fn.dataTable.ext.search.push((settings, _data, idx) => {
      const row = settings.aoData[idx].nTr;
      const t = row.dataset.team, p = row.dataset.pos;
      const a = +row.dataset.age, s = +row.dataset.salary, sur = +row.dataset.surplus;
      if (team && t !== team) return false;
      if (pos && !p.includes(pos)) return false;
      if (a > ageMax) return false;
      if (s > salaryMax) return false;
      if (polarity === "pos" && sur < 0) return false;
      if (polarity === "neg" && sur >= 0) return false;
      return true;
    });
    dt.draw();
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
