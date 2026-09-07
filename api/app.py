"""health-web API — 인증 + 몸무게 조회.

프론트(정적, GitHub Pages)가 호출:
  POST /auth/signup   email+pw(8+)+tg_user_id(+목표) → 계정 생성(verified=N) + link 코드
  POST /auth/signin   email+pw → JWT
  POST /auth/reset    email+새 pw → reset 코드 (봇 확인 후 반영)
  GET  /auth/me       Bearer → 계정 정보 (미인증이면 link_code 포함)
  GET  /weights       Bearer(+verified) → 토큰의 tg_user_id로 weight_log 조회

health-bot(같은 VM)이 호출 (헤더 X-Internal-Key):
  POST /internal/link   {code, tg_user_id} → verify_code 대조 → app_user.verified=Y
  POST /internal/reset  {code, tg_user_id} → verify_code 대조 → password_hash 교체

127.0.0.1 바인드, 앞단 Caddy(HTTPS). /internal/* 은 Caddy에서 외부 404 + 시크릿 이중.

필요 env: DB_USER DB_PASSWORD DB_DSN DB_WALLET_LOCATION DB_WALLET_PASSWORD
          ALLOW_ORIGIN JWT_SECRET INTERNAL_KEY
"""
from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import time
from collections import defaultdict
from typing import Optional

import bcrypt
import jwt
import oracledb
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UID_RE = re.compile(r"^\d{3,}$")
JWT_ALG = "HS256"
JWT_TTL = dt.timedelta(days=7)
CODE_TTL_MIN = 10
MIN_WEIGHT, MAX_WEIGHT = 20, 300

WEIGHT_QUERY = """
    select to_char(log_date, 'YYYY-MM-DD') as d,
           to_char(log_date, 'HH24:MI:SS') as t,
           weight, quote
    from admin.weight_log
    where tg_user_id = :tg_uid and weight is not null
    order by log_date
"""

pool: oracledb.ConnectionPool | None = None
app = FastAPI(title="health-web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOW_ORIGIN", "*").split(",")],
    allow_methods=["GET", "POST"],
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
        max=3,
        increment=1,
    )


@app.on_event("shutdown")
def _shutdown() -> None:
    if pool is not None:
        pool.close()


def q1(sql: str, **binds):
    """SELECT 첫 행을 dict로, 없으면 None."""
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, **binds)
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0].lower() for c in cur.description]
        return dict(zip(cols, row))


def qall(sql: str, **binds) -> list[dict]:
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, **binds)
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def dml(sql: str, **binds) -> int:
    assert pool is not None
    with pool.acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, **binds)
        n = cur.rowcount
        conn.commit()
        return n


# ---------- auth 유틸 ----------

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def check_pw(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], h.encode())
    except ValueError:
        return False


def make_jwt(email: str, tg_user_id: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": tg_user_id, "email": email, "iat": now, "exp": now + JWT_TTL},
        os.environ["JWT_SECRET"],
        algorithm=JWT_ALG,
    )


def auth_user(authorization: str = Header(default="")) -> dict:
    """Bearer 토큰 → app_user 행(dict)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        payload = jwt.decode(
            authorization[7:], os.environ["JWT_SECRET"], algorithms=[JWT_ALG]
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해 주세요")
    u = q1(
        "select email, tg_user_id, verified, target_weight "
        "from healthweb.app_user where email = :e",
        e=payload.get("email"),
    )
    if u is None:
        raise HTTPException(401, "존재하지 않는 계정입니다")
    return u


def internal_auth(x_internal_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_key, os.environ.get("INTERNAL_KEY", "")):
        raise HTTPException(403, "forbidden")


def code_cutoff() -> dt.datetime:
    """유효 코드 하한 (naive UTC). ADB(server=UTC)의 created_at 과 naive 비교 —
    systimestamp(TZ-aware)를 WHERE에 쓰면 세션 TZ로 암묵 변환돼 어긋난다."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
        minutes=CODE_TTL_MIN
    )


def new_verify_code(
    purpose: str, email: str, tg_user_id: str, new_hash: str | None = None
) -> str:
    """해당 email·purpose의 기존 코드를 지우고 새 6자리 코드 발급."""
    dml(
        "delete from healthweb.verify_code where email = :e and purpose = :p",
        e=email,
        p=purpose,
    )
    for _ in range(6):
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            dml(
                "insert into healthweb.verify_code "
                "(code, purpose, email, tg_user_id, new_hash) "
                "values (:c, :p, :e, :u, :h)",
                c=code,
                p=purpose,
                e=email,
                u=tg_user_id,
                h=new_hash,
            )
            return code
        except oracledb.IntegrityError:
            continue
    raise HTTPException(500, "코드 생성에 실패했습니다. 다시 시도해 주세요")


# ---------- 레이트리밋 (단일 프로세스 인메모리) ----------

_hits: dict[str, list[float]] = defaultdict(list)


def rate_ok(key: str, limit: int, window: float) -> bool:
    now = time.time()
    hits = [t for t in _hits[key] if now - t < window]
    _hits[key] = hits
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


# ---------- 모델 ----------

class SignupIn(BaseModel):
    email: str
    password: str
    tg_user_id: str
    target_weight: Optional[float] = None


class SigninIn(BaseModel):
    email: str
    password: str


class ResetIn(BaseModel):
    email: str
    new_password: str


class CodeIn(BaseModel):
    code: str
    tg_user_id: str


# ---------- 엔드포인트 ----------

@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/auth/signup")
def signup(body: SignupIn, request: Request) -> dict:
    email = body.email.strip().lower()
    uid = body.tg_user_id.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다")
    if len(body.password) < 8:
        raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다")
    if not UID_RE.match(uid):
        raise HTTPException(400, "텔레그램 User ID는 숫자입니다 (봇에 /whoami)")
    tw = body.target_weight
    if tw is not None and not (MIN_WEIGHT <= tw <= MAX_WEIGHT):
        raise HTTPException(400, "목표 몸무게가 범위를 벗어났습니다")

    if not rate_ok(f"signup:{client_ip(request)}", 5, 3600):
        raise HTTPException(429, "가입 시도가 많습니다. 잠시 후 다시 시도해 주세요")

    if q1("select 1 as x from healthweb.app_user where email = :e", e=email):
        raise HTTPException(409, "이미 가입된 이메일입니다")
    if q1("select 1 as x from healthweb.app_user where tg_user_id = :u", u=uid):
        raise HTTPException(409, "이미 등록된 텔레그램 User ID입니다")

    try:
        dml(
            "insert into healthweb.app_user "
            "(email, password_hash, tg_user_id, target_weight) "
            "values (:e, :h, :u, :t)",
            e=email,
            h=hash_pw(body.password),
            u=uid,
            t=tw,
        )
    except oracledb.IntegrityError:
        raise HTTPException(409, "이미 가입된 계정입니다")

    code = new_verify_code("link", email, uid)
    return {
        "token": make_jwt(email, uid),
        "verified": False,
        "link_code": code,
        "message": f"헬스봇에게 /link {code} 를 보내면 인증이 완료됩니다 ({CODE_TTL_MIN}분 내).",
    }


@app.post("/auth/signin")
def signin(body: SigninIn, request: Request) -> dict:
    email = body.email.strip().lower()
    if not rate_ok(f"signin-ip:{client_ip(request)}", 15, 60) or not rate_ok(
        f"signin-em:{email}", 5, 900
    ):
        raise HTTPException(429, "로그인 시도가 많습니다. 15분 후 다시 시도해 주세요")

    u = q1(
        "select email, password_hash, tg_user_id, verified "
        "from healthweb.app_user where email = :e",
        e=email,
    )
    if u is None or not check_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다")

    dml(
        "update healthweb.app_user set last_login_at = systimestamp where email = :e",
        e=email,
    )
    return {"token": make_jwt(u["email"], u["tg_user_id"]), "verified": u["verified"] == "Y"}


@app.post("/auth/reset")
def reset(body: ResetIn, request: Request) -> dict:
    email = body.email.strip().lower()
    if len(body.new_password) < 8:
        raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다")
    if not rate_ok(f"reset:{client_ip(request)}", 5, 3600):
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요")

    u = q1("select tg_user_id from healthweb.app_user where email = :e", e=email)
    if u is None:
        raise HTTPException(404, "가입되지 않은 이메일입니다")

    code = new_verify_code(
        "reset", email, u["tg_user_id"], new_hash=hash_pw(body.new_password)
    )
    return {
        "reset_code": code,
        "message": f"헬스봇에게 /reset {code} 를 보내면 비밀번호가 변경됩니다 ({CODE_TTL_MIN}분 내).",
    }


@app.get("/auth/me")
def me(u: dict = Depends(auth_user)) -> dict:
    verified = u["verified"] == "Y"
    out = {
        "email": u["email"],
        "tg_user_id": u["tg_user_id"],
        "verified": verified,
        "target_weight": float(u["target_weight"])
        if u["target_weight"] is not None
        else None,
    }
    if not verified:
        row = q1(
            "select code from healthweb.verify_code "
            "where email = :e and purpose = 'link' and consumed = 'N' "
            "and created_at > :cutoff",
            e=u["email"],
            cutoff=code_cutoff(),
        )
        out["link_code"] = (
            row["code"] if row else new_verify_code("link", u["email"], u["tg_user_id"])
        )
    return out


@app.get("/weights")
def weights(request: Request, u: dict = Depends(auth_user)) -> dict:
    if u["verified"] != "Y":
        raise HTTPException(403, "텔레그램 인증이 필요합니다")
    if not rate_ok(f"weights:{client_ip(request)}", 30, 60):
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요")

    rows = qall(WEIGHT_QUERY, tg_uid=u["tg_user_id"])
    entries = [
        {"date": r["d"], "time": r["t"], "weight": float(r["weight"]), "quote": r["quote"]}
        for r in rows
    ]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"updated_at": now, "count": len(entries), "entries": entries}


@app.post("/internal/link")
def internal_link(body: CodeIn, _: None = Depends(internal_auth)) -> dict:
    row = q1(
        "select email, tg_user_id from healthweb.verify_code "
        "where code = :c and purpose = 'link' and consumed = 'N' "
        "and created_at > :cutoff",
        c=body.code,
        cutoff=code_cutoff(),
    )
    if row is None:
        raise HTTPException(404, "유효하지 않거나 만료된 코드입니다")
    if row["tg_user_id"] != body.tg_user_id:
        raise HTTPException(403, "이 코드는 다른 텔레그램 계정에서 발급되었습니다")

    dml("update healthweb.app_user set verified = 'Y' where email = :e", e=row["email"])
    dml("update healthweb.verify_code set consumed = 'Y' where code = :c", c=body.code)
    return {"ok": True, "email": row["email"]}


@app.post("/internal/reset")
def internal_reset(body: CodeIn, _: None = Depends(internal_auth)) -> dict:
    row = q1(
        "select email, tg_user_id, new_hash from healthweb.verify_code "
        "where code = :c and purpose = 'reset' and consumed = 'N' "
        "and created_at > :cutoff",
        c=body.code,
        cutoff=code_cutoff(),
    )
    if row is None:
        raise HTTPException(404, "유효하지 않거나 만료된 코드입니다")
    if row["tg_user_id"] != body.tg_user_id:
        raise HTTPException(403, "이 코드는 다른 텔레그램 계정에서 발급되었습니다")

    dml(
        "update healthweb.app_user set password_hash = :h where email = :e",
        h=row["new_hash"],
        e=row["email"],
    )
    dml("update healthweb.verify_code set consumed = 'Y' where code = :c", c=body.code)
    return {"ok": True, "email": row["email"]}
