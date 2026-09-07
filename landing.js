"use strict";
// config.js 제공: API, TOKEN_KEY, ME_KEY

const $ = (id) => document.getElementById(id);

// 이미 로그인돼 있으면 대시보드로 (토큰 만료면 app.html이 다시 돌려보냄 — 루프 아님)
try {
  if (localStorage.getItem(TOKEN_KEY)) location.replace("./app.html");
} catch {}

function saveSession(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.removeItem(ME_KEY);
  } catch {}
}

function toApp() {
  location.href = "./app.html";
}

function msg(el, text, kind) {
  el.textContent = text;
  el.className = "form-msg" + (kind ? " " + kind : "");
  el.hidden = !text;
}

function showTab(name) {
  for (const t of ["login", "signup", "reset"]) $(`form-${t}`).hidden = t !== name;
  document
    .querySelectorAll(".tab")
    .forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
}

async function postJSON(path, body) {
  let res;
  try {
    res = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, data: { detail: "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요." } };
  }
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

// ---------- 로그인 ----------
$("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter || e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  const { ok, data } = await postJSON("/auth/signin", {
    email: $("login-email").value.trim(),
    password: $("login-password").value,
  });
  btn.disabled = false;
  if (!ok) return msg($("login-msg"), data.detail || "로그인에 실패했습니다", "err");
  saveSession(data.token);
  toApp();
});

// ---------- 회원가입 ----------
$("form-signup").addEventListener("submit", async (e) => {
  e.preventDefault();
  const m = $("signup-msg");
  const pw = $("signup-password").value;
  if (pw.length < 8) return msg(m, "비밀번호는 8자 이상이어야 합니다", "err");
  if (pw !== $("signup-password2").value) return msg(m, "비밀번호가 일치하지 않습니다", "err");
  const uid = $("signup-uid").value.trim();
  if (!/^\d{3,}$/.test(uid)) return msg(m, "텔레그램 User ID는 숫자입니다 (봇에게 /whoami)", "err");

  const body = { email: $("signup-email").value.trim(), password: pw, tg_user_id: uid };
  const tw = $("signup-target").value.trim();
  if (tw) body.target_weight = parseFloat(tw);

  const btn = e.submitter || e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  const { ok, data } = await postJSON("/auth/signup", body);
  btn.disabled = false;
  if (!ok) return msg(m, data.detail || "가입에 실패했습니다", "err");
  saveSession(data.token);
  toApp(); // 대시보드에서 텔레그램 인증 안내
});

// ---------- 비밀번호 재설정 ----------
$("form-reset").addEventListener("submit", async (e) => {
  e.preventDefault();
  const m = $("reset-msg");
  const pw = $("reset-password").value;
  if (pw.length < 8) return msg(m, "비밀번호는 8자 이상이어야 합니다", "err");
  if (pw !== $("reset-password2").value) return msg(m, "비밀번호가 일치하지 않습니다", "err");

  const btn = e.submitter || e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  const { ok, data } = await postJSON("/auth/reset", {
    email: $("reset-email").value.trim(),
    new_password: pw,
  });
  btn.disabled = false;
  if (!ok) return msg(m, data.detail || "요청에 실패했습니다", "err");
  msg(m, data.message || "헬스봇에게 코드를 보내면 변경됩니다.", "ok");
});

// ---------- 탭 전환 ----------
document.querySelectorAll("[data-tab]").forEach((el) =>
  el.addEventListener("click", (e) => {
    if (el.tagName === "A") e.preventDefault();
    showTab(el.dataset.tab);
  })
);
$("to-reset").addEventListener("click", (e) => {
  e.preventDefault();
  showTab("reset");
});

showTab("login");
