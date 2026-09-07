"use strict";
// config.js 제공: API, TOKEN_KEY, ME_KEY

const $ = (id) => document.getElementById(id);

let chart = null;
let allEntries = [];
let me = null; // { email, tg_user_id, verified, target_weight, link_code? }
let currentUpdatedAt = null;
let relTimer = null;
let bannerTimer = null;
let lastRefresh = 0;

// ---------- 세션 ----------

function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}
function endSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ME_KEY);
  } catch {}
}
function toLanding() {
  location.replace("./index.html");
}

// 401 이면 세션 정리 후 랜딩으로. 그 외 응답은 그대로 반환.
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    cache: "no-store",
    headers: { Authorization: "Bearer " + getToken(), ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    endSession();
    toLanding();
    throw new Error("unauthorized");
  }
  return res;
}

// ---------- 정적 폴백 ----------

async function sha256Hex(str) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function fetchStatic(uid) {
  try {
    const hash = await sha256Hex(String(uid).trim());
    const res = await fetch(`./data/users/${hash}.json`, { cache: "no-store" });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

// ---------- 부팅 ----------

(async function boot() {
  if (!getToken()) return toLanding();

  try {
    me = JSON.parse(localStorage.getItem(ME_KEY) || "null");
  } catch {}

  try {
    const res = await api("/auth/me");
    if (res.ok) {
      me = await res.json();
      try {
        localStorage.setItem(ME_KEY, JSON.stringify(me));
      } catch {}
    }
  } catch (e) {
    if (e.message === "unauthorized") return;
    // API 다운 — 캐시된 me 로 진행
  }

  if (!me) {
    // 토큰은 있는데 계정 정보를 못 얻음 (첫 방문 + API 다운)
    showStale();
    return;
  }

  $("account").textContent = me.email || "";

  if (!me.verified) return showVerifyGate(me.link_code);
  await loadWeights();
})();

// ---------- 텔레그램 인증 게이트 ----------

function showVerifyGate(code) {
  $("dashboard").hidden = true;
  $("empty").hidden = true;
  $("verify-gate").hidden = false;
  $("refresh").hidden = true;
  $("verify-cmd").textContent = code ? `/link ${code}` : "/link (코드 불러오는 중…)";
  if (!code) refreshLinkCode();
}

async function refreshLinkCode() {
  try {
    const res = await api("/auth/me");
    if (res.ok) {
      me = await res.json();
      try {
        localStorage.setItem(ME_KEY, JSON.stringify(me));
      } catch {}
      if (me.link_code) $("verify-cmd").textContent = `/link ${me.link_code}`;
    }
  } catch {}
}

$("verify-recheck").addEventListener("click", async () => {
  const btn = $("verify-recheck");
  const m = $("verify-msg");
  btn.disabled = true;
  try {
    const res = await api("/auth/me");
    if (res.ok) {
      me = await res.json();
      try {
        localStorage.setItem(ME_KEY, JSON.stringify(me));
      } catch {}
      if (me.verified) {
        m.hidden = true;
        $("verify-gate").hidden = true;
        await loadWeights();
        return;
      }
      if (me.link_code) $("verify-cmd").textContent = `/link ${me.link_code}`;
      m.textContent = "아직 인증 전이에요. 헬스봇에게 명령을 보낸 뒤 다시 눌러 주세요.";
      m.className = "form-msg";
      m.hidden = false;
    }
  } catch (e) {
    if (e.message !== "unauthorized") {
      m.textContent = "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.";
      m.className = "form-msg err";
      m.hidden = false;
    }
  } finally {
    btn.disabled = false;
  }
});

// ---------- 데이터 로드 ----------

async function loadWeights() {
  $("verify-gate").hidden = true;
  try {
    const res = await api("/weights");
    if (res.status === 403) return showVerifyGate(me && me.link_code);
    if (!res.ok) throw new Error(`조회 실패 (${res.status})`);
    const data = await res.json();
    lastRefresh = Date.now();
    renderDashboard(data);
    hideStale();
  } catch (e) {
    if (e.message === "unauthorized") return;
    const uid = me && me.tg_user_id;
    const snap = uid ? await fetchStatic(uid) : null;
    if (snap) {
      renderDashboard(snap);
      showStale();
    } else {
      $("dashboard").hidden = false;
      showStale();
    }
  }
}

// 새로고침: /weights 재조회. silent=true 는 배너 없이(진입 자동).
async function refreshNow(silent = false) {
  if (!me || !me.verified) return;
  const now = Date.now();
  if (now - lastRefresh < 10000) {
    if (!silent) banner("이미 최신 데이터입니다", "ok");
    return;
  }
  const btn = $("refresh");
  btn.disabled = true;
  btn.classList.add("spin");
  try {
    const res = await api("/weights");
    if (!res.ok) throw new Error(res.status === 429 ? "요청이 많습니다. 잠시 후 다시" : `조회 실패 (${res.status})`);
    const data = await res.json();
    lastRefresh = now;
    renderDashboard(data);
    hideStale();
    if (!silent) banner("실시간 데이터로 갱신되었습니다", "ok");
  } catch (e) {
    if (e.message === "unauthorized") return;
    if (/429|요청이 많/.test(e.message || "")) {
      if (!silent) banner("요청이 많습니다 · 잠시 후 다시 시도해 주세요", "warn");
    } else {
      showStale();
      if (!silent) banner("실시간 연결에 실패했습니다 · 마지막 갱신본을 표시합니다", "warn");
    }
  } finally {
    btn.disabled = false;
    btn.classList.remove("spin");
  }
}

$("refresh").addEventListener("click", () => refreshNow(false));
$("staleness-retry").addEventListener("click", () => refreshNow(false));
$("logout").addEventListener("click", () => {
  endSession();
  toLanding();
});

// ---------- 렌더 ----------

function renderDashboard(data) {
  $("verify-gate").hidden = true;
  allEntries = (data.entries || []).slice().sort((a, b) => key(a).localeCompare(key(b)));
  currentUpdatedAt = data.updated_at || null;

  if (!allEntries.length) {
    $("dashboard").hidden = true;
    $("empty").hidden = false;
    $("refresh").hidden = false;
    return;
  }
  $("empty").hidden = true;
  $("dashboard").hidden = false;
  $("refresh").hidden = false;

  $("updated").textContent = relTime(currentUpdatedAt);
  $("updated").title = fmtUpdated(currentUpdatedAt);
  startRelTimer();
  renderStats();
  applyRange(currentDays());
  renderTable();
}

const key = (e) => `${e.date} ${e.time}`;
const fmtKg = (n) => (Math.round(n * 10) / 10).toFixed(1);
const targetWeight = () => (me && typeof me.target_weight === "number" ? me.target_weight : null);

function fmtUpdated(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

// ---------- 실시간 연결 상태 ----------

function relTime(iso) {
  if (!iso) return "알 수 없음";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "알 수 없음";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "방금";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return `${Math.floor(s / 86400)}일 전`;
}
const staleText = () => `실시간 연결 안 됨 · 마지막 갱신 ${relTime(currentUpdatedAt)}`;
function showStale() {
  $("staleness-text").textContent = staleText();
  $("staleness").hidden = false;
}
function hideStale() {
  $("staleness").hidden = true;
}
function startRelTimer() {
  clearInterval(relTimer);
  relTimer = setInterval(() => {
    $("updated").textContent = relTime(currentUpdatedAt);
    if (!$("staleness").hidden) $("staleness-text").textContent = staleText();
  }, 60000);
}

function banner(text, kind) {
  const el = $("banner");
  el.textContent = text;
  el.className = "banner" + (kind ? " " + kind : "");
  el.hidden = false;
  clearTimeout(bannerTimer);
  if (kind === "ok") bannerTimer = setTimeout(() => (el.hidden = true), 4000);
}

// ---------- 통계 ----------

function renderStats() {
  const box = $("stats");
  box.innerHTML = "";
  if (!allEntries.length) return;
  const last = allEntries[allEntries.length - 1];
  const first = allEntries[0];
  const cards = [
    { k: "최근 몸무게", v: `${fmtKg(last.weight)} <small>kg</small>` },
    { k: "시작 대비", v: signed(last.weight - first.weight) },
    { k: "기록 수", v: `${allEntries.length}건` },
  ];
  const tw = targetWeight();
  if (tw) {
    const diff = last.weight - tw;
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
  const tw = targetWeight();
  if (tw) {
    ds.push({
      label: "목표",
      data: data.map(() => tw),
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

document.getElementById("range").addEventListener("click", (e) => {
  if (e.target.tagName === "BUTTON") applyRange(Number(e.target.dataset.days));
});

// ---------- 테이블 ----------

function renderTable() {
  const tb = document.querySelector("#log tbody");
  tb.innerHTML = "";
  const rows = allEntries.slice().reverse();
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
