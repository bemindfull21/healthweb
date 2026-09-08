"use strict";
// config.js: window.HW = { API, TOKEN_KEY, ME_KEY }
const { API, TOKEN_KEY, ME_KEY } = window.HW;
const $ = (id) => document.getElementById(id);
const APP = "./app.html";

try {
  if (localStorage.getItem(TOKEN_KEY)) location.replace(APP);
} catch {}

function saveSession(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.removeItem(ME_KEY);
  } catch {}
}

function msg(el, text, kind) {
  el.textContent = text;
  el.className = "form-msg" + (kind ? " " + kind : "");
  el.hidden = !text;
}

function showTab(name) {
  for (const t of ["login", "signup", "reset"]) $(`form-${t}`).hidden = t !== name;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
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
    return { ok: false, data: { detail: "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요." } };
  }
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
}

// ---------- 실시간 중복 확인 ----------
function liveCheck(inputId, statusId, param, formatOk) {
  let timer = null;
  $(inputId).addEventListener("input", (e) => {
    const el = $(statusId);
    const v = e.target.value.trim();
    clearTimeout(timer);
    if (!v) { el.textContent = ""; el.className = "field-status"; return; }
    if (!formatOk(v)) { el.textContent = "형식을 확인하세요"; el.className = "field-status bad"; return; }
    el.textContent = "확인 중…"; el.className = "field-status";
    timer = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/auth/check?${param}=${encodeURIComponent(v)}`);
        const d = (await r.json())[param];
        if (d.available) { el.textContent = "사용 가능"; el.className = "field-status ok"; }
        else { el.textContent = d.reason || "사용할 수 없음"; el.className = "field-status bad"; }
      } catch { el.textContent = ""; el.className = "field-status"; }
    }, 400);
  });
}
liveCheck("signup-loginid", "loginid-status", "login_id", (v) => /^[a-z0-9]{3,20}$/.test(v.toLowerCase()));
liveCheck("signup-name", "name-status", "name", (v) => v.length >= 2 && v.length <= 20 && !/[/@]/.test(v));

// ---------- 로그인 ----------
$("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter || e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  const { ok, data } = await postJSON("/auth/signin", {
    login_id: $("login-loginid").value.trim().toLowerCase(),
    password: $("login-password").value,
  });
  btn.disabled = false;
  if (!ok) return msg($("login-msg"), data.detail || "로그인에 실패했습니다", "err");
  saveSession(data.token);
  location.href = APP;
});

// ---------- 회원가입 ----------
$("form-signup").addEventListener("submit", async (e) => {
  e.preventDefault();
  const m = $("signup-msg");
  const lid = $("signup-loginid").value.trim().toLowerCase();
  if (!/^[a-z0-9]{3,20}$/.test(lid)) return msg(m, "아이디는 영문 소문자·숫자 3–20자입니다", "err");
  const name = $("signup-name").value.trim().replace(/\s+/g, " ");
  if (name.length < 2 || name.length > 20 || /[/@]/.test(name)) return msg(m, "이름은 2–20자이고 / @ 는 쓸 수 없습니다", "err");
  const pw = $("signup-password").value;
  if (pw.length < 8) return msg(m, "비밀번호는 8자 이상이어야 합니다", "err");
  if (pw !== $("signup-password2").value) return msg(m, "비밀번호가 일치하지 않습니다", "err");

  const body = { login_id: lid, name, password: pw };
  const tw = $("signup-target").value.trim();
  if (tw) body.target_weight = parseFloat(tw);

  const btn = e.submitter || e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  const { ok, data } = await postJSON("/auth/signup", body);
  btn.disabled = false;
  if (!ok) return msg(m, data.detail || "가입에 실패했습니다", "err");
  saveSession(data.token);
  location.href = APP;
});

// ---------- 비밀번호 재설정 ----------
$("form-reset").addEventListener("submit", async (e) => {
  e.preventDefault();
  const m = $("reset-msg");
  const pw = $("reset-password").value;
  if (pw.length < 8) return msg(m, "비밀번호는 8자 이상이어야 합니다", "err");
  const btn = e.submitter || e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  const { ok, data } = await postJSON("/auth/reset", {
    login_id: $("reset-loginid").value.trim().toLowerCase(),
    name: $("reset-name").value.trim().replace(/\s+/g, " "),
    new_password: pw,
  });
  btn.disabled = false;
  if (!ok) return msg(m, data.detail || "재설정에 실패했습니다", "err");
  msg(m, "변경되었습니다. 새 비밀번호로 로그인하세요.", "ok");
  setTimeout(() => showTab("login"), 1200);
});

// ---------- 탭 ----------
document.querySelectorAll("[data-tab]").forEach((el) =>
  el.addEventListener("click", (e) => {
    if (el.tagName === "A") e.preventDefault();
    showTab(el.dataset.tab);
  })
);
$("to-reset").addEventListener("click", (e) => { e.preventDefault(); showTab("reset"); });

showTab("login");
