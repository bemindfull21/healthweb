import { h, render, createContext } from "https://esm.sh/preact@10.24.3";
import { useState, useEffect, useRef, useCallback, useContext } from "https://esm.sh/preact@10.24.3/hooks";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(h);

// ---------- 설정 ----------
const API = "https://healthweb21.duckdns.org";
const TOKEN_KEY = "healthweb.token";
const ME_KEY = "healthweb.me";
const BASE = new URL(".", import.meta.url).pathname.replace(/\/$/, "");

const KIND_LABEL = { brag: "자랑", resolve: "도전", reflect: "성찰", casual: "그냥" };

// ---------- 딥링크 복원 ----------
try {
  const r = sessionStorage.getItem("spa_redirect");
  if (r) { sessionStorage.removeItem("spa_redirect"); history.replaceState(null, "", r); }
} catch {}

// ---------- 세션 ----------
const token = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
function logout() {
  try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(ME_KEY); } catch {}
  location.replace(BASE + "/");
}

// ---------- API ----------
async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(API + path, {
      method,
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token() },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw { status: 0, detail: "서버에 연결하지 못했습니다" };
  }
  if (res.status === 401) { logout(); throw { status: 401, detail: "세션 만료" }; }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, detail: data.detail || "오류가 발생했습니다" };
  return data;
}

// ---------- 유틸 ----------
const fmtKg = (n) => (Math.round(n * 10) / 10).toFixed(1);
function relTime(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "방금";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}
function streakOf(entries) {
  if (!entries.length) return 0;
  const days = new Set(entries.map((e) => e.date));
  let cur = new Date(entries[entries.length - 1].date + "T00:00:00Z");
  let n = 0;
  while (days.has(cur.toISOString().slice(0, 10))) { n++; cur.setUTCDate(cur.getUTCDate() - 1); }
  return n;
}
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function movingAvg(arr, w) {
  return arr.map((_, i) => {
    const s = arr.slice(Math.max(0, i - w + 1), i + 1);
    return s.reduce((a, b) => a + b, 0) / s.length;
  });
}
function nowLocalInput() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}
function resizeImage(file, maxDim) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(img.src);
      let { width, height } = img;
      const scale = Math.min(1, maxDim / Math.max(width, height));
      width = Math.max(1, Math.round(width * scale));
      height = Math.max(1, Math.round(height * scale));
      const c = document.createElement("canvas");
      c.width = width; c.height = height;
      c.getContext("2d").drawImage(img, 0, 0, width, height);
      c.toBlob((b) => (b ? resolve(b) : reject(new Error("이미지 변환 실패"))), "image/jpeg", 0.85);
    };
    img.onerror = () => reject(new Error("이미지를 읽을 수 없습니다"));
    img.src = URL.createObjectURL(file);
  });
}

// ---------- 전역 스토어 ----------
const Store = createContext(null);
const useStore = () => useContext(Store);

// ---------- 라우터 ----------
function useRoute() {
  const [path, setPath] = useState(location.pathname);
  useEffect(() => {
    const on = () => setPath(location.pathname);
    addEventListener("popstate", on);
    return () => removeEventListener("popstate", on);
  }, []);
  const nav = useCallback((to) => {
    history.pushState(null, "", BASE + to);
    setPath(location.pathname);
    scrollTo(0, 0);
  }, []);
  let route = (path.slice(BASE.length) || "/").replace(/\/+$/, "") || "/";
  if (route === "/" || route === "/app.html" || route === "/404.html") route = "/feed";
  return { route, nav };
}

// ---------- 공통 컴포넌트 ----------
function Toast() {
  const { toastData } = useStore();
  if (!toastData) return null;
  return html`<div class=${"toast " + (toastData.kind || "")}>${toastData.text}</div>`;
}

function TopBar({ title, onBack }) {
  const { route, nav } = useStore();
  return html`<header class="topbar">
    ${onBack && html`<button class="icon-btn" onClick=${onBack} aria-label="뒤로">‹</button>`}
    <span class="topbar-title">${title}</span>
    ${route !== "/search" &&
      html`<button class="icon-btn" onClick=${() => nav("/search")} aria-label="검색">🔍</button>`}
  </header>`;
}

function TabBar() {
  const { route, nav, openSheet, bump, unread } = useStore();
  const on = (r) =>
    route === r ||
    (r === "/feed" && route.startsWith("/p/")) ||
    (r === "/challenges" && route.startsWith("/challenges"));
  const go = (r) => () => (route === r ? bump() : nav(r)); // 현재 탭 다시 누르면 새로고침
  return html`<nav class="tabbar tabbar-5">
    <button class=${on("/feed") ? "on" : ""} onClick=${go("/feed")}>피드</button>
    <button class=${on("/challenges") ? "on" : ""} onClick=${go("/challenges")}>챌린지</button>
    <button class="plus" onClick=${openSheet} aria-label="추가">＋</button>
    <button class=${route === "/notifications" ? "on" : ""} onClick=${go("/notifications")}>
      알림${unread > 0 && html`<span class="badge">${unread > 9 ? "9+" : unread}</span>`}
    </button>
    <button class=${route === "/me" ? "on" : ""} onClick=${go("/me")}>나</button>
  </nav>`;
}

function KindBadge({ kind }) {
  return html`<span class=${"kind kind-" + kind}>${KIND_LABEL[kind] || kind}</span>`;
}

const RANK_NAME = { 1: "흑연", 2: "흑요석", 3: "자수정", 4: "사파이어", 5: "다이아몬드" };
function RankBadge({ level }) {
  if (!level) return null;
  return html`<span class=${"rank-badge rank-" + level}>${RANK_NAME[level]}</span>`;
}

function EncourageBtn({ post, big }) {
  const [on, setOn] = useState(post.i_encouraged);
  const [count, setCount] = useState(post.encourage_count);
  const [busy, setBusy] = useState(false);
  const toggle = async (e) => {
    e.stopPropagation();
    if (busy) return;
    const next = !on;
    setOn(next); setCount((c) => c + (next ? 1 : -1)); setBusy(true);
    try {
      await api(`/posts/${post.id}/encourage`, { method: next ? "POST" : "DELETE" });
    } catch {
      setOn(!next); setCount((c) => c + (next ? -1 : 1));
    } finally { setBusy(false); }
  };
  return html`<button class=${"encourage" + (on ? " on" : "") + (big ? " big" : "")} onClick=${toggle}>
    ♥ 응원 ${count > 0 ? count : ""}
  </button>`;
}

function PostCard({ post }) {
  const { nav } = useStore();
  const goUser = (e) => { e.stopPropagation(); nav(`/u/${encodeURIComponent(post.name)}`); };
  return html`<article class="post-card" onClick=${() => nav(`/p/${post.id}`)}>
    <div class="post-head">
      <button class="pc-user" onClick=${goUser}>
        <${Avatar} src=${post.avatar && post.avatar.thumb_url} name=${post.name} size="sm" />
        <span class="handle">${post.name}</span>
        <${RankBadge} level=${post.rank_level} />
      </button>
      <${KindBadge} kind=${post.kind} />
      <span class="post-time">${relTime(post.created_at)}</span>
    </div>
    <p class="post-body">${post.body}</p>
    ${post.image && html`<img class="post-img" src=${post.image.thumb_url || post.image.url} alt="" loading="lazy" />`}
    ${post.weight != null &&
      html`<div class="post-weight">${fmtKg(post.weight)} kg</div>`}
    <div class="post-actions">
      <${EncourageBtn} post=${post} />
      <span class="cmt">💬 ${post.comment_count || ""}</span>
    </div>
  </article>`;
}

function Spinner() { return html`<div class="spinner">불러오는 중…</div>`; }
function ErrorBox({ msg, onRetry }) {
  return html`<div class="errbox"><p>${msg || "문제가 발생했습니다"}</p>
    ${onRetry && html`<button onClick=${onRetry}>다시 시도</button>`}</div>`;
}

// ---------- 차트 ----------
function WeightChart({ entries, target }) {
  const canvas = useRef(null);
  const chart = useRef(null);
  const [days, setDays] = useState(30);

  useEffect(() => {
    if (!canvas.current || !window.Chart) return;
    let rows = entries;
    if (days > 0 && entries.length) {
      const last = new Date(entries[entries.length - 1].date + "T00:00:00Z");
      last.setUTCDate(last.getUTCDate() - days + 1);
      const cut = last.toISOString().slice(0, 10);
      rows = entries.filter((e) => e.date >= cut);
    }
    const sameDay = (d) => rows.filter((r) => r.date === d).length > 1;
    const labels = rows.map((e) => (sameDay(e.date) ? `${e.date.slice(5)} ${e.time.slice(0, 5)}` : e.date));
    const data = rows.map((e) => e.weight);
    const ds = [
      { label: "몸무게", data, borderColor: cssVar("--accent"), backgroundColor: cssVar("--accent-soft"),
        pointRadius: rows.length > 60 ? 0 : 3, tension: 0.25, fill: true },
      { label: "7일 평균", data: movingAvg(data, 7), borderColor: cssVar("--muted"),
        borderDash: [5, 4], pointRadius: 0, tension: 0.25 },
    ];
    if (target) ds.push({ label: "목표", data: data.map(() => target), borderColor: cssVar("--down"),
      borderDash: [2, 3], pointRadius: 0, borderWidth: 1.5 });

    chart.current?.destroy();
    chart.current = new window.Chart(canvas.current, {
      type: "line",
      data: { labels, datasets: ds },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { boxWidth: 12, color: cssVar("--muted") } } },
        scales: {
          x: { ticks: { color: cssVar("--muted"), maxRotation: 0, autoSkipPadding: 20 }, grid: { display: false } },
          y: { ticks: { color: cssVar("--muted") }, grid: { color: cssVar("--border") } },
        },
      },
    });
    return () => chart.current?.destroy();
  }, [entries, target, days]);

  return html`<div class="panel">
    <div class="panel-head"><span>추이</span>
      <div class="range">
        ${[7, 30, 90, 0].map((d) => html`<button key=${d} class=${d === days ? "on" : ""}
          onClick=${() => setDays(d)}>${d ? d + "일" : "전체"}</button>`)}
      </div>
    </div>
    <div class="chart-box"><canvas ref=${canvas}></canvas></div>
  </div>`;
}

// ---------- 미니 스파크라인 (프로필 추이) ----------
function Sparkline({ data }) {
  const w = 280, h = 46, pad = 3;
  const lo = Math.min(...data), hi = Math.max(...data);
  const span = hi - lo || 1;
  const pts = data
    .map((v, i) => {
      const x = pad + (i / (data.length - 1)) * (w - pad * 2);
      const y = pad + (1 - (v - lo) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return html`<div class="sparkline">
    <svg viewBox=${`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="최근 몸무게 추이">
      <polyline points=${pts} fill="none" stroke="var(--accent)" stroke-width="1.5"
        vector-effect="non-scaling-stroke" />
    </svg>
    <span class="spark-range">${fmtKg(data[0])} → ${fmtKg(data[data.length - 1])} kg</span>
  </div>`;
}

// ---------- 아바타 · 이미지 ----------
function Avatar({ src, name, size }) {
  const cls = "avatar" + (size ? " " + size : "");
  return src
    ? html`<img class=${cls} src=${src} alt=${name || ""} loading="lazy" />`
    : html`<div class=${cls}>${(name || "?")[0].toUpperCase()}</div>`;
}

function ImageUpload({ kind, value, onChange, label = "사진 추가", compact }) {
  const { toast } = useStore();
  const [busy, setBusy] = useState(false);
  const inp = useRef(null);
  const pick = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return toast("JPEG · PNG · WebP만 올릴 수 있어요", "err");
    setBusy(true);
    try {
      const blob = await resizeImage(file, kind === "avatar" ? 800 : 1600);
      const fd = new FormData();
      fd.append("file", blob, "upload.jpg");
      fd.append("kind", kind);
      const res = await fetch(API + "/media", {
        method: "POST", headers: { Authorization: "Bearer " + token() }, body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "업로드에 실패했어요");
      onChange(data);
    } catch (err) { toast(err.message, "err"); }
    finally { setBusy(false); }
  };
  if (compact) {
    return html`<div class="img-upload compact">
      <button type="button" class="iu-btn" disabled=${busy} onClick=${() => inp.current.click()}>
        ${busy ? "올리는 중…" : (value ? "변경" : "📷 " + label)}
      </button>
      ${value && html`<button type="button" class="iu-rm" onClick=${() => onChange(null)}>제거</button>`}
      <input ref=${inp} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange=${pick} />
    </div>`;
  }
  return html`<div class="img-upload">
    ${value
      ? html`<div class="iu-preview">
          <img src=${value.thumb_url || value.url} alt="" />
          <button type="button" class="iu-x" onClick=${() => onChange(null)} aria-label="사진 제거">✕</button>
        </div>`
      : html`<button type="button" class="iu-btn" disabled=${busy} onClick=${() => inp.current.click()}>
          ${busy ? "올리는 중…" : "📷 " + label}
        </button>`}
    <input ref=${inp} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange=${pick} />
  </div>`;
}

function Lightbox({ src, onClose }) {
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [onClose]);
  return html`<div class="lightbox" onClick=${onClose}>
    <img src=${src} alt="" onClick=${(e) => e.stopPropagation()} />
  </div>`;
}

// ---------- 뷰: 검색 ----------
function SearchView() {
  const { nav } = useStore();
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [state, setState] = useState("idle"); // idle | loading | ok | err
  const timer = useRef(null);

  useEffect(() => {
    clearTimeout(timer.current);
    const term = q.trim();
    if (term.length < 2) { setRes(null); setState("idle"); return; }
    setState("loading");
    timer.current = setTimeout(() => {
      api(`/search?q=${encodeURIComponent(term)}`)
        .then((d) => { setRes(d); setState("ok"); })
        .catch(() => setState("err"));
    }, 350);
    return () => clearTimeout(timer.current);
  }, [q]);

  const empty = res && !res.users.length && !res.challenges.length && !res.posts.length;
  return html`<div class="view search">
    <input class="search-input" type="search" autofocus placeholder="사람 · 챌린지 · 글 검색"
      value=${q} onInput=${(e) => setQ(e.target.value)} />
    ${state === "idle" && html`<div class="empty">두 글자 이상 입력해 보세요.</div>`}
    ${state === "loading" && html`<${Spinner} />`}
    ${state === "err" && html`<${ErrorBox} msg="검색에 실패했습니다" />`}
    ${state === "ok" && empty && html`<div class="empty">"${res.q}" 결과가 없어요.</div>`}
    ${state === "ok" && !empty && html`
      ${res.users.length > 0 && html`<section class="sr">
        <h3>사람</h3>
        ${res.users.map((u) => html`<button class="sr-user" key=${u.name}
          onClick=${() => nav(`/u/${encodeURIComponent(u.name)}`)}>
          <div class="avatar sm">${(u.name || "?")[0].toUpperCase()}</div>
          <div class="sr-user-txt">
            <div class="sr-name">${u.name}</div>
            ${u.bio && html`<div class="sr-bio">${u.bio}</div>`}
          </div>
          ${u.i_follow && html`<span class="sr-tag">팔로잉</span>`}
        </button>`)}
      </section>`}
      ${res.challenges.length > 0 && html`<section class="sr">
        <h3>챌린지</h3>
        ${res.challenges.map((c) => html`<button class="sr-row" key=${c.id}
          onClick=${() => nav(`/challenges/${c.id}`)}>
          <span class="sr-name">${c.title}</span>
          <span class="sr-meta">${c.member_count}명${c.i_joined ? " · 참여 중" : ""}</span>
        </button>`)}
      </section>`}
      ${res.posts.length > 0 && html`<section class="sr">
        <h3>글</h3>
        ${res.posts.map((p) => html`<${PostCard} key=${p.id} post=${p} />`)}
      </section>`}
    `}
  </div>`;
}

// ---------- 뷰: 피드 ----------
function FeedView() {
  const { bumpKey, openPost } = useStore();
  const [scope, setScope] = useState(() => {
    try { return localStorage.getItem("healthweb.feedScope") || "following"; } catch { return "following"; }
  });
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(undefined);
  const [state, setState] = useState("loading");

  const load = useCallback(async (cur) => {
    try {
      const d = await api(`/feed?scope=${scope}${cur ? "&cursor=" + cur : ""}`);
      setItems((prev) => (cur ? [...prev, ...d.items] : d.items));
      setCursor(d.next_cursor);
      setState("ok");
    } catch (e) { setState(e.status === 0 ? "neterr" : "err"); }
  }, [scope]);

  useEffect(() => { setState("loading"); load(); }, [bumpKey, load]);

  const pick = (s) => {
    setScope(s);
    try { localStorage.setItem("healthweb.feedScope", s); } catch {}
  };

  const tabs = html`<div class="seg">
    <button class=${scope === "following" ? "on" : ""} onClick=${() => pick("following")}>팔로잉</button>
    <button class=${scope === "all" ? "on" : ""} onClick=${() => pick("all")}>전체</button>
  </div>`;

  if (state === "loading") return html`<div class="view feed">${tabs}<${Spinner} /></div>`;
  if (state !== "ok") return html`<div class="view feed">${tabs}<${ErrorBox} msg=${state === "neterr" ? "서버에 연결하지 못했습니다" : "피드를 불러오지 못했습니다"} onRetry=${() => { setState("loading"); load(); }} /></div>`;

  return html`<div class="view feed">
    ${tabs}
    <button class="write-btn" onClick=${openPost}>＋ 글쓰기</button>
    ${items.length === 0
      ? html`<div class="empty">${scope === "following"
          ? "팔로우한 사람의 글이 없어요. 전체 탭에서 사람을 찾아보세요."
          : "아직 글이 없어요. 첫 기록을 남겨보세요."}</div>`
      : items.map((p) => html`<${PostCard} key=${p.id} post=${p} />`)}
    ${cursor && html`<button class="more" onClick=${() => load(cursor)}>더 보기</button>`}
  </div>`;
}

// ---------- 뷰: 나 ----------
function MeView() {
  const { me, nav, bumpKey, openWeight, toast } = useStore();
  const [data, setData] = useState(null);
  const [state, setState] = useState("loading");
  const [zoom, setZoom] = useState(null);

  const load = useCallback(async () => {
    try { setData(await api("/weights")); setState("ok"); }
    catch (e) { setState(e.status === 0 ? "neterr" : "err"); }
  }, []);
  useEffect(() => { setState("loading"); load(); }, [bumpKey, load]);

  const del = async (id) => {
    if (!confirm("이 기록을 삭제할까요?")) return;
    try { await api(`/weights/${id}`, { method: "DELETE" }); load(); toast("삭제했습니다"); }
    catch (e) { toast(e.detail, "err"); }
  };

  if (state === "loading") return html`<${Spinner} />`;
  if (state !== "ok") return html`<${ErrorBox} msg=${"기록을 불러오지 못했습니다"} onRetry=${load} />`;

  const entries = data.entries;
  const target = me?.target_weight || null;
  const last = entries[entries.length - 1];
  const first = entries[0];

  return html`<div class="view me">
    <div class="me-head">
      <${Avatar} src=${me && me.avatar && me.avatar.url} name=${me && me.name} size="lg" />
      <div class="me-head-id">
        <div class="me-name">${me ? me.name : ""} <${RankBadge} level=${me && me.rank_level} /></div>
        ${me && me.name && html`<button class="link-btn"
          onClick=${() => nav(`/u/${encodeURIComponent(me.name)}`)}>내 프로필 보기</button>`}
      </div>
      <button class="ghost" onClick=${() => nav("/settings")}>설정</button>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">최근 몸무게</div><div class="v">${last ? fmtKg(last.weight) : "–"} <small>kg</small></div></div>
      ${target && last && html`<div class="stat"><div class="k">목표까지</div>
        <div class="v">${Math.abs(last.weight - target) < 0.05 ? "달성 🎉"
          : html`${fmtKg(Math.abs(last.weight - target))} <small>kg ${last.weight > target ? "감량" : "증량"}</small>`}</div></div>`}
      <div class="stat"><div class="k">연속 기록</div><div class="v">${streakOf(entries)} <small>일</small></div></div>
      <div class="stat"><div class="k">기록 수</div><div class="v">${entries.length} <small>건</small></div></div>
      <div class="stat"><div class="k">M 스코어</div><div class="v">${me ? me.rank_score : "–"}</div></div>
      <div class="stat"><div class="k">M 단계</div><div class="v">${me ? me.rank_name : "–"}</div></div>
    </div>

    ${entries.length === 0
      ? html`<div class="empty">첫 몸무게를 기록해 보세요. <button onClick=${openWeight}>＋ 기록</button></div>`
      : html`
        <${WeightChart} entries=${entries} target=${target} />
        <div class="panel">
          <div class="panel-head"><span>기록</span></div>
          <div class="table-scroll"><table><thead><tr><th>일시</th><th>몸무게</th><th>증감</th><th>메모</th><th></th></tr></thead>
          <tbody>${entries.slice().reverse().map((e, i, arr) => {
            const prev = arr[i + 1];
            const d = prev ? e.weight - prev.weight : null;
            return html`<tr key=${e.id}>
              <td>${e.date} ${e.time.slice(0, 5)}</td>
              <td>${fmtKg(e.weight)} kg</td>
              <td class=${d == null || Math.abs(d) < 0.05 ? "" : d > 0 ? "delta-up" : "delta-down"}>${d == null ? "–" : Math.abs(d) < 0.05 ? "±0" : (d > 0 ? "+" : "−") + fmtKg(Math.abs(d))}</td>
              <td class="q">
                ${e.photo && html`<img class="entry-thumb" src=${e.photo.thumb_url || e.photo.url} alt="진행 사진"
                  onClick=${() => setZoom(e.photo.url)} />`}
                ${e.note || (e.photo ? "" : "–")}
              </td>
              <td><button class="row-del" onClick=${() => del(e.id)} aria-label="삭제">✕</button></td>
            </tr>`;
          })}</tbody></table></div>
        </div>`}

    <button class="fab" onClick=${openWeight} aria-label="몸무게 기록">＋</button>
    ${zoom && html`<${Lightbox} src=${zoom} onClose=${() => setZoom(null)} />`}
  </div>`;
}

// ---------- 뷰: 글 상세 ----------
function PostView({ id }) {
  const { me, nav, toast, bump } = useStore();
  const [post, setPost] = useState(null);
  const [state, setState] = useState("loading");
  const [cmt, setCmt] = useState("");
  const [sending, setSending] = useState(false);
  const [menu, setMenu] = useState(false);
  const [zoom, setZoom] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState("");
  const [editKind, setEditKind] = useState("casual");
  const [savingEdit, setSavingEdit] = useState(false);

  const load = useCallback(async () => {
    try { setPost(await api(`/posts/${id}`)); setState("ok"); }
    catch (e) { setState(e.status === 404 ? "gone" : "err"); }
  }, [id]);
  useEffect(() => { setState("loading"); load(); }, [id, load]);

  const submit = async (e) => {
    e.preventDefault();
    const body = cmt.trim();
    if (!body || sending) return;
    setSending(true);
    try { await api(`/posts/${id}/comments`, { method: "POST", body: { body } }); setCmt(""); load(); }
    catch (err) { toast(err.detail, "err"); }
    finally { setSending(false); }
  };
  const delPost = async () => {
    if (!confirm("이 글을 삭제할까요?")) return;
    try { await api(`/posts/${id}`, { method: "DELETE" }); bump(); nav("/feed"); toast("삭제했습니다"); }
    catch (e) { toast(e.detail, "err"); }
  };
  const startEdit = () => { setEditBody(post.body); setEditKind(post.kind); setEditing(true); };
  const saveEdit = async () => {
    const text = editBody.trim();
    if (!text || savingEdit) return;
    setSavingEdit(true);
    try {
      await api(`/posts/${id}`, { method: "PATCH", body: { body: text, kind: editKind } });
      setEditing(false); toast("수정했습니다"); load(); bump();
    } catch (e) { toast(e.detail, "err"); }
    finally { setSavingEdit(false); }
  };
  const togglePin = async () => {
    try {
      await api("/auth/me", { method: "PATCH", body: { pinned_post_id: post.pinned ? 0 : Number(id) } });
      toast(post.pinned ? "고정을 해제했습니다" : "프로필에 고정했습니다");
      load();
    } catch (e) { toast(e.detail, "err"); }
  };
  const report = async () => {
    setMenu(false);
    const reason = prompt("신고 사유를 적어주세요 (선택)");
    if (reason === null) return;
    try {
      await api("/reports", { method: "POST", body: { target_kind: "post", target_id: String(id), reason } });
      toast("신고를 접수했습니다");
    } catch (e) { toast(e.detail, "err"); }
  };

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "gone") return html`<div class="view"><${ErrorBox} msg="삭제되었거나 없는 글입니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" onRetry=${load} /></div>`;

  return html`<div class="view post-detail">
    <div class="post-head">
      <button class="pc-user" onClick=${() => nav(`/u/${encodeURIComponent(post.name)}`)}>
        <${Avatar} src=${post.avatar && post.avatar.thumb_url} name=${post.name} size="sm" />
        <span class="handle">${post.name}</span>
        <${RankBadge} level=${post.rank_level} />
      </button>
      <${KindBadge} kind=${post.kind} />
      <span class="post-time">${relTime(post.created_at)}</span>
      <div class="pd-menu">
        <button class="icon-btn" onClick=${() => setMenu(!menu)} aria-label="더보기">⋯</button>
        ${menu && html`<div class="menu-pop">
          ${post.mine
            ? html`<button class="plain" onClick=${() => { setMenu(false); togglePin(); }}>${post.pinned ? "고정 해제" : "프로필에 고정"}</button>
                   <button class="plain" onClick=${() => { setMenu(false); startEdit(); }}>수정</button>
                   <button onClick=${() => { setMenu(false); delPost(); }}>삭제</button>`
            : html`<button onClick=${report}>신고</button>`}
        </div>`}
      </div>
    </div>
    ${editing
      ? html`<div class="edit-form">
          <div class="chips">
            ${Object.entries(KIND_LABEL).map(([k, l]) => html`<button type="button" key=${k}
              class=${"chip" + (k === editKind ? " on" : "")} onClick=${() => setEditKind(k)}>${l}</button>`)}
          </div>
          <textarea rows="4" value=${editBody} onInput=${(e) => setEditBody(e.target.value)} maxlength="2000" autofocus></textarea>
          <div class="edit-actions">
            <button class="ghost" onClick=${() => setEditing(false)}>취소</button>
            <button disabled=${!editBody.trim() || savingEdit} onClick=${saveEdit}>저장</button>
          </div>
        </div>`
      : html`<p class="post-body full">${post.body}</p>`}
    ${post.image && html`<img class="post-img full" src=${post.image.url} alt=""
      onClick=${() => setZoom(true)} loading="lazy" />`}
    ${post.weight != null && html`<div class="post-weight big">${fmtKg(post.weight)} kg</div>`}
    <div class="post-actions"><${EncourageBtn} post=${post} big=${true} /></div>
    ${zoom && post.image && html`<${Lightbox} src=${post.image.url} onClose=${() => setZoom(false)} />`}

    <div class="comments">
      <h3>댓글 ${post.comments.length || ""}</h3>
      ${post.comments.map((c) => html`<div class="comment" key=${c.id}>
        <button class="pc-user" onClick=${() => nav(`/u/${encodeURIComponent(c.name)}`)}>
          <${Avatar} src=${c.avatar && c.avatar.thumb_url} name=${c.name} size="sm" />
          <span class="handle">${c.name}</span>
        </button>
        <span class="post-time">${relTime(c.created_at)}</span>
        <p>${c.body}</p>
      </div>`)}
      <form class="comment-form" onSubmit=${submit}>
        <input value=${cmt} onInput=${(e) => setCmt(e.target.value)} placeholder="응원의 말을 남겨보세요" maxlength="1000" />
        <button disabled=${!cmt.trim() || sending}>등록</button>
      </form>
    </div>
  </div>`;
}

// ---------- 뷰: 프로필 ----------
function ProfileView({ handle }) {
  const { nav, toast } = useStore();
  const [p, setP] = useState(null);
  const [state, setState] = useState("loading");
  const [following, setFollowing] = useState(false);
  const [followers, setFollowers] = useState(0);
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);

  const load = useCallback(() => {
    setState("loading");
    api(`/u/${encodeURIComponent(handle)}`).then((d) => {
      setP(d); setFollowing(d.i_follow); setFollowers(d.followers || 0); setState("ok");
    }).catch((e) => setState(e.status === 404 ? "gone" : "err"));
  }, [handle]);
  useEffect(() => { load(); }, [handle, load]);

  const toggleFollow = async () => {
    if (busy) return;
    const next = !following;
    setFollowing(next); setFollowers((n) => n + (next ? 1 : -1)); setBusy(true);
    try {
      await api(`/u/${encodeURIComponent(handle)}/follow`, { method: next ? "POST" : "DELETE" });
    } catch (e) {
      setFollowing(!next); setFollowers((n) => n + (next ? -1 : 1)); toast(e.detail, "err");
    } finally { setBusy(false); }
  };
  const block = async () => {
    setMenu(false);
    if (!confirm(`${p.name} 님을 차단할까요? 서로의 글과 활동이 보이지 않게 됩니다.`)) return;
    try { await api(`/u/${encodeURIComponent(handle)}/block`, { method: "POST" }); toast("차단했습니다"); load(); }
    catch (e) { toast(e.detail, "err"); }
  };
  const unblock = async () => {
    try { await api(`/u/${encodeURIComponent(handle)}/block`, { method: "DELETE" }); toast("차단을 해제했습니다"); load(); }
    catch (e) { toast(e.detail, "err"); }
  };
  const report = async () => {
    setMenu(false);
    const reason = prompt("신고 사유를 적어주세요 (선택)");
    if (reason === null) return;
    try {
      await api("/reports", { method: "POST", body: { target_kind: "user", target_id: p.name, reason } });
      toast("신고를 접수했습니다");
    } catch (e) { toast(e.detail, "err"); }
  };

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "gone") return html`<div class="view"><${ErrorBox} msg="없는 사용자입니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" onRetry=${load} /></div>`;

  if (p.blocked_by_me) return html`<div class="view profile">
    <div class="empty">
      <p><b>${p.name}</b> 님을 차단했습니다.</p>
      <button onClick=${unblock}>차단 해제</button>
    </div>
  </div>`;

  const trendTxt = { down: "▼ 감소 추세", up: "▲ 증가 추세", flat: "▬ 유지" };
  const joined = p.created_at
    ? new Date(p.created_at).toLocaleDateString("ko-KR", { year: "numeric", month: "long" })
    : null;
  return html`<div class="view profile">
    <div class="profile-head">
      <${Avatar} src=${p.avatar && p.avatar.url} name=${p.name} size="lg" />
      <div class="profile-id">
        <div class="phandle">${p.name} <${RankBadge} level=${p.rank_level} /></div>
        ${p.bio && html`<p class="pbio">${p.bio}</p>`}
      </div>
      ${p.mine
        ? html`<button class="ghost" onClick=${() => nav("/settings")}>편집</button>`
        : html`<div class="profile-actions">
            <button class=${following ? "ghost" : ""} onClick=${toggleFollow}>${following ? "팔로잉" : "팔로우"}</button>
            <button class="icon-btn" onClick=${() => setMenu(!menu)} aria-label="더보기">⋯</button>
            ${menu && html`<div class="menu-pop">
              <button class="plain" onClick=${report}>신고</button>
              <button onClick=${block}>차단</button>
            </div>`}
          </div>`}
    </div>

    ${(p.location || p.link || joined) && html`<div class="profile-meta">
      ${p.location && html`<span>📍 ${p.location}</span>`}
      ${p.link && html`<a href=${p.link} target="_blank" rel="noopener noreferrer nofollow">🔗 ${p.link.replace(/^https?:\/\//, "")}</a>`}
      ${joined && html`<span>${joined} 가입</span>`}
    </div>`}

    <div class="profile-stats">
      <span><b>${followers}</b> 팔로워</span>
      <span><b>${p.following}</b> 팔로잉</span>
      <span><b>${p.post_count}</b> 글</span>
      <span>연속 ${p.streak}일</span>
      ${p.recent_weight != null
        ? html`<span>최근 ${fmtKg(p.recent_weight)}kg</span>`
        : p.trend && html`<span>${trendTxt[p.trend]}</span>`}
    </div>

    ${p.trend_series && p.trend_series.length > 1 && html`<${Sparkline} data=${p.trend_series} />`}

    ${p.pinned && html`<div class="pinned-wrap">
      <span class="pin-label">📌 고정한 글</span>
      <${PostCard} post=${p.pinned} />
    </div>`}
    ${p.posts.length === 0 && !p.pinned
      ? html`<div class="empty">아직 글이 없어요.</div>`
      : p.posts.map((post) => html`<${PostCard} key=${post.id} post=${post} />`)}
  </div>`;
}

// ---------- 뷰: 챌린지 목록 ----------
function ChallengesView() {
  const { bumpKey, nav, openChallenge } = useStore();
  const [items, setItems] = useState(null);
  const [state, setState] = useState("loading");
  useEffect(() => {
    setState("loading");
    api("/challenges").then((d) => { setItems(d.items); setState("ok"); })
      .catch(() => setState("err"));
  }, [bumpKey]);

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "err") return html`<${ErrorBox} msg="챌린지를 불러오지 못했습니다" />`;

  return html`<div class="view challenges">
    <button class="write-btn" onClick=${openChallenge}>＋ 챌린지 만들기</button>
    ${items.length === 0
      ? html`<div class="empty">첫 챌린지를 만들어 보세요. 연속으로 지킬 루틴을요.</div>`
      : items.map((c) => html`
        <article class="challenge-card" key=${c.id} onClick=${() => nav(`/challenges/${c.id}`)}>
          <div class="cc-title">${c.title}</div>
          <div class="cc-meta">
            <span>${c.target_days}일 목표</span>
            <span>·</span>
            <span>${c.member_count}명 참여</span>
            ${c.i_joined && html`<span class="cc-badge">내 진행 ${c.progress}/${c.target_days}</span>`}
          </div>
        </article>`)}
  </div>`;
}

// ---------- 뷰: 챌린지 상세 ----------
function ChallengeView({ id }) {
  const { bump, toast, nav } = useStore();
  const [c, setC] = useState(null);
  const [state, setState] = useState("loading");
  const [busy, setBusy] = useState(false);
  const today = new Date();
  today.setMinutes(today.getMinutes() - today.getTimezoneOffset());
  const todayStr = today.toISOString().slice(0, 10);

  const load = useCallback(async () => {
    try { setC(await api(`/challenges/${id}`)); setState("ok"); }
    catch (e) { setState(e.status === 404 ? "gone" : "err"); }
  }, [id]);
  useEffect(() => { setState("loading"); load(); }, [id, load]);

  const join = async () => {
    setBusy(true);
    try { await api(`/challenges/${id}/join`, { method: "POST" }); await load(); bump(); }
    catch (e) { toast(e.detail, "err"); }
    finally { setBusy(false); }
  };
  const leave = async () => {
    if (!confirm("챌린지에서 나갈까요? 체크 기록이 사라집니다.")) return;
    try { await api(`/challenges/${id}/leave`, { method: "DELETE" }); bump(); nav("/challenges"); }
    catch (e) { toast(e.detail, "err"); }
  };
  const check = async () => {
    const done = c.my_dates && c.my_dates.includes(todayStr);
    setBusy(true);
    try {
      if (done) await api(`/challenges/${id}/checkin/${todayStr}`, { method: "DELETE" });
      else await api(`/challenges/${id}/checkin`, { method: "POST", body: { date: todayStr } });
      await load(); bump();
    } catch (e) { toast(e.detail, "err"); }
    finally { setBusy(false); }
  };

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "gone") return html`<div class="view"><${ErrorBox} msg="없는 챌린지입니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" onRetry=${load} /></div>`;

  const checkedToday = c.my_dates && c.my_dates.includes(todayStr);
  const pct = Math.min(100, Math.round((c.my_progress / c.target_days) * 100));
  return html`<div class="view challenge-detail">
    <h2>${c.title}</h2>
    <p class="muted sm">${c.owner_name} 시작 · ${c.target_days}일 목표</p>
    ${c.description && html`<p class="cd-desc">${c.description}</p>`}

    ${c.i_joined
      ? html`
        <div class="cd-progress">
          <div class="pbar"><div class="pfill" style=${`width:${pct}%`}></div></div>
          <div class="pnum">${c.my_progress} / ${c.target_days}일 · 연속 ${c.my_streak}일</div>
        </div>
        <button class=${"check-btn" + (checkedToday ? " done" : "")} disabled=${busy} onClick=${check}>
          ${checkedToday ? "오늘 완료 ✓" : "오늘 체크하기"}
        </button>
        <button class="ghost leave-btn" onClick=${leave}>챌린지 나가기</button>`
      : html`<button disabled=${busy} onClick=${join}>참여하기</button>`}

    <div class="panel">
      <div class="panel-head"><span>참여자 ${c.members.length}명</span></div>
      ${c.members.map((m) => html`<div class="member-row" key=${m.name}>
        <button class="handle" onClick=${() => nav(`/u/${encodeURIComponent(m.name)}`)}>${m.name}</button>
        <div class="mini-bar"><div class="mini-fill" style=${`width:${Math.min(100, Math.round((m.progress / c.target_days) * 100))}%`}></div></div>
        <span class="mnum">${m.progress}일</span>
      </div>`)}
    </div>
  </div>`;
}

// ---------- 뷰: 알림 ----------
function NoticeCard({ a }) {
  const inner = html`
    ${a.title && html`<div class="notice-title">${a.title}</div>`}
    <p class="notice-body">${a.body}</p>
    ${a.link && html`<span class="notice-more">자세히 보기 →</span>`}
  `;
  return a.link
    ? html`<a class="notice-card" href=${a.link} target="_blank" rel="noopener noreferrer">${inner}</a>`
    : html`<div class="notice-card">${inner}</div>`;
}

function NotificationsView() {
  const { bumpKey, nav, clearUnread } = useStore();
  const [data, setData] = useState(null);
  const [state, setState] = useState("loading");

  useEffect(() => {
    setState("loading");
    api("/notifications").then((d) => {
      setData(d); setState("ok");
      api("/notifications/read", { method: "POST" }).then(clearUnread).catch(() => {});
    }).catch(() => setState("err"));
  }, [bumpKey]);

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "err") return html`<${ErrorBox} msg="알림을 불러오지 못했습니다" />`;

  const anns = data.announcements || [];
  const items = data.items || [];
  const verb = { encourage: "님이 응원했어요", comment: "님이 댓글을 남겼어요", follow: "님이 팔로우했어요" };

  return html`<div class="view notifications">
    ${anns.length > 0 && html`
      <div class="notice-divider">공지</div>
      ${anns.map((a) => html`<${NoticeCard} key=${a.id} a=${a} />`)}
    `}
    ${items.length === 0 && anns.length === 0
      ? html`<div class="empty">아직 알림이 없어요.</div>`
      : items.map((n) => html`
        <button class=${"notif" + (n.read ? "" : " unread")} key=${n.id}
          onClick=${() => n.kind === "rank" ? nav("/me") : n.post_id ? nav(`/p/${n.post_id}`) : nav(`/u/${encodeURIComponent(n.actor_name)}`)}>
          ${n.kind === "rank"
            ? html`<span>🎉 <${RankBadge} level=${n.rank_level} /> 등급이 되었어요</span>`
            : html`<span><b>${n.actor_name}</b>${verb[n.kind] || ""}</span>`}
          <span class="notif-time">${relTime(n.created_at)}</span>
        </button>`)}
  </div>`;
}

// ---------- 뷰: 설정 ----------
function SettingsView() {
  const { setMe, toast, nav } = useStore();
  const [f, setF] = useState({ login_id: "", name: "", bio: "", link: "", location: "", target_weight: "", weight_privacy: "private" });
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [avatar, setAvatar] = useState(null);
  const [meInfo, setMeInfo] = useState({});
  const [tg, setTg] = useState({ linked: false, available: true, code: null, busy: false });
  useEffect(() => {
    api("/auth/me").then((d) => {
      setMe(d); setMeInfo(d);
      setAvatar(d.avatar || null);
      setTg((t) => ({ ...t, linked: !!d.telegram_linked }));
      setF({ login_id: d.login_id || "", name: d.name || "", bio: d.bio || "",
        link: d.link || "", location: d.location || "",
        target_weight: d.target_weight ?? "", weight_privacy: d.weight_privacy || "private" });
    }).catch(() => {});
  }, []);

  const refreshTg = useCallback(async () => {
    try {
      const s = await api("/push/telegram");
      setTg((t) => ({ ...t, linked: s.linked, available: s.available, code: s.linked ? null : t.code }));
    } catch {}
  }, []);
  useEffect(() => {
    const on = () => document.visibilityState === "visible" && refreshTg();
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, [refreshTg]);
  const startTg = async () => {
    setTg((t) => ({ ...t, busy: true }));
    try {
      const c = await api("/push/telegram/code", { method: "POST" });
      setTg((t) => ({ ...t, code: c, busy: false }));
      window.open(c.deep_link, "_blank", "noopener");
    } catch (e) { toast(e.detail, "err"); setTg((t) => ({ ...t, busy: false })); }
  };
  const unlinkTg = async () => {
    try {
      await api("/push/telegram", { method: "DELETE" });
      setTg({ linked: false, available: true, code: null, busy: false });
      toast("텔레그램 알림을 껐습니다");
    } catch (e) { toast(e.detail, "err"); }
  };

  const changeAvatar = async (media) => {
    setAvatar(media);
    try {
      await api("/auth/me", { method: "PATCH", body: { avatar_media_id: media ? media.id : 0 } });
      const fresh = await api("/auth/me"); setMe(fresh);
      toast(media ? "프로필 사진을 바꿨습니다" : "프로필 사진을 지웠습니다");
    } catch (e) { toast(e.detail, "err"); }
  };

  const saveProfile = async () => {
    try {
      const body = { name: f.name, bio: f.bio, link: f.link, location: f.location, weight_privacy: f.weight_privacy };
      if (f.target_weight !== "") body.target_weight = parseFloat(f.target_weight);
      await api("/auth/me", { method: "PATCH", body });
      const fresh = await api("/auth/me"); setMe(fresh);
      toast("저장했습니다");
    } catch (e) { toast(e.detail, "err"); }
  };
  const savePw = async () => {
    if (pw.new_password.length < 8) return toast("새 비밀번호는 8자 이상", "err");
    try {
      await api("/auth/me", { method: "PATCH", body: pw });
      setPw({ current_password: "", new_password: "" });
      toast("비밀번호를 변경했습니다");
    } catch (e) { toast(e.detail, "err"); }
  };

  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return html`<div class="view settings">
    ${meInfo.is_owner && html`<button class="admin-link" onClick=${() => nav("/admin")}>
      관리자${meInfo.open_reports ? ` · 신고 ${meInfo.open_reports}` : ""}
    </button>`}
    <div class="panel">
      <div class="panel-head"><span>프로필</span></div>
      <div class="avatar-row">
        <${Avatar} src=${avatar && avatar.url} name=${f.name} size="lg" />
        <${ImageUpload} kind="avatar" value=${avatar} onChange=${changeAvatar} label="프로필 사진" compact=${true} />
      </div>
      <label>아이디 <span class="hint">변경 불가 · 비공개</span>
        <input value=${f.login_id} disabled /></label>
      <label>이름 <span class="hint">피드·프로필에 표시됨</span>
        <input value=${f.name} onInput=${upd("name")} maxlength="20" /></label>
      <label>소개
        <input value=${f.bio} onInput=${upd("bio")} maxlength="200" placeholder="한 줄 소개" /></label>
      <label>지역 <span class="hint">선택 · 프로필에 표시됨</span>
        <input value=${f.location} onInput=${upd("location")} maxlength="60" placeholder="예: 서울" /></label>
      <label>링크 <span class="hint">선택 · 블로그·SNS 등</span>
        <input value=${f.link} onInput=${upd("link")} maxlength="200" placeholder="https://" inputmode="url" /></label>
      <label>목표 몸무게 (kg)
        <input type="number" step="0.1" min="20" max="300" value=${f.target_weight} onInput=${upd("target_weight")} /></label>
      <label>몸무게 공개
        <select value=${f.weight_privacy} onChange=${upd("weight_privacy")}>
          <option value="private">비공개</option>
          <option value="trend">추세 방향만</option>
          <option value="public">최근 값까지</option>
        </select></label>
      <button onClick=${saveProfile}>저장</button>
    </div>

    ${tg.available && html`<div class="panel">
      <div class="panel-head"><span>텔레그램 알림</span></div>
      ${tg.linked
        ? html`
          <p class="muted sm">연결됨 ✓ — 응원·댓글·팔로우 알림을 텔레그램으로도 받습니다.</p>
          <button class="ghost" onClick=${unlinkTg}>연결 해제</button>`
        : tg.code
          ? html`
            <p class="muted sm">텔레그램 봇 대화창에서 <b>시작</b>을 누르면 연결됩니다.</p>
            <p class="muted sm">연결 코드: <span class="mono">${tg.code.code}</span> <span class="hint">(10분 유효)</span></p>
            <a class="cta" href=${tg.code.deep_link} target="_blank" rel="noopener">텔레그램 봇 열기</a>
            <button class="ghost" onClick=${refreshTg}>연결됐는지 확인</button>`
          : html`
            <p class="muted sm">앱을 열지 않아도 알림을 받고 싶다면 텔레그램을 연결하세요. (선택)</p>
            <button disabled=${tg.busy} onClick=${startTg}>${tg.busy ? "준비 중…" : "텔레그램으로 알림 받기"}</button>`}
    </div>`}

    <div class="panel">
      <div class="panel-head"><span>비밀번호 변경</span></div>
      <label>현재 비밀번호
        <input type="password" value=${pw.current_password} onInput=${(e) => setPw({ ...pw, current_password: e.target.value })} /></label>
      <label>새 비밀번호 (8자 이상)
        <input type="password" value=${pw.new_password} onInput=${(e) => setPw({ ...pw, new_password: e.target.value })} /></label>
      <button onClick=${savePw}>변경</button>
    </div>

    <button class="logout" onClick=${logout}>로그아웃</button>
  </div>`;
}

// ---------- 뷰: 관리자 허브 ----------
function AdminHubView() {
  const { nav } = useStore();
  const [me, setLocalMe] = useState(null);
  useEffect(() => { api("/auth/me").then(setLocalMe).catch(() => setLocalMe({})); }, []);
  if (me && !me.is_owner) return html`<div class="view"><${ErrorBox} msg="권한이 없습니다" /></div>`;
  return html`<div class="view admin-hub">
    <button class="hub-item" onClick=${() => nav("/admin/reports")}>
      <span>신고 관리</span>
      ${me && me.open_reports ? html`<span class="hub-badge">${me.open_reports}</span>` : ""}
    </button>
    <button class="hub-item" onClick=${() => nav("/admin/announcements")}>
      <span>공지 관리</span>
    </button>
  </div>`;
}

// ---------- 뷰: 공지 관리 (오너) ----------
function AdminAnnouncementsView() {
  const { toast } = useStore();
  const [items, setItems] = useState(null);
  const [state, setState] = useState("loading");
  const [editing, setEditing] = useState(null); // 공지 객체 or {} (신규) or null

  const load = useCallback(() => {
    setState("loading");
    api("/admin/announcements").then((d) => { setItems(d.items); setState("ok"); })
      .catch((e) => setState(e.status === 403 ? "forbidden" : "err"));
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (form) => {
    const body = {
      title: form.title || null, body: form.body, link: form.link || null,
      starts_at: form.starts ? new Date(form.starts).toISOString() : null,
      ends_at: form.ends ? new Date(form.ends + "T23:59:59").toISOString() : null,
    };
    try {
      if (editing.id) await api(`/admin/announcements/${editing.id}`, { method: "PATCH", body });
      else await api("/admin/announcements", { method: "POST", body });
      toast("저장했습니다"); setEditing(null); load();
    } catch (e) { toast(e.detail, "err"); }
  };
  const del = async (id) => {
    if (!confirm("이 공지를 삭제할까요?")) return;
    try { await api(`/admin/announcements/${id}`, { method: "DELETE" }); toast("삭제했습니다"); load(); }
    catch (e) { toast(e.detail, "err"); }
  };

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "forbidden") return html`<div class="view"><${ErrorBox} msg="권한이 없습니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" onRetry=${load} /></div>`;

  const stateLabel = { scheduled: "예정", live: "게시 중", expired: "종료" };
  const dOnly = (iso) => (iso ? iso.slice(0, 10) : "");
  return html`<div class="view admin">
    ${editing
      ? html`<${AnnouncementForm} initial=${editing} onSave=${save} onCancel=${() => setEditing(null)} />`
      : html`<button class="write-btn" onClick=${() => setEditing({})}>＋ 새 공지</button>`}
    ${items.length === 0 && !editing
      ? html`<div class="empty">공지가 없어요.</div>`
      : items.map((a) => html`<div class="ann-card" key=${a.id}>
          <div class="ann-head">
            <span class=${"ann-state ann-" + a.state}>${stateLabel[a.state]}</span>
            <span class="muted sm">${dOnly(a.starts_at) || "즉시"} ~ ${dOnly(a.ends_at) || "무기한"}</span>
          </div>
          ${a.title && html`<div class="ann-title">${a.title}</div>`}
          <p class="ann-body">${a.body}</p>
          <div class="ann-actions">
            <button class="ghost" onClick=${() => setEditing({
              id: a.id, title: a.title || "", body: a.body, link: a.link || "",
              starts: dOnly(a.starts_at), ends: dOnly(a.ends_at),
            })}>수정</button>
            <button class="danger" onClick=${() => del(a.id)}>삭제</button>
          </div>
        </div>`)}
  </div>`;
}

function AnnouncementForm({ initial, onSave, onCancel }) {
  const [f, setF] = useState({
    title: initial.title || "", body: initial.body || "", link: initial.link || "",
    starts: initial.starts || "", ends: initial.ends || "",
  });
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = (e) => { e.preventDefault(); if (f.body.trim()) onSave(f); };
  return html`<form class="panel ann-form" onSubmit=${submit}>
    <label>제목 (선택)
      <input value=${f.title} onInput=${upd("title")} maxlength="80" /></label>
    <label>본문
      <textarea rows="3" value=${f.body} onInput=${upd("body")} maxlength="1000" required></textarea></label>
    <label>링크 (선택) <span class="hint">전체 URL</span>
      <input value=${f.link} onInput=${upd("link")} maxlength="300" placeholder="https://" inputmode="url" /></label>
    <label>게시 시작일 (선택) <span class="hint">비우면 즉시</span>
      <input type="date" value=${f.starts} onInput=${upd("starts")} /></label>
    <label>게시 종료일 (선택) <span class="hint">비우면 무기한 · 그날 끝까지</span>
      <input type="date" value=${f.ends} onInput=${upd("ends")} /></label>
    <div class="ann-form-actions">
      <button type="submit" disabled=${!f.body.trim()}>저장</button>
      <button type="button" class="ghost" onClick=${onCancel}>취소</button>
    </div>
  </form>`;
}

// ---------- 뷰: 신고 관리 (오너) ----------
function AdminReportsView() {
  const { nav, toast } = useStore();
  const [items, setItems] = useState(null);
  const [state, setState] = useState("loading");

  const load = useCallback(() => {
    setState("loading");
    api("/admin/reports").then((d) => { setItems(d.items); setState("ok"); })
      .catch((e) => setState(e.status === 403 ? "forbidden" : "err"));
  }, []);
  useEffect(() => { load(); }, [load]);

  const resolve = async (rid, action) => {
    if (action && !confirm(action === "delete_post" ? "이 글을 삭제할까요?" : "이 댓글을 삭제할까요?")) return;
    try {
      await api(`/admin/reports/${rid}/resolve`, { method: "POST", body: { action: action || "none" } });
      toast("처리했습니다"); load();
    } catch (e) { toast(e.detail, "err"); }
  };

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "forbidden") return html`<div class="view"><${ErrorBox} msg="권한이 없습니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" onRetry=${load} /></div>`;
  if (items.length === 0) return html`<div class="empty">처리할 신고가 없어요.</div>`;

  return html`<div class="view admin">
    ${items.map((r) => {
      const c = r.context || {};
      return html`<div class="report-card" key=${r.id}>
        <div class="rc-head">
          <span class="rc-kind">${r.target_kind === "post" ? "글" : r.target_kind === "comment" ? "댓글" : "사용자"}</span>
          <span class="rc-by">${r.reporter_name} 신고 · ${relTime(r.created_at)}</span>
        </div>
        ${r.reason && html`<p class="rc-reason">"${r.reason}"</p>`}
        <div class="rc-target">
          ${c.gone
            ? html`<span class="muted">(이미 삭제됨)</span>`
            : r.target_kind === "user"
              ? html`<b>${c.name}</b>${c.bio ? html` — ${c.bio}` : ""}`
              : html`<span class="muted sm">${c.author}</span> ${c.excerpt}`}
        </div>
        <div class="rc-actions">
          ${!c.gone && r.target_kind === "post" && html`
            <button class="ghost" onClick=${() => nav(`/p/${c.post_id}`)}>글 보기</button>
            <button class="danger" onClick=${() => resolve(r.id, "delete_post")}>글 삭제</button>`}
          ${!c.gone && r.target_kind === "comment" && html`
            <button class="ghost" onClick=${() => nav(`/p/${c.post_id}`)}>글 보기</button>
            <button class="danger" onClick=${() => resolve(r.id, "delete_comment")}>댓글 삭제</button>`}
          ${!c.gone && r.target_kind === "user" && html`
            <button class="ghost" onClick=${() => nav(`/u/${encodeURIComponent(c.name)}`)}>프로필</button>`}
          <button onClick=${() => resolve(r.id, null)}>무시</button>
        </div>
      </div>`;
    })}
  </div>`;
}

// ---------- 모달 ----------
function Modal({ title, onClose, children }) {
  return html`<div class="modal-back" onClick=${onClose}>
    <div class="modal" onClick=${(e) => e.stopPropagation()}>
      <div class="modal-grab"></div>
      <div class="modal-head"><span>${title}</span><button class="icon-btn" onClick=${onClose}>✕</button></div>
      ${children}
    </div>
  </div>`;
}

function WeightModal({ onClose }) {
  const { bump, toast } = useStore();
  const [w, setW] = useState("");
  const [at, setAt] = useState(nowLocalInput());
  const [note, setNote] = useState("");
  const [share, setShare] = useState(false);
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const willShare = share || !!photo;

  const onPhoto = (m) => { setPhoto(m); if (m) setShare(true); };
  const submit = async (e) => {
    e.preventDefault();
    const weight = parseFloat(w);
    if (!(weight >= 20 && weight <= 300)) return toast("몸무게는 20–300kg", "err");
    setBusy(true);
    try {
      await api("/weights", {
        method: "POST",
        body: { weight, logged_at: at, note, share: willShare, photo_media_id: photo ? photo.id : null },
      });
      bump(); toast("기록했습니다"); onClose();
    } catch (err) { toast(err.detail, "err"); setBusy(false); }
  };
  return html`<${Modal} title="몸무게 기록" onClose=${onClose}>
    <form class="modal-form" onSubmit=${submit}>
      <label>측정 시각
        <input type="datetime-local" value=${at} onInput=${(e) => setAt(e.target.value)} /></label>
      <label class="big-weight">몸무게 (kg)
        <input type="number" inputmode="decimal" step="0.1" value=${w} onInput=${(e) => setW(e.target.value)} autofocus required /></label>
      <label>메모 (선택)
        <input value=${note} onInput=${(e) => setNote(e.target.value)} maxlength="500" placeholder="컨디션, 상황…" /></label>
      <div class="field">
        <span class="field-label">진행 사진 (선택) <span class="hint">첨부하면 피드에 함께 공유돼요</span></span>
        <${ImageUpload} kind="progress" value=${photo} onChange=${onPhoto} label="사진 추가" />
      </div>
      <label class="check"><input type="checkbox" checked=${willShare} disabled=${!!photo}
        onChange=${(e) => setShare(e.target.checked)} />
        ${photo ? "사진과 함께 피드에 공유" : "이 기록을 글로 공유"}</label>
      <button disabled=${busy}>저장</button>
    </form>
  <//>`;
}

function PostModal({ onClose }) {
  const { bump, toast, nav } = useStore();
  const [kind, setKind] = useState("casual");
  const [body, setBody] = useState("");
  const [image, setImage] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!body.trim() || busy) return;
    setBusy(true);
    try {
      const { id } = await api("/posts", {
        method: "POST",
        body: { kind, body: body.trim(), image_media_id: image ? image.id : null },
      });
      bump(); toast("게시했습니다"); onClose(); nav(`/p/${id}`);
    } catch (err) { toast(err.detail, "err"); setBusy(false); }
  };
  return html`<${Modal} title="글쓰기" onClose=${onClose}>
    <form class="modal-form" onSubmit=${submit}>
      <div class="chips">
        ${Object.entries(KIND_LABEL).map(([k, l]) => html`<button type="button" key=${k}
          class=${"chip" + (k === kind ? " on" : "")} onClick=${() => setKind(k)}>${l}</button>`)}
      </div>
      <textarea rows="4" value=${body} onInput=${(e) => setBody(e.target.value)} maxlength="2000"
        placeholder="오늘 지킨 루틴, 느낀 점, 궁금한 것…" autofocus></textarea>
      <${ImageUpload} kind="post" value=${image} onChange=${setImage} label="사진 추가" />
      <button disabled=${!body.trim() || busy}>게시</button>
    </form>
  <//>`;
}

function ChallengeModal({ onClose }) {
  const { bump, toast, nav } = useStore();
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [days, setDays] = useState("21");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    const n = parseInt(days, 10);
    if (title.trim().length < 2) return toast("제목을 입력하세요", "err");
    if (!(n >= 1 && n <= 365)) return toast("목표 일수는 1–365", "err");
    setBusy(true);
    try {
      const { id } = await api("/challenges", {
        method: "POST",
        body: { title: title.trim(), description: desc.trim() || null, target_days: n },
      });
      bump(); toast("챌린지를 만들었어요"); onClose(); nav(`/challenges/${id}`);
    } catch (err) { toast(err.detail, "err"); setBusy(false); }
  };
  return html`<${Modal} title="챌린지 만들기" onClose=${onClose}>
    <form class="modal-form" onSubmit=${submit}>
      <label>제목 <span class="hint">예: 매일 기록 21일</span>
        <input value=${title} onInput=${(e) => setTitle(e.target.value)} maxlength="60" autofocus required /></label>
      <label>설명 (선택)
        <textarea rows="3" value=${desc} onInput=${(e) => setDesc(e.target.value)} maxlength="500"
          placeholder="어떤 루틴을 매일 지킬까요?"></textarea></label>
      <label>목표 일수
        <input type="number" inputmode="numeric" min="1" max="365" value=${days}
          onInput=${(e) => setDays(e.target.value)} /></label>
      <button disabled=${busy}>만들기</button>
    </form>
  <//>`;
}

function ActionSheet({ onClose, pick }) {
  return html`<div class="modal-back" onClick=${onClose}>
    <div class="sheet" onClick=${(e) => e.stopPropagation()}>
      <button onClick=${() => pick("weight")}>몸무게 기록</button>
      <button onClick=${() => pick("post")}>글쓰기</button>
      <button onClick=${() => pick("challenge")}>챌린지 만들기</button>
      <button class="cancel" onClick=${onClose}>취소</button>
    </div>
  </div>`;
}

// ---------- 앱 셸 ----------
function App() {
  const { route, nav } = useRoute();
  const [me, setMe] = useState(() => { try { return JSON.parse(localStorage.getItem(ME_KEY) || "null"); } catch { return null; } });
  const [toastState, setToastState] = useState(null);
  const [modal, setModal] = useState(null); // 'weight' | 'post' | 'challenge' | 'sheet' | null
  const [bumpKey, setBumpKey] = useState(0);
  const [unread, setUnread] = useState(0);
  const toastTimer = useRef(null);

  useEffect(() => {
    api("/auth/me").then((d) => {
      setMe(d);
      try { localStorage.setItem(ME_KEY, JSON.stringify(d)); } catch {}
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const refresh = () => api("/notifications/unread-count").then((d) => setUnread(d.count)).catch(() => {});
    refresh();
    const t = setInterval(refresh, 60000);
    return () => clearInterval(t);
  }, [bumpKey]);

  const toast = useCallback((text, kind) => {
    setToastState({ text, kind });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastState(null), 2600);
  }, []);
  const bump = useCallback(() => setBumpKey((k) => k + 1), []);

  const store = {
    me, setMe: (d) => { setMe(d); try { localStorage.setItem(ME_KEY, JSON.stringify(d)); } catch {} },
    route, nav, toast, bump, bumpKey, unread,
    toastData: toastState,
    clearUnread: () => setUnread(0),
    openSheet: () => setModal("sheet"),
    openWeight: () => setModal("weight"),
    openPost: () => setModal("post"),
    openChallenge: () => setModal("challenge"),
  };

  const m = route.match(/^\/p\/(\d+)$/);
  const cm = route.match(/^\/challenges\/(\d+)$/);
  const up = route.match(/^\/u\/(.+)$/);
  let view, title = "몸무게 기록", back = null;
  if (route === "/feed") { view = html`<${FeedView} />`; title = "피드"; }
  else if (route === "/challenges") { view = html`<${ChallengesView} />`; title = "챌린지"; }
  else if (cm) { view = html`<${ChallengeView} id=${cm[1]} />`; title = "챌린지"; back = () => nav("/challenges"); }
  else if (route === "/notifications") { view = html`<${NotificationsView} />`; title = "알림"; }
  else if (route === "/me") { view = html`<${MeView} />`; title = "나"; }
  else if (route === "/search") { view = html`<${SearchView} />`; title = "검색"; back = () => history.back(); }
  else if (route === "/admin") { view = html`<${AdminHubView} />`; title = "관리자"; back = () => nav("/settings"); }
  else if (route === "/admin/reports") { view = html`<${AdminReportsView} />`; title = "신고 관리"; back = () => nav("/admin"); }
  else if (route === "/admin/announcements") { view = html`<${AdminAnnouncementsView} />`; title = "공지 관리"; back = () => nav("/admin"); }
  else if (route === "/settings") { view = html`<${SettingsView} />`; title = "설정"; back = () => nav("/me"); }
  else if (m) { view = html`<${PostView} id=${m[1]} />`; title = "글"; back = () => history.back(); }
  else if (up) {
    const handle = decodeURIComponent(up[1]);
    view = html`<${ProfileView} handle=${handle} />`; title = handle; back = () => history.back();
  }
  else { view = html`<${FeedView} />`; title = "피드"; }

  const close = () => setModal(null);
  return html`<${Store.Provider} value=${store}>
    <div class="app-shell">
      <${TopBar} title=${title} onBack=${back} />
      <main class="app-main">${view}</main>
      <${TabBar} />
      <${Toast} />
      ${modal === "sheet" && html`<${ActionSheet} onClose=${close} pick=${setModal} />`}
      ${modal === "weight" && html`<${WeightModal} onClose=${close} />`}
      ${modal === "post" && html`<${PostModal} onClose=${close} />`}
      ${modal === "challenge" && html`<${ChallengeModal} onClose=${close} />`}
    </div>
  </${Store.Provider}>`;
}

// ---------- 부팅 ----------
if (!token()) {
  location.replace(BASE + "/");
} else {
  render(html`<${App} />`, document.getElementById("app"));
}
