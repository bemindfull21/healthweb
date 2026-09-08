"""health-web API — Phase 1 (커뮤니티).

계정: 로그인 아이디(login_id, 영문+숫자 소문자, 비공개) / 비밀번호.
      이름(name)이 공개 handle — 피드·프로필·URL. login_id·name 둘 다 unique.
      비밀번호 재설정: login_id + name 일치 확인.
몸무게: healthweb.weight_entry (키 = login_id). 커뮤니티: post / encouragement / post_comment.

127.0.0.1 바인드, 앞단 Caddy(HTTPS).
필요 env: DB_USER DB_PASSWORD DB_DSN DB_WALLET_LOCATION DB_WALLET_PASSWORD ALLOW_ORIGIN JWT_SECRET
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
from collections import defaultdict
from typing import Optional

import bcrypt
import jwt
import oracledb
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

LOGIN_ID_RE = re.compile(r"^[a-z0-9]{3,20}$")
JWT_ALG = "HS256"
JWT_TTL = dt.timedelta(days=7)
MIN_WEIGHT, MAX_WEIGHT = 20.0, 300.0
POST_KINDS = {"log", "routine", "reflection", "question"}
PRIVACY = {"private", "trend", "public"}

pool: oracledb.ConnectionPool | None = None
app = FastAPI(title="health-web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOW_ORIGIN", "*").split(",")],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# ---------- DB ----------

@app.on_event("startup")
def _startup() -> None:
    global pool
    wallet = os.environ["DB_WALLET_LOCATION"]
    pool = oracledb.create_pool(
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dsn=os.environ.get("DB_DSN", "shindb_low"),
        config_dir=wallet,
        wallet_location=wallet,
        wallet_password=os.environ["DB_WALLET_PASSWORD"],
        min=1,
        max=4,
        increment=1,
    )


@app.on_event("shutdown")
def _shutdown() -> None:
    if pool is not None:
        pool.close()


@app.exception_handler(Exception)
def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    print(f"[500] {request.method} {request.url.path}: {exc!r}")
    return JSONResponse(status_code=500, content={"detail": "서버 오류가 발생했습니다"})


def q1(sql: str, **b):
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, **b)
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0].lower() for c in cur.description]
        return dict(zip(cols, row))


def qall(sql: str, **b) -> list[dict]:
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, **b)
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def dml(sql: str, **b) -> int:
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, **b)
        n = cur.rowcount
        conn.commit()
        return n


def insert_id(sql: str, **b) -> int:
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        new_id = cur.var(oracledb.NUMBER)
        cur.execute(sql, new_id=new_id, **b)
        conn.commit()
        return int(new_id.getvalue()[0])


# ---------- auth 유틸 ----------

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def check_pw(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], h.encode())
    except ValueError:
        return False


def make_jwt(login_id: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": login_id, "iat": now, "exp": now + JWT_TTL},
        os.environ["JWT_SECRET"],
        algorithm=JWT_ALG,
    )


def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        payload = jwt.decode(
            authorization[7:], os.environ["JWT_SECRET"], algorithms=[JWT_ALG]
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해 주세요")
    u = q1(
        "select login_id, name, bio, target_weight, weight_privacy "
        "from healthweb.app_user where login_id = :lid",
        lid=payload.get("sub"),
    )
    if u is None:
        raise HTTPException(401, "존재하지 않는 계정입니다")
    return u


def clean_name(raw: str) -> str:
    n = " ".join(raw.split())  # 연속 공백/개행 정리
    if not (2 <= len(n) <= 20) or "/" in n or "@" in n:
        raise HTTPException(400, "이름은 2–20자이고 / @ 는 쓸 수 없습니다")
    return n


# ---------- 레이트리밋 ----------

_hits: dict[str, list[float]] = defaultdict(list)


def rate_ok(key: str, limit: int, window: float) -> bool:
    now = time.time()
    hits = [t for t in _hits[key] if now - t < window]
    _hits[key] = hits
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True


def ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def parse_dt(s: Optional[str]) -> dt.datetime:
    if s:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return dt.datetime.strptime(s.strip(), fmt)
            except ValueError:
                continue
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_z(d: Optional[dt.datetime] = None) -> str:
    d = d or dt.datetime.now(dt.timezone.utc)
    if d.tzinfo:
        return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 모델 ----------

class SignupIn(BaseModel):
    login_id: str
    name: str
    password: str
    target_weight: Optional[float] = None


class SigninIn(BaseModel):
    login_id: str
    password: str


class ResetIn(BaseModel):
    login_id: str
    name: str
    new_password: str


class MePatch(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    target_weight: Optional[float] = None
    weight_privacy: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


class WeightIn(BaseModel):
    weight: float
    logged_at: Optional[str] = None
    note: Optional[str] = None
    share: bool = False


class PostIn(BaseModel):
    kind: str
    body: str
    weight_entry_id: Optional[int] = None


class CommentIn(BaseModel):
    body: str


# ---------- 헬스체크 ----------

@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# ---------- 인증 ----------

@app.get("/auth/check")
def check(login_id: Optional[str] = None, name: Optional[str] = None) -> dict:
    out: dict = {}
    if login_id is not None:
        lid = login_id.strip().lower()
        if not LOGIN_ID_RE.match(lid):
            out["login_id"] = {"available": False, "reason": "영문 소문자·숫자 3–20자"}
        else:
            taken = q1("select 1 as x from healthweb.app_user where login_id = :v", v=lid)
            out["login_id"] = {"available": taken is None, "reason": None if taken is None else "이미 사용 중"}
    if name is not None:
        try:
            n = clean_name(name)
        except HTTPException:
            out["name"] = {"available": False, "reason": "2–20자 · / @ 불가"}
        else:
            taken = q1("select 1 as x from healthweb.app_user where lower(name) = lower(:v)", v=n)
            out["name"] = {"available": taken is None, "reason": None if taken is None else "이미 사용 중"}
    return out


@app.post("/auth/signup")
def signup(body: SignupIn, request: Request) -> dict:
    lid = body.login_id.strip().lower()
    name = clean_name(body.name)
    if not LOGIN_ID_RE.match(lid):
        raise HTTPException(400, "아이디는 영문 소문자·숫자 3–20자입니다")
    if len(body.password) < 8:
        raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다")
    tw = body.target_weight
    if tw is not None and not (MIN_WEIGHT <= tw <= MAX_WEIGHT):
        raise HTTPException(400, "목표 몸무게가 범위를 벗어났습니다")
    if not rate_ok(f"signup:{ip(request)}", 5, 3600):
        raise HTTPException(429, "가입 시도가 많습니다. 잠시 후 다시 시도해 주세요")

    if q1("select 1 as x from healthweb.app_user where login_id = :v", v=lid):
        raise HTTPException(409, "이미 사용 중인 아이디입니다")
    if q1("select 1 as x from healthweb.app_user where lower(name) = lower(:v)", v=name):
        raise HTTPException(409, "이미 사용 중인 이름입니다")
    try:
        dml(
            "insert into healthweb.app_user (login_id, name, password_hash, target_weight) "
            "values (:l, :n, :h, :t)",
            l=lid, n=name, h=hash_pw(body.password), t=tw,
        )
    except oracledb.IntegrityError:
        raise HTTPException(409, "이미 사용 중인 아이디 또는 이름입니다")
    return {"token": make_jwt(lid), "login_id": lid, "name": name}


@app.post("/auth/signin")
def signin(body: SigninIn, request: Request) -> dict:
    lid = body.login_id.strip().lower()
    if not rate_ok(f"signin-ip:{ip(request)}", 20, 60) or not rate_ok(f"signin:{lid}", 5, 900):
        raise HTTPException(429, "로그인 시도가 많습니다. 15분 후 다시 시도해 주세요")
    u = q1(
        "select login_id, name, password_hash from healthweb.app_user where login_id = :v",
        v=lid,
    )
    if u is None or not check_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    dml("update healthweb.app_user set last_login_at = systimestamp where login_id = :v", v=lid)
    return {"token": make_jwt(lid), "login_id": lid, "name": u["name"]}


@app.post("/auth/reset")
def reset(body: ResetIn, request: Request) -> dict:
    lid = body.login_id.strip().lower()
    if len(body.new_password) < 8:
        raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다")
    if not rate_ok(f"reset:{ip(request)}", 5, 3600):
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요")
    u = q1("select name from healthweb.app_user where login_id = :v", v=lid)
    if u is None or " ".join(body.name.split()).lower() != u["name"].lower():
        raise HTTPException(401, "아이디와 이름이 일치하지 않습니다")
    dml(
        "update healthweb.app_user set password_hash = :h where login_id = :v",
        h=hash_pw(body.new_password), v=lid,
    )
    return {"ok": True}


@app.get("/auth/me")
def me(u: dict = Depends(current_user)) -> dict:
    return {
        "login_id": u["login_id"],
        "name": u["name"],
        "bio": u["bio"],
        "target_weight": float(u["target_weight"]) if u["target_weight"] is not None else None,
        "weight_privacy": u["weight_privacy"],
    }


@app.patch("/auth/me")
def patch_me(body: MePatch, u: dict = Depends(current_user)) -> dict:
    sets, binds = [], {"v": u["login_id"]}
    if body.name is not None:
        n = clean_name(body.name)
        if n.lower() != u["name"].lower():
            if q1("select 1 as x from healthweb.app_user where lower(name) = lower(:n)", n=n):
                raise HTTPException(409, "이미 사용 중인 이름입니다")
        sets.append("name = :n"); binds["n"] = n
    if body.bio is not None:
        sets.append("bio = :bio"); binds["bio"] = body.bio.strip()[:200] or None
    if body.target_weight is not None:
        if not (MIN_WEIGHT <= body.target_weight <= MAX_WEIGHT):
            raise HTTPException(400, "목표 몸무게가 범위를 벗어났습니다")
        sets.append("target_weight = :t"); binds["t"] = body.target_weight
    if body.weight_privacy is not None:
        if body.weight_privacy not in PRIVACY:
            raise HTTPException(400, "잘못된 공개 범위")
        sets.append("weight_privacy = :p"); binds["p"] = body.weight_privacy
    if body.new_password is not None:
        if len(body.new_password) < 8:
            raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다")
        cur = q1("select password_hash from healthweb.app_user where login_id = :v", v=u["login_id"])
        if not check_pw(body.current_password or "", cur["password_hash"]):
            raise HTTPException(401, "현재 비밀번호가 올바르지 않습니다")
        sets.append("password_hash = :ph"); binds["ph"] = hash_pw(body.new_password)

    if sets:
        dml(f"update healthweb.app_user set {', '.join(sets)} where login_id = :v", **binds)
    return {"ok": True}


# ---------- 몸무게 ----------

@app.get("/weights")
def list_weights(u: dict = Depends(current_user)) -> dict:
    rows = qall(
        "select id, to_char(logged_at,'YYYY-MM-DD') d, to_char(logged_at,'HH24:MI:SS') t, "
        "weight, note from healthweb.weight_entry where login_id = :v order by logged_at",
        v=u["login_id"],
    )
    entries = [
        {"id": r["id"], "date": r["d"], "time": r["t"], "weight": float(r["weight"]), "note": r["note"]}
        for r in rows
    ]
    return {"updated_at": iso_z(), "count": len(entries), "entries": entries}


@app.post("/weights")
def add_weight(body: WeightIn, u: dict = Depends(current_user)) -> dict:
    if not (MIN_WEIGHT <= body.weight <= MAX_WEIGHT):
        raise HTTPException(400, "몸무게는 20–300kg 범위입니다")
    if not rate_ok(f"w:{u['login_id']}", 30, 60):
        raise HTTPException(429, "요청이 많습니다")
    logged = parse_dt(body.logged_at)
    note = (body.note or "").strip()[:500] or None

    entry_id = insert_id(
        "insert into healthweb.weight_entry (login_id, logged_at, weight, note) "
        "values (:l, :d, :w, :n) returning id into :new_id",
        l=u["login_id"], d=logged, w=body.weight, n=note,
    )
    post_id = None
    if body.share:
        post_id = insert_id(
            "insert into healthweb.post (login_id, kind, body, weight_entry_id) "
            "values (:l, 'log', :b, :e) returning id into :new_id",
            l=u["login_id"], b=note or "오늘도 기록했어요.", e=entry_id,
        )
    return {"id": entry_id, "post_id": post_id}


@app.delete("/weights/{entry_id}")
def del_weight(entry_id: int, u: dict = Depends(current_user)) -> dict:
    owned = q1(
        "select 1 as x from healthweb.weight_entry where id = :i and login_id = :v",
        i=entry_id, v=u["login_id"],
    )
    if owned is None:
        raise HTTPException(404, "기록을 찾을 수 없습니다")
    dml("update healthweb.post set weight_entry_id = null where weight_entry_id = :i", i=entry_id)
    dml("delete from healthweb.weight_entry where id = :i", i=entry_id)
    return {"ok": True}


# ---------- 피드 · 글 ----------

def _post_row(r: dict) -> dict:
    out = {
        "id": r["id"],
        "name": r["name"],
        "kind": r["kind"],
        "body": r["body"],
        "created_at": iso_z(r["created_at"]) if r["created_at"] else None,
        "encourage_count": r.get("enc_count", 0) or 0,
        "comment_count": r.get("cmt_count", 0) or 0,
        "i_encouraged": bool(r.get("i_enc")),
        "mine": bool(r.get("mine")),
    }
    if r["kind"] == "log" and r.get("weight") is not None and r.get("weight_privacy") == "public":
        out["weight"] = float(r["weight"])
    return out


FEED_SQL = """
    select p.id, au.name, p.kind, p.body, p.created_at,
           we.weight, au.weight_privacy,
           case when p.login_id = :viewer then 1 else 0 end mine,
           (select count(*) from healthweb.encouragement e where e.post_id = p.id) enc_count,
           (select count(*) from healthweb.post_comment c where c.post_id = p.id) cmt_count,
           (select count(*) from healthweb.encouragement e where e.post_id = p.id and e.login_id = :viewer) i_enc
    from healthweb.post p
    join healthweb.app_user au on au.login_id = p.login_id
    left join healthweb.weight_entry we on we.id = p.weight_entry_id
    {where}
    order by p.id desc
    fetch first :lim rows only
"""


@app.get("/feed")
def feed(u: dict = Depends(current_user), cursor: Optional[int] = None, limit: int = 20) -> dict:
    limit = max(1, min(limit, 50))
    where = "where p.id < :cur" if cursor else ""
    binds = {"viewer": u["login_id"], "lim": limit}
    if cursor:
        binds["cur"] = cursor
    rows = qall(FEED_SQL.format(where=where), **binds)
    items = [_post_row(r) for r in rows]
    return {"items": items, "next_cursor": items[-1]["id"] if len(items) == limit else None}


@app.post("/posts")
def create_post(body: PostIn, u: dict = Depends(current_user)) -> dict:
    if body.kind not in POST_KINDS:
        raise HTTPException(400, "잘못된 글 종류")
    text = body.body.strip()
    if not (1 <= len(text) <= 2000):
        raise HTTPException(400, "본문은 1–2000자입니다")
    eid = body.weight_entry_id
    if eid is not None:
        owned = q1(
            "select 1 as x from healthweb.weight_entry where id = :i and login_id = :v",
            i=eid, v=u["login_id"],
        )
        if owned is None:
            eid = None
    pid = insert_id(
        "insert into healthweb.post (login_id, kind, body, weight_entry_id) "
        "values (:l, :k, :b, :e) returning id into :new_id",
        l=u["login_id"], k=body.kind, b=text, e=eid,
    )
    return {"id": pid}


@app.get("/posts/{post_id}")
def get_post(post_id: int, u: dict = Depends(current_user)) -> dict:
    rows = qall(FEED_SQL.format(where="where p.id = :pid"), viewer=u["login_id"], lim=1, pid=post_id)
    if not rows:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    post = _post_row(rows[0])
    comments = qall(
        "select c.id, au.name, c.body, c.created_at, "
        "case when c.login_id = :viewer then 1 else 0 end mine "
        "from healthweb.post_comment c join healthweb.app_user au on au.login_id = c.login_id "
        "where c.post_id = :p order by c.id",
        p=post_id, viewer=u["login_id"],
    )
    post["comments"] = [
        {"id": c["id"], "name": c["name"], "body": c["body"],
         "created_at": iso_z(c["created_at"]), "mine": bool(c["mine"])}
        for c in comments
    ]
    return post


@app.post("/posts/{post_id}/encourage")
def encourage(post_id: int, u: dict = Depends(current_user)) -> dict:
    if q1("select 1 as x from healthweb.post where id = :p", p=post_id) is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    try:
        dml(
            "insert into healthweb.encouragement (post_id, login_id) values (:p, :l)",
            p=post_id, l=u["login_id"],
        )
    except oracledb.IntegrityError:
        pass
    return {"ok": True}


@app.delete("/posts/{post_id}/encourage")
def unencourage(post_id: int, u: dict = Depends(current_user)) -> dict:
    dml(
        "delete from healthweb.encouragement where post_id = :p and login_id = :l",
        p=post_id, l=u["login_id"],
    )
    return {"ok": True}


@app.post("/posts/{post_id}/comments")
def add_comment(post_id: int, body: CommentIn, u: dict = Depends(current_user)) -> dict:
    text = body.body.strip()
    if not (1 <= len(text) <= 1000):
        raise HTTPException(400, "댓글은 1–1000자입니다")
    if q1("select 1 as x from healthweb.post where id = :p", p=post_id) is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    cid = insert_id(
        "insert into healthweb.post_comment (post_id, login_id, body) "
        "values (:p, :l, :b) returning id into :new_id",
        p=post_id, l=u["login_id"], b=text,
    )
    return {"id": cid}


@app.delete("/posts/{post_id}")
def delete_post(post_id: int, u: dict = Depends(current_user)) -> dict:
    owned = q1("select 1 as x from healthweb.post where id = :p and login_id = :l", p=post_id, l=u["login_id"])
    if owned is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    dml("delete from healthweb.post_comment where post_id = :p", p=post_id)
    dml("delete from healthweb.encouragement where post_id = :p", p=post_id)
    dml("delete from healthweb.post where id = :p", p=post_id)
    return {"ok": True}


# ---------- 프로필 ----------

def _streak(login_id: str) -> int:
    days = qall(
        "select distinct to_char(logged_at,'YYYY-MM-DD') d from healthweb.weight_entry "
        "where login_id = :v order by d desc",
        v=login_id,
    )
    if not days:
        return 0
    have = {r["d"] for r in days}
    cur = dt.datetime.strptime(days[0]["d"], "%Y-%m-%d").date()
    n = 0
    while cur.strftime("%Y-%m-%d") in have:
        n += 1
        cur -= dt.timedelta(days=1)
    return n


@app.get("/u/{handle}")
def profile(handle: str, u: dict = Depends(current_user)) -> dict:
    p = q1(
        "select login_id, name, bio, target_weight, weight_privacy, created_at "
        "from healthweb.app_user where lower(name) = lower(:h)",
        h=" ".join(handle.split()),
    )
    if p is None:
        raise HTTPException(404, "없는 사용자입니다")

    out = {
        "name": p["name"],
        "bio": p["bio"],
        "created_at": iso_z(p["created_at"]),
        "weight_privacy": p["weight_privacy"],
        "streak": _streak(p["login_id"]),
        "mine": p["login_id"] == u["login_id"],
    }
    if p["weight_privacy"] in ("trend", "public"):
        recent = qall(
            "select weight, logged_at from healthweb.weight_entry where login_id = :v "
            "order by logged_at desc fetch first 20 rows only",
            v=p["login_id"],
        )
        if recent:
            latest = float(recent[0]["weight"])
            two_wk = recent[0]["logged_at"] - dt.timedelta(days=14)
            older = [float(r["weight"]) for r in recent if r["logged_at"] <= two_wk]
            base = older[0] if older else float(recent[-1]["weight"])
            diff = latest - base
            out["trend"] = "down" if diff < -0.1 else "up" if diff > 0.1 else "flat"
            if p["weight_privacy"] == "public":
                out["recent_weight"] = latest
                if p["target_weight"] is not None:
                    out["target_weight"] = float(p["target_weight"])

    posts = qall(
        FEED_SQL.format(where="where p.login_id = :pl"),
        viewer=u["login_id"], lim=30, pl=p["login_id"],
    )
    out["posts"] = [_post_row(r) for r in posts]
    return out
