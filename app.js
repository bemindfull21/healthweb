import { h, render, createContext } from "https://esm.sh/preact@10.24.3";
import { useState, useEffect, useRef, useCallback, useContext } from "https://esm.sh/preact@10.24.3/hooks";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(h);

// ---------- 설정 ----------
const API = "https://healthweb21.duckdns.org";
const TOKEN_KEY = "healthweb.token";
const ME_KEY = "healthweb.me";
const BASE = new URL(".", import.meta.url).pathname.replace(/\/$/, "");

const KIND_LABEL = { log: "기록", routine: "루틴", reflection: "회고", question: "질문" };

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
  return html`<header class="topbar">
    ${onBack && html`<button class="icon-btn" onClick=${onBack} aria-label="뒤로">‹</button>`}
    <span class="topbar-title">${title}</span>
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
  return html`<article class="post-card" onClick=${() => nav(`/p/${post.id}`)}>
    <div class="post-head">
      <button class="handle" onClick=${(e) => { e.stopPropagation(); nav(`/u/${encodeURIComponent(post.name)}`); }}>${post.name}</button>
      <${KindBadge} kind=${post.kind} />
      <span class="post-time">${relTime(post.created_at)}</span>
    </div>
    <p class="post-body">${post.body}</p>
    ${post.kind === "log" && post.weight != null &&
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
  const { me, bumpKey, openWeight, toast } = useStore();
  const [data, setData] = useState(null);
  const [state, setState] = useState("loading");

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
    <div class="stats">
      <div class="stat"><div class="k">최근 몸무게</div><div class="v">${last ? fmtKg(last.weight) : "–"} <small>kg</small></div></div>
      ${target && last && html`<div class="stat"><div class="k">목표까지</div>
        <div class="v">${Math.abs(last.weight - target) < 0.05 ? "달성 🎉"
          : html`${fmtKg(Math.abs(last.weight - target))} <small>kg ${last.weight > target ? "감량" : "증량"}</small>`}</div></div>`}
      <div class="stat"><div class="k">연속 기록</div><div class="v">${streakOf(entries)} <small>일</small></div></div>
      <div class="stat"><div class="k">기록 수</div><div class="v">${entries.length} <small>건</small></div></div>
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
              <td class="q">${e.note || "–"}</td>
              <td><button class="row-del" onClick=${() => del(e.id)} aria-label="삭제">✕</button></td>
            </tr>`;
          })}</tbody></table></div>
        </div>`}

    <button class="fab" onClick=${openWeight} aria-label="몸무게 기록">＋</button>
  </div>`;
}

// ---------- 뷰: 글 상세 ----------
function PostView({ id }) {
  const { me, nav, toast, bump } = useStore();
  const [post, setPost] = useState(null);
  const [state, setState] = useState("loading");
  const [cmt, setCmt] = useState("");
  const [sending, setSending] = useState(false);

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

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "gone") return html`<div class="view"><${ErrorBox} msg="삭제되었거나 없는 글입니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" onRetry=${load} /></div>`;

  return html`<div class="view post-detail">
    <div class="post-head">
      <button class="handle" onClick=${() => nav(`/u/${encodeURIComponent(post.name)}`)}>${post.name}</button>
      <${KindBadge} kind=${post.kind} />
      <span class="post-time">${relTime(post.created_at)}</span>
      ${post.mine && html`<button class="row-del" onClick=${delPost} aria-label="삭제">✕</button>`}
    </div>
    <p class="post-body full">${post.body}</p>
    ${post.kind === "log" && post.weight != null && html`<div class="post-weight big">${fmtKg(post.weight)} kg</div>`}
    <div class="post-actions"><${EncourageBtn} post=${post} big=${true} /></div>

    <div class="comments">
      <h3>댓글 ${post.comments.length || ""}</h3>
      ${post.comments.map((c) => html`<div class="comment" key=${c.id}>
        <button class="handle" onClick=${() => nav(`/u/${encodeURIComponent(c.name)}`)}>${c.name}</button>
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

  useEffect(() => {
    setState("loading");
    api(`/u/${encodeURIComponent(handle)}`).then((d) => {
      setP(d); setFollowing(d.i_follow); setFollowers(d.followers); setState("ok");
    }).catch((e) => setState(e.status === 404 ? "gone" : "err"));
  }, [handle]);

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

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "gone") return html`<div class="view"><${ErrorBox} msg="없는 사용자입니다" /></div>`;
  if (state === "err") return html`<div class="view"><${ErrorBox} msg="불러오지 못했습니다" /></div>`;

  const trendTxt = { down: "▼ 감소 추세", up: "▲ 증가 추세", flat: "▬ 유지" };
  return html`<div class="view profile">
    <div class="profile-head">
      <div class="avatar">${(p.name || "?")[0].toUpperCase()}</div>
      <div class="profile-id">
        <div class="phandle">${p.name}</div>
        ${p.bio && html`<p class="pbio">${p.bio}</p>`}
      </div>
      ${p.mine
        ? html`<button class="ghost" onClick=${() => nav("/settings")}>편집</button>`
        : html`<button class=${following ? "ghost" : ""} onClick=${toggleFollow}>${following ? "팔로잉" : "팔로우"}</button>`}
    </div>
    <div class="profile-stats">
      <span><b>${followers}</b> 팔로워</span>
      <span><b>${p.following}</b> 팔로잉</span>
      <span>연속 ${p.streak}일</span>
      ${p.recent_weight != null
        ? html`<span>최근 ${fmtKg(p.recent_weight)}kg</span>`
        : p.trend && html`<span>${trendTxt[p.trend]}</span>`}
    </div>
    ${p.posts.length === 0
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
function NotificationsView() {
  const { bumpKey, nav, clearUnread } = useStore();
  const [items, setItems] = useState(null);
  const [state, setState] = useState("loading");

  useEffect(() => {
    setState("loading");
    api("/notifications").then((d) => {
      setItems(d.items); setState("ok");
      api("/notifications/read", { method: "POST" }).then(clearUnread).catch(() => {});
    }).catch(() => setState("err"));
  }, [bumpKey]);

  if (state === "loading") return html`<${Spinner} />`;
  if (state === "err") return html`<${ErrorBox} msg="알림을 불러오지 못했습니다" />`;
  if (items.length === 0) return html`<div class="empty">아직 알림이 없어요.</div>`;

  const verb = { encourage: "님이 응원했어요", comment: "님이 댓글을 남겼어요", follow: "님이 팔로우했어요" };
  return html`<div class="view notifications">
    ${items.map((n) => html`
      <button class=${"notif" + (n.read ? "" : " unread")} key=${n.id}
        onClick=${() => n.post_id ? nav(`/p/${n.post_id}`) : nav(`/u/${encodeURIComponent(n.actor_name)}`)}>
        <span><b>${n.actor_name}</b>${verb[n.kind] || ""}</span>
        <span class="notif-time">${relTime(n.created_at)}</span>
      </button>`)}
  </div>`;
}

// ---------- 뷰: 설정 ----------
function SettingsView() {
  const { setMe, toast } = useStore();
  const [f, setF] = useState({ login_id: "", name: "", bio: "", target_weight: "", weight_privacy: "private" });
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  useEffect(() => {
    api("/auth/me").then((d) => {
      setMe(d);
      setF({ login_id: d.login_id || "", name: d.name || "", bio: d.bio || "",
        target_weight: d.target_weight ?? "", weight_privacy: d.weight_privacy || "private" });
    }).catch(() => {});
  }, []);

  const saveProfile = async () => {
    try {
      const body = { name: f.name, bio: f.bio, weight_privacy: f.weight_privacy };
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
    <div class="panel">
      <div class="panel-head"><span>프로필</span></div>
      <label>아이디 <span class="hint">변경 불가 · 비공개</span>
        <input value=${f.login_id} disabled /></label>
      <label>이름 <span class="hint">피드·프로필에 표시됨</span>
        <input value=${f.name} onInput=${upd("name")} maxlength="20" /></label>
      <label>소개
        <input value=${f.bio} onInput=${upd("bio")} maxlength="200" placeholder="한 줄 소개" /></label>
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
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const weight = parseFloat(w);
    if (!(weight >= 20 && weight <= 300)) return toast("몸무게는 20–300kg", "err");
    setBusy(true);
    try {
      await api("/weights", { method: "POST", body: { weight, logged_at: at, note, share } });
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
      <label class="check"><input type="checkbox" checked=${share} onChange=${(e) => setShare(e.target.checked)} /> 이 기록을 글로 공유</label>
      <button disabled=${busy}>저장</button>
    </form>
  <//>`;
}

function PostModal({ onClose }) {
  const { bump, toast, nav } = useStore();
  const [kind, setKind] = useState("routine");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!body.trim() || busy) return;
    setBusy(true);
    try {
      const { id } = await api("/posts", { method: "POST", body: { kind, body: body.trim() } });
      bump(); toast("게시했습니다"); onClose(); nav(`/p/${id}`);
    } catch (err) { toast(err.detail, "err"); setBusy(false); }
  };
  return html`<${Modal} title="글쓰기" onClose=${onClose}>
    <form class="modal-form" onSubmit=${submit}>
      <div class="chips">
        ${Object.entries(KIND_LABEL).map(([k, l]) => html`<button type="button" key=${k}
          class=${"chip" + (k === kind ? " on" : "")} onClick=${() => setKind(k)}>${l}</button>`)}
      </div>
      <textarea rows="6" value=${body} onInput=${(e) => setBody(e.target.value)} maxlength="2000"
        placeholder="오늘 지킨 루틴, 느낀 점, 궁금한 것…" autofocus></textarea>
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
