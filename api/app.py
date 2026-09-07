"""health-web 실시간 조회 API (방식 B).

브라우저는 Oracle에 직접 못 붙으므로, VM에서 이 API가 `admin.weight_log`를
읽어 커밋된 `data/users/<hash>.json` 과 **동일한 형태**로 돌려준다.
프론트의 '새로고침' 버튼이 호출한다.

- 127.0.0.1 로만 바인드하고 앞단은 Caddy(HTTPS 종단)가 리버스 프록시.
- 쿼리는 `:uid` 바인드 고정 — 임의 SQL 불가.
- 반환 컬럼은 date/time/weight/quote 4개뿐 (tg_username·explanation·raw_text 제외).

필요 env: DB_USER, DB_PASSWORD, DB_DSN(기본 shindb_low),
          DB_WALLET_LOCATION, DB_WALLET_PASSWORD, ALLOW_ORIGIN
"""
from __future__ import annotations

import datetime
import os
import re
import time
from collections import defaultdict

import oracledb
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

UID_RE = re.compile(r"^\d{3,}$")

# 단일 프로세스(uvicorn 1 worker) 기준 간이 IP 레이트리밋
RATE_N = 20
RATE_WINDOW = 60
_hits: dict[str, list[float]] = defaultdict(list)

# export_weights.py 와 동일한 컬럼·조건 (두 경로가 어긋나지 않게)
# 바인드 이름은 :tg_uid — :uid 는 Oracle UID 함수와 충돌(ORA-01745)
QUERY = """
    select to_char(log_date, 'YYYY-MM-DD') as d,
           to_char(log_date, 'HH24:MI:SS') as t,
           weight,
           quote
    from admin.weight_log
    where tg_user_id = :tg_uid
      and weight is not null
    order by log_date
"""

pool: oracledb.ConnectionPool | None = None
app = FastAPI(title="health-web read API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOW_ORIGIN", "*").split(",")],
    allow_methods=["GET"],
    allow_headers=["*"],
)


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
        max=2,
        increment=1,
    )


@app.on_event("shutdown")
def _shutdown() -> None:
    if pool is not None:
        pool.close()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def _rate_ok(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _hits[ip] if now - t < RATE_WINDOW]
    _hits[ip] = hits
    if len(hits) >= RATE_N:
        return False
    hits.append(now)
    return True


@app.get("/weights")
def weights(uid: str, request: Request) -> dict:
    if not UID_RE.match(uid):
        raise HTTPException(status_code=400, detail="invalid uid")

    ip = request.client.host if request.client else "?"
    if not _rate_ok(ip):
        raise HTTPException(status_code=429, detail="rate limited")

    assert pool is not None
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(QUERY, tg_uid=uid)
            rows = cur.fetchall()

    entries = [
        {"date": d, "time": t, "weight": float(w), "quote": q} for d, t, w, q in rows
    ]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"updated_at": now, "count": len(entries), "entries": entries}
