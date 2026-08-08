const api = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw await errorFrom(r);
    return r.json();
  },
};

async function errorFrom(r) {
  try {
    const data = await r.json();
    return new Error(data.detail || r.statusText);
  } catch {
    return new Error(r.statusText);
  }
}

const SYSTEM_STATUSES = [
  "Not Started",
  "Concepts",
  "System Flow",
  "Service Flow",
  "Deep Dive Ready",
  "Interview Ready",
];

const GROUP_ORDER = [
  "Booking System",
  "Location Based Systems",
  "Notification System",
  "Ordering System",
  "Rate Limiter",
  "Simple Cassandra Based Systems",
  "Social Media",
  "Video Based Systems",
  "Ungrouped",
];

// Matches CLAUDE.md's 10-step framework and db.py's SECTION_KEYS.
const SECTION_LABELS = {
  "1_requirements": "Requirement Gathering",
  "2_queries": "Queries in Plain English",
  "3_state_diagram": "State Diagram",
  "4_api_endpoints": "API Endpoints",
  "5_concurrency": "Concurrency Requirements",
  "6_db_choice": "Database Choice + Justification",
  "7_db_schema": "Database Schema",
  "8_detailed_queries": "Detailed Queries",
  "9_read_write_paths": "Read/Write Paths",
  "10_scale_justification": "Scale Justification",
};
const SECTION_KEYS = Object.keys(SECTION_LABELS);

const AUTO_REFRESH_MS = 30000;

let allSystems = [];
let allConcepts = [];

// ------------------------------------------------------------- bootstrap

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initTabs();
  document.getElementById("refresh-btn").addEventListener("click", loadAll);
  document.getElementById("filter-status").addEventListener("change", renderSystems);
  document.getElementById("filter-label").addEventListener("change", renderSystems);
  document.getElementById("sort-systems").addEventListener("change", renderSystems);
  document.getElementById("sort-concepts").addEventListener("change", renderConcepts);
  loadAll();
  setInterval(loadAll, AUTO_REFRESH_MS);
});

function initTheme() {
  const saved = localStorage.getItem("hld-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    localStorage.setItem("hld-theme", cur);
  });
}

function initTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });
}

async function loadAll() {
  const [dashboard, systems, concepts] = await Promise.all([
    api.get("/api/dashboard"),
    api.get("/api/systems"),
    api.get("/api/concepts"),
  ]);
  allSystems = systems;
  allConcepts = concepts;

  renderSummary(dashboard);
  populateFilters(systems);
  renderSystems();
  renderConcepts();
  renderSessions(dashboard.recent_sessions);

  document.getElementById("last-updated").textContent =
    "Updated " + new Date().toLocaleTimeString();
}

// ----------------------------------------------------------------- summary

function renderSummary(dashboard) {
  const statusBadges = SYSTEM_STATUSES.map(
    (s) => `<span class="badge ${statusClass(s)}">${s}: ${dashboard.systems_by_status[s] || 0}</span>`
  ).join("");
  const fresh = dashboard.concepts_by_freshness["Fresh"] || 0;
  const stale = dashboard.concepts_by_freshness["Check recommended"] || 0;

  document.getElementById("summary-bar").innerHTML = `
    <div class="summary-group"><span class="summary-label">Systems</span>${statusBadges}</div>
    <div class="summary-group">
      <span class="summary-label">Concepts</span>
      <span class="badge badge-fresh">Fresh: ${fresh}</span>
      <span class="badge badge-stale">Check recommended: ${stale}</span>
    </div>
  `;
}

// ----------------------------------------------------------------- filters

function populateFilters(systems) {
  const statusSel = document.getElementById("filter-status");
  if (!statusSel.dataset.populated) {
    statusSel.innerHTML =
      `<option value="">All statuses</option>` +
      SYSTEM_STATUSES.map((s) => `<option value="${escapeAttr(s)}">${escapeHtml(s)}</option>`).join("");
    statusSel.dataset.populated = "1";
  }

  const labelSel = document.getElementById("filter-label");
  const prev = labelSel.value;
  const labels = Array.from(new Set(systems.flatMap((s) => s.labels))).sort();
  labelSel.innerHTML =
    `<option value="">All labels</option>` +
    labels.map((l) => `<option value="${escapeAttr(l)}">${escapeHtml(l)}</option>`).join("");
  if (labels.includes(prev)) labelSel.value = prev;
}

// ----------------------------------------------------------------- systems

function renderSystems() {
  const statusFilter = document.getElementById("filter-status").value;
  const labelFilter = document.getElementById("filter-label").value;
  const sortBy = document.getElementById("sort-systems").value;

  const filtered = allSystems.filter(
    (s) =>
      (!statusFilter || s.status === statusFilter) &&
      (!labelFilter || s.labels.includes(labelFilter))
  );

  const groups = {};
  filtered.forEach((s) => {
    const g = s.grouping || "Ungrouped";
    (groups[g] = groups[g] || []).push(s);
  });

  const sorters = {
    grouping: (a, b) => a.service_name.localeCompare(b.service_name),
    sections_complete: (a, b) => b.sections_complete - a.sections_complete,
    last_session: (a, b) => (b.last_session || "").localeCompare(a.last_session || ""),
  };
  const sorter = sorters[sortBy] || sorters.grouping;

  const groupNames = GROUP_ORDER.filter((g) => groups[g] && groups[g].length);
  // Any grouping not in the canonical list still gets shown, appended at the end.
  Object.keys(groups).forEach((g) => {
    if (!groupNames.includes(g)) groupNames.push(g);
  });

  const container = document.getElementById("systems-groups");
  if (!groupNames.length) {
    container.innerHTML = `<div class="empty-note">No systems match these filters.</div>`;
    return;
  }

  container.innerHTML = groupNames
    .map((g) => {
      const items = groups[g].slice().sort(sorter);
      return `
      <details class="group" open>
        <summary>${escapeHtml(g)} <span class="count">(${items.length})</span></summary>
        <div class="card-list">${items.map(systemCard).join("")}</div>
      </details>`;
    })
    .join("");

  attachSystemCardHandlers();
}

function systemCard(s) {
  const segs = SECTION_KEYS.map((k) => {
    const st = s.section_status[k] || "not_started";
    return `<span class="seg seg-${st}" title="${escapeAttr(SECTION_LABELS[k])}: ${st.replace("_", " ")}"></span>`;
  }).join("");
  const tags = s.labels.map((l) => `<span class="tag">${escapeHtml(l)}</span>`).join("");
  const sectionRows = SECTION_KEYS.map((k) => {
    const st = s.section_status[k] || "not_started";
    return `
      <div class="section-row">
        <span>${escapeHtml(SECTION_LABELS[k])}</span>
        <span class="seg-status seg-status-${st}">${st.replace("_", " ")}</span>
      </div>`;
  }).join("");

  return `
  <div class="card system-card">
    <div class="card-top" data-toggle>
      <div>
        <div class="card-title">${escapeHtml(s.service_name)}</div>
        <div class="seg-bar">${segs}</div>
        <div class="card-meta">
          ${tags}
          <span>Last session: ${s.last_session || "never"}</span>
        </div>
      </div>
      <span class="badge ${statusClass(s.status)}">${escapeHtml(s.status)}</span>
    </div>
    <div class="card-expand hidden">
      <div class="section-list">${sectionRows}</div>
      <button class="btn btn-sm btn-ghost" data-file="${escapeAttr(s.file_path)}">Open file</button>
    </div>
  </div>`;
}

function attachSystemCardHandlers() {
  document.querySelectorAll(".system-card [data-toggle]").forEach((top) => {
    top.addEventListener("click", () => {
      top.parentElement.querySelector(".card-expand").classList.toggle("hidden");
    });
  });
  document.querySelectorAll(".system-card [data-file]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const path = btn.dataset.file;
      navigator.clipboard?.writeText(path).catch(() => {});
      const original = btn.textContent;
      btn.textContent = `Copied: ${path}`;
      setTimeout(() => {
        btn.textContent = original;
      }, 1500);
    });
  });
}

// ---------------------------------------------------------------- concepts

function renderConcepts() {
  const sortBy = document.getElementById("sort-concepts").value;

  const lastSessionByService = {};
  allSystems.forEach((s) => {
    if (s.last_session) lastSessionByService[s.service_name] = s.last_session;
  });

  const sorters = {
    freshness: (a, b) =>
      (a.freshness === "Check recommended" ? 0 : 1) - (b.freshness === "Check recommended" ? 0 : 1) ||
      a.concept_name.localeCompare(b.concept_name),
    last_reviewed: (a, b) => (a.last_reviewed || "").localeCompare(b.last_reviewed || ""),
    concept_name: (a, b) => a.concept_name.localeCompare(b.concept_name),
  };
  const items = allConcepts.slice().sort(sorters[sortBy] || sorters.freshness);

  const el = document.getElementById("concepts-list");
  if (!items.length) {
    el.innerHTML = `<div class="empty-note">No concepts yet.</div>`;
    return;
  }

  el.innerHTML = items
    .map((c) => {
      const needsReview =
        c.freshness === "Check recommended" &&
        c.linked_systems.some((name) => {
          const last = lastSessionByService[name];
          return last && (!c.last_reviewed || last > c.last_reviewed);
        });
      const freshBadgeClass = c.freshness === "Fresh" ? "badge-fresh" : "badge-stale";
      const tags =
        c.linked_systems.map((n) => `<span class="tag">${escapeHtml(n)}</span>`).join("") ||
        `<span class="tag">none linked</span>`;

      return `
      <div class="card concept-card ${needsReview ? "needs-review" : ""}">
        <div class="card-top">
          <div>
            <div class="card-title">${escapeHtml(c.concept_name)}</div>
            <div class="card-meta">
              ${tags}
              <span>Last reviewed: ${c.last_reviewed || "never"}</span>
            </div>
          </div>
          <span class="badge ${freshBadgeClass}">${escapeHtml(c.freshness)}</span>
        </div>
      </div>`;
    })
    .join("");
}

// ---------------------------------------------------------------- sessions

function renderSessions(sessions) {
  const el = document.getElementById("sessions-list");
  if (!sessions || !sessions.length) {
    el.innerHTML = `<div class="empty-note">No sessions logged yet.</div>`;
    return;
  }
  el.innerHTML = sessions
    .map(
      (s) => `
    <div class="session-row">
      <div class="session-top">
        <span class="session-date">${escapeHtml(s.session_date)}</span>
        <span class="badge badge-mode">${escapeHtml(s.mode)}</span>
      </div>
      <div class="session-name">${escapeHtml(s.entry_name)}</div>
      ${s.notes ? `<div class="session-notes">${escapeHtml(s.notes)}</div>` : ""}
    </div>`
    )
    .join("");
}

// ----------------------------------------------------------------- util

function statusClass(status) {
  return "status-" + slug(status);
}

function slug(text) {
  return String(text ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s);
}
