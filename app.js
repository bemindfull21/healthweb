"use strict";

const LS_KEY = "healthweb.profile";
// 실시간 조회 API (VM). 빈 문자열이면 새로고침 버튼 숨김
const LIVE_API = "https://healthweb21.duckdns.org";
const $ = (id) => document.getElementById(id);

let chart = null;
let allEntries = [];
let profile = null; // { uid, target }
let lastRefresh = 0;
let bannerTimer = null;

// ---------- 유틸 ----------

async function sha256Hex(str) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function loadProfile() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || "null");
  } catch {
    return null;
  }
}
function saveProfile(p) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(p));
  } catch {}
}
function clearProfile() {
  try {
    localStorage.removeItem(LS_KEY);
  } catch {}
}

const fmtKg = (n) => (Math.round(n * 10) / 10).toFixed(1);

// ---------- 데이터 로드 ----------

// 정적 스냅샷(Pages CDN, 빠름) 우선. 없으면(404) 라이브 API로 폴백 —
// 배치가 아직 안 돈 신규 사용자도 바로 조회되게.
async function fetchUserData(uid) {
  const hash = await sha256Hex(String(uid).trim());
  const res = await fetch(`./data/users/${hash}.json`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`데이터를 불러오지 못했습니다 (${res.status})`);
  return res.json();
}

async function fetchLive(uid) {
  const res = await fetch(`${LIVE_API}/weights?uid=${encodeURIComponent(String(uid).trim())}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(res.status === 429 ? "요청이 많습니다. 잠시 후 다시" : `조회 실패 (${res.status})`);
  }
  return res.json();
}

async function loadUserData(uid) {
  const staticData = await fetchUserData(uid);
  if (staticData) return staticData;
  if (LIVE_API) {
    try {
      const data = await fetchLive(uid);
      lastRefresh = Date.now();
      return data;
    } catch {
      /* 라이브도 실패하면 아래에서 null */
    }
  }
  return null;
}

// 새로고침: VM API에서 실시간 조회. 실패해도 화면의 마지막 갱신본은 유지.
// silent=true 는 페이지 진입 시 자동 갱신용 — 배너/쿨다운 안내를 띄우지 않는다.
async function refreshNow(silent = false) {
  if (!LIVE_API || !profile?.uid) return;
  const now = Date.now();
  if (now - lastRefresh < 10000) {
    // 진입 시 자동 갱신이 이미 돌았으므로, 직후 수동 클릭은 "최신"으로 안내
    if (!silent) banner("이미 최신 데이터입니다", "ok");
    return;
  }
  const btn = $("refresh");
  btn.disabled = true;
  btn.classList.add("spin");
  try {
    const data = await fetchLive(profile.uid);
    lastRefresh = now;
    showDashboard(data);
    if (!silent) banner("실시간 데이터로 갱신되었습니다", "ok");
  } catch (e) {
    if (!silent) banner(`${e.message || "조회 실패"} · 마지막 갱신본을 표시합니다`, "warn");
  } finally {
    btn.disabled = false;
    btn.classList.remove("spin");
  }
}

function banner(msg, kind) {
  const el = $("banner");
  el.textContent = msg;
  el.className = "banner" + (kind ? " " + kind : "");
  el.hidden = false;
  clearTimeout(bannerTimer);
  if (kind === "ok") bannerTimer = setTimeout(() => (el.hidden = true), 4000);
}

// ---------- 화면 전환 ----------

function showRegister(errMsg) {
  $("dashboard").hidden = true;
  $("register").hidden = false;
  $("banner").hidden = true;
  const e = $("register-error");
  if (errMsg) {
    e.textContent = errMsg;
    e.hidden = false;
  } else {
    e.hidden = true;
  }
}

function showDashboard(data) {
  $("register").hidden = true;
  $("dashboard").hidden = false;
  $("refresh").hidden = !LIVE_API;
  allEntries = (data.entries || []).slice().sort((a, b) => key(a).localeCompare(key(b)));
  $("updated").textContent = fmtUpdated(data.updated_at);
  renderStats();
  applyRange(currentDays());
  renderTable();
}

const key = (e) => `${e.date} ${e.time}`;

function fmtUpdated(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

// ---------- 통계 ----------

function renderStats() {
  const box = $("stats");
  box.innerHTML = "";
  if (!allEntries.length) {
    box.innerHTML = `<div class="stat"><div class="k">기록</div><div class="v">0건</div></div>`;
    return;
  }
  const last = allEntries[allEntries.length - 1];
  const first = allEntries[0];
  const cards = [
    { k: "최근 몸무게", v: `${fmtKg(last.weight)} <small>kg</small>` },
    {
      k: "시작 대비",
      v: signed(last.weight - first.weight),
    },
    { k: "기록 수", v: `${allEntries.length}건` },
  ];
  if (profile?.target) {
    const diff = last.weight - profile.target;
    cards.splice(1, 0, {
      k: "목표까지",
      v:
        Math.abs(diff) < 0.05
          ? "달성 🎉"
          : `${fmtKg(Math.abs(diff))} <small>kg ${diff > 0 ? "감량" : "증량"}</small>`,
    });
  }
  for (const c of cards) {
    const el = document.createElement("div");
    el.className = "stat";
    el.innerHTML = `<div class="k">${c.k}</div><div class="v">${c.v}</div>`;
    box.appendChild(el);
  }
}

function signed(delta) {
  const s = fmtKg(Math.abs(delta));
  if (Math.abs(delta) < 0.05) return `±0 <small>kg</small>`;
  const cls = delta > 0 ? "delta-up" : "delta-down";
  return `<span class="${cls}">${delta > 0 ? "+" : "−"}${s}</span> <small>kg</small>`;
}

// ---------- 차트 ----------

function currentDays() {
  const on = document.querySelector("#range button.on");
  return on ? Number(on.dataset.days) : 30;
}

function applyRange(days) {
  document
    .querySelectorAll("#range button")
    .forEach((b) => b.classList.toggle("on", Number(b.dataset.days) === days));

  let rows = allEntries;
  if (days > 0 && allEntries.length) {
    // 오늘이 아니라 "가장 최근 기록"을 기준으로 N일 (수집이 잠시 멈춰도 최근 구간이 보이게)
    const last = new Date(allEntries[allEntries.length - 1].date + "T00:00:00Z");
    last.setUTCDate(last.getUTCDate() - days + 1);
    const cut = last.toISOString().slice(0, 10);
    rows = allEntries.filter((e) => e.date >= cut);
  }
  renderChart(rows);
}

function renderChart(rows) {
  const labels = rows.map((e) => (sameDayDup(rows, e) ? `${e.date} ${e.time.slice(0, 5)}` : e.date));
  const data = rows.map((e) => e.weight);
  const ma = movingAvg(data, 7);

  const ds = [
    {
      label: "몸무게",
      data,
      borderColor: cssVar("--accent"),
      backgroundColor: cssVar("--accent-soft"),
      pointRadius: rows.length > 60 ? 0 : 3,
      tension: 0.25,
      fill: true,
    },
    {
      label: "7일 이동평균",
      data: ma,
      borderColor: cssVar("--muted"),
      borderDash: [5, 4],
      pointRadius: 0,
      tension: 0.25,
    },
  ];
  if (profile?.target) {
    ds.push({
      label: "목표",
      data: data.map(() => profile.target),
      borderColor: cssVar("--down"),
      borderDash: [2, 3],
      pointRadius: 0,
      borderWidth: 1.5,
    });
  }

  if (chart) chart.destroy();
  chart = new Chart($("chart"), {
    type: "line",
    data: { labels, datasets: ds },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { boxWidth: 12, color: cssVar("--muted") } } },
      scales: {
        x: { ticks: { color: cssVar("--muted"), maxRotation: 0, autoSkipPadding: 20 }, grid: { display: false } },
        y: { ticks: { color: cssVar("--muted") }, grid: { color: cssVar("--border") } },
      },
    },
  });
}

function sameDayDup(rows, e) {
  return rows.filter((r) => r.date === e.date).length > 1;
}
function movingAvg(arr, n) {
  return arr.map((_, i) => {
    const s = Math.max(0, i - n + 1);
    const w = arr.slice(s, i + 1);
    return w.reduce((a, b) => a + b, 0) / w.length;
  });
}
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ---------- 테이블 ----------

function renderTable() {
  const tb = document.querySelector("#log tbody");
  tb.innerHTML = "";
  const rows = allEntries.slice().reverse(); // 최신순
  rows.forEach((e, i) => {
    const prev = rows[i + 1];
    const delta = prev ? e.weight - prev.weight : null;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${e.date} ${e.time.slice(0, 5)}</td>
      <td>${fmtKg(e.weight)} kg</td>
      <td>${delta === null ? "-" : deltaCell(delta)}</td>
      <td class="q">${e.quote ? escapeHtml(e.quote) : "-"}</td>`;
    tb.appendChild(tr);
  });
}
function deltaCell(d) {
  if (Math.abs(d) < 0.05) return "±0";
  const cls = d > 0 ? "delta-up" : "delta-down";
  return `<span class="${cls}">${d > 0 ? "+" : "−"}${fmtKg(Math.abs(d))}</span>`;
}
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- 초기화 / 이벤트 ----------

$("register-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const uid = $("uid-input").value.trim();
  const target = parseFloat($("target-input").value);
  if (!/^\d{3,}$/.test(uid)) {
    return showRegister("User ID는 숫자입니다. 봇에게 /whoami 를 보내 확인하세요.");
  }
  const btn = ev.submitter;
  btn.disabled = true;
  btn.textContent = "조회 중…";
  try {
    const data = await loadUserData(uid);
    if (!data) {
      showRegister("해당 ID로 저장된 기록이 없습니다. 헬스봇에 몸무게를 먼저 기록해 보세요.");
      return;
    }
    profile = { uid, target: Number.isFinite(target) ? target : null };
    saveProfile(profile);
    showDashboard(data);
    refreshNow(true);
  } catch (e) {
    showRegister(e.message || "조회에 실패했습니다.");
  } finally {
    btn.disabled = false;
    btn.textContent = "조회";
  }
});

$("refresh").addEventListener("click", () => refreshNow(false));

$("logout").addEventListener("click", () => {
  clearProfile();
  profile = null;
  $("uid-input").value = "";
  $("target-input").value = "";
  showRegister();
});

document.getElementById("range").addEventListener("click", (e) => {
  if (e.target.tagName === "BUTTON") applyRange(Number(e.target.dataset.days));
});

(async function boot() {
  profile = loadProfile();
  if (!profile?.uid) return showRegister();
  try {
    const data = await loadUserData(profile.uid);
    if (!data) return showRegister("저장된 기록을 찾지 못했습니다.");
    showDashboard(data);
    refreshNow(true); // 정적으로 즉시 그린 뒤 백그라운드로 실시간 갱신
  } catch (e) {
    showRegister(e.message || "조회에 실패했습니다.");
  }
})();
