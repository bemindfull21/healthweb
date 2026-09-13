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
import io
import json
import os
import pathlib
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any, Optional

import bcrypt
import jwt
import oracledb
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps
from pydantic import BaseModel

LOGIN_ID_RE = re.compile(r"^[a-z0-9]{3,20}$")
JWT_ALG = "HS256"
JWT_TTL = dt.timedelta(days=7)
MIN_WEIGHT, MAX_WEIGHT = 20.0, 300.0
POST_KINDS = {"brag", "resolve", "reflect", "casual"}
PRIVACY = {"private", "trend", "public"}

MEDIA_DIR = pathlib.Path(os.environ.get("MEDIA_DIR", "media"))
MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL", "/media").rstrip("/")
OWNER_LOGIN_ID = os.environ.get("OWNER_LOGIN_ID", "").strip().lower()
IMG_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD = 8 * 1024 * 1024
MEDIA_QUOTA = 200
DISPLAY_MAX = 1280
THUMB_MAX = 320
Image.MAX_IMAGE_PIXELS = 40_000_000  # 디컴프레션 폭탄 방어

# 텔레그램 알림 (옵트인)
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "health_trainer21_bot").strip().lstrip("@")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://bemindfull21.github.io/healthweb").rstrip("/")
INTERNAL_KEY = os.environ.get("INTERNAL_KEY", "").strip()
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 글자 제외
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()  # _shared/secrets.env 공용, 다른 프로젝트와 쿼터 공유
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

pool: oracledb.ConnectionPool | None = None
app = FastAPI(title="health-web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOW_ORIGIN", "*").split(",")],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
_MEDIA_ROOT = MEDIA_DIR.resolve()


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
        "select au.login_id, au.name, au.bio, au.link, au.location, au.pinned_post_id, "
        "au.target_weight, au.weight_privacy, au.avatar_media_id, au.tg_chat_id, au.rank_level, au.rank_score, au.erp_access, "
        "m.path avatar_path, m.thumb_path avatar_thumb "
        "from healthweb.app_user au "
        "left join healthweb.media m on m.id = au.avatar_media_id "
        "where au.login_id = :lid",
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


def utcnow() -> dt.datetime:
    """naive UTC — 세션 TZ에 안 흔들리는 timestamp 비교용."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_z(d: Optional[dt.datetime] = None) -> str:
    d = d or dt.datetime.now(dt.timezone.utc)
    if d.tzinfo:
        return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(s: Optional[str]) -> Optional[dt.datetime]:
    """ISO 8601(Z/offset/날짜만) → naive UTC. 빈 값이면 None."""
    if not s or not s.strip():
        return None
    t = re.sub(r"\.\d+", "", s.strip())
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(t)
    except ValueError:
        try:
            d = dt.datetime.strptime(t[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "날짜 형식이 올바르지 않습니다")
    if d.tzinfo is not None:
        d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return d.replace(microsecond=0)


NOTIFY_VERB = {
    "encourage": "님이 응원했어요",
    "comment": "님이 댓글을 남겼어요",
    "follow": "님이 팔로우했어요",
}

# ---------- 등급 (자기돌봄 습관이 단단해진 정도) ----------
RANK_NAMES = {1: "흑연", 2: "흑요석", 3: "자수정", 4: "사파이어", 5: "다이아몬드"}
RANK_THRESHOLDS = [(0, 1), (50, 2), (200, 3), (600, 4), (1500, 5)]  # (최소 점수, 등급)
RANK_W_DAY = 1        # 기록한 날 (누적, 연속 아니어도 됨)
RANK_W_STREAK = 2     # 역대 최장 연속 기록일
RANK_W_COMPLETE = 30  # 완주한 챌린지 (체크인 수 >= 목표일수)
RANK_W_CHECKIN = 1    # 챌린지 체크인 총 횟수


def _tg_api(method: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        print(f"[tg] {method} 실패: {e!r}")
        return 0, {}


def _push_worker(chat_id: int, text: str) -> None:
    status, _ = _tg_api("sendMessage", {"chat_id": chat_id, "text": text})
    if status in (400, 403):  # 봇 차단됨 / 채팅 없음 → 연결 해제
        try:
            dml("update healthweb.app_user set tg_chat_id = null where tg_chat_id = :c", c=chat_id)
        except Exception:
            pass


def _maybe_push(recipient: str, kind: str, actor: str, post_id: Optional[int]) -> None:
    if not TG_TOKEN:
        return
    row = q1("select tg_chat_id from healthweb.app_user where login_id = :r", r=recipient)
    if not row or row["tg_chat_id"] is None:
        return
    a = q1("select name from healthweb.app_user where login_id = :a", a=actor)
    who = a["name"] if a else "누군가"
    link = (f"{WEB_APP_URL}/p/{post_id}" if post_id
            else f"{WEB_APP_URL}/u/{urllib.parse.quote(who)}")
    text = f"{who}{NOTIFY_VERB.get(kind, '님이 반응했어요')}\n{link}"
    threading.Thread(target=_push_worker, args=(int(row["tg_chat_id"]), text), daemon=True).start()


def notify(recipient: str, kind: str, actor: str, post_id: Optional[int] = None) -> None:
    """recipient에게 알림. 자기 행동은 건너뛴다. tg 연결돼 있으면 텔레그램도 전송(비동기)."""
    if recipient == actor:
        return
    dml(
        "insert into healthweb.notification (login_id, kind, actor, post_id) "
        "values (:r, :k, :a, :p)",
        r=recipient, k=kind, a=actor, p=post_id,
    )
    _maybe_push(recipient, kind, actor, post_id)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https?://[^\s]{3,197}$", re.I)


def clean_link(raw: Optional[str]) -> Optional[str]:
    s = (raw or "").strip()
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    if not URL_RE.match(s):
        raise HTTPException(400, "링크는 올바른 URL이어야 합니다")
    return s[:200]


def is_blocked(a: str, b: str) -> bool:
    """a와 b 사이에 어느 방향으로든 차단이 있으면 True."""
    return q1(
        "select 1 x from healthweb.user_block "
        "where (blocker = :a and blocked = :b) or (blocker = :b and blocked = :a)",
        a=a, b=b,
    ) is not None


def like_arg(q: str) -> str:
    """LIKE 와일드카드 이스케이프 후 %감쌈%. escape '\\' 와 함께 사용."""
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q.lower()}%"


# 피드 쿼리에 항상 붙는 차단 필터 (viewer 바인드 필요)
BLOCK_FILTER = """
    p.login_id not in (
        select blocked from healthweb.user_block where blocker = :viewer
        union all
        select blocker from healthweb.user_block where blocked = :viewer
    )
"""


# ---------- 이미지 ----------

def _process_image(raw: bytes, kind: str) -> dict:
    """Pillow 로 검증·EXIF 제거·재인코딩. 표시용 + 썸네일 JPEG 2장 저장하고 메타 반환.
    동기 함수 — run_in_threadpool 로 호출."""
    try:
        Image.open(io.BytesIO(raw)).verify()  # 손상·폭탄 1차 검사
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im)      # 회전 반영 후 EXIF 폐기
        im = im.convert("RGB")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "이미지를 읽을 수 없습니다")

    if kind == "avatar":
        disp = ImageOps.fit(im, (400, 400), Image.LANCZOS)
    else:
        disp = im.copy()
        disp.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.LANCZOS)
    thumb = im.copy()
    thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)

    token = secrets.token_hex(16)
    key, tkey = f"{token[:2]}/{token}.jpg", f"{token[:2]}/{token}_t.jpg"
    (MEDIA_DIR / key).parent.mkdir(parents=True, exist_ok=True)
    b = io.BytesIO()
    disp.save(b, "JPEG", quality=82, optimize=True)
    (MEDIA_DIR / key).write_bytes(b.getvalue())
    bt = io.BytesIO()
    thumb.save(bt, "JPEG", quality=78, optimize=True)
    (MEDIA_DIR / tkey).write_bytes(bt.getvalue())
    return {"path": key, "thumb_path": tkey, "width": disp.width, "height": disp.height,
            "bytes": len(b.getvalue())}


def _media_url(path: Optional[str], thumb: Optional[str] = None) -> Optional[dict]:
    if not path:
        return None
    return {"url": f"{MEDIA_BASE_URL}/{path}",
            "thumb_url": f"{MEDIA_BASE_URL}/{thumb or path}"}


def _unlink_media(path: Optional[str], thumb: Optional[str]) -> None:
    for p in (path, thumb):
        if p:
            try:
                (MEDIA_DIR / p).unlink(missing_ok=True)
            except OSError:
                pass


def _gc_media(mid: Optional[int]) -> None:
    """어디에서도 참조하지 않으면 media 행 + 파일 삭제."""
    if not mid:
        return
    if q1(
        "select 1 x from healthweb.app_user where avatar_media_id = :i "
        "union all select 1 from healthweb.weight_entry where photo_media_id = :i "
        "union all select 1 from healthweb.post where image_media_id = :i "
        "union all select 1 from healthweb.purchase_item where source_media_id = :i "
        "union all select 1 from healthweb.purchase_item where thumb_media_id = :i",
        i=mid,
    ):
        return
    m = q1("select path, thumb_path from healthweb.media where id = :i", i=mid)
    if m:
        dml("delete from healthweb.media where id = :i", i=mid)
        _unlink_media(m["path"], m["thumb_path"])


def _own_media(mid: Optional[int], login_id: str, *kinds: str) -> Optional[int]:
    """mid 가 login_id 소유이고 kind 가 맞으면 그대로, 0 이하/None 이면 None, 아니면 400."""
    if mid is None or mid <= 0:
        return None
    row = q1(
        "select 1 x from healthweb.media where id = :i and login_id = :v and kind in "
        "(" + ", ".join(f"'{k}'" for k in kinds) + ")",
        i=mid, v=login_id,
    )
    if row is None:
        raise HTTPException(400, "잘못된 이미지입니다")
    return mid


def require_owner(u: dict) -> None:
    if not OWNER_LOGIN_ID or u["login_id"] != OWNER_LOGIN_ID:
        raise HTTPException(403, "권한이 없습니다")


def require_erp(u: dict) -> None:
    if not u["erp_access"]:
        raise HTTPException(403, "권한이 없습니다")


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
    link: Optional[str] = None
    location: Optional[str] = None
    pinned_post_id: Optional[int] = None  # 0 또는 음수 → 고정 해제
    avatar_media_id: Optional[int] = None  # 0 또는 음수 → 아바타 제거
    target_weight: Optional[float] = None
    weight_privacy: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


class WeightIn(BaseModel):
    weight: float
    logged_at: Optional[str] = None
    note: Optional[str] = None
    share: bool = False
    photo_media_id: Optional[int] = None  # share=True 일 때만


class PostIn(BaseModel):
    kind: str
    body: str
    weight_entry_id: Optional[int] = None
    image_media_id: Optional[int] = None


class PostPatch(BaseModel):
    body: str
    kind: Optional[str] = None


class ReportIn(BaseModel):
    target_kind: str
    target_id: str
    reason: Optional[str] = None


class ResolveIn(BaseModel):
    action: Optional[str] = None  # None/'none' | 'delete_post' | 'delete_comment'


class TgLinkIn(BaseModel):
    code: str
    chat_id: int


class TgUnlinkIn(BaseModel):
    chat_id: int


class AnnouncementIn(BaseModel):
    title: Optional[str] = None
    body: str
    link: Optional[str] = None
    starts_at: Optional[str] = None  # ISO(UTC) 또는 null
    ends_at: Optional[str] = None


class CommentIn(BaseModel):
    body: str


class ChallengeIn(BaseModel):
    title: str
    description: Optional[str] = None
    target_days: int


class CheckinIn(BaseModel):
    date: str


class ErpAccessIn(BaseModel):
    erp_access: bool


class PurchaseExtractIn(BaseModel):
    media_id: int


class PurchaseItemIn(BaseModel):
    shop_name: Optional[str] = None
    product_name: str
    option_text: Optional[str] = None
    quantity: int = 1
    price_cny: Optional[float] = None
    price_krw: Optional[float] = None
    fx_rate: Optional[float] = None
    thumb_media_id: Optional[int] = None


class PurchaseSaveIn(BaseModel):
    items: list[PurchaseItemIn]
    order_date: str
    source_media_id: Optional[int] = None


class PurchasePatchIn(BaseModel):
    received: Optional[bool] = None
    quantity: Optional[int] = None


class ExpenseIn(BaseModel):
    expense_date: str
    item_name: str
    amount_krw: float
    purchase_item_id: Optional[int] = None


class ExpensePatchIn(BaseModel):
    amount_krw: float


class SaleItemIn(BaseModel):
    purchase_item_id: int
    sale_qty: int
    sale_price_krw: float = 0


class SaleSaveIn(BaseModel):
    items: list[SaleItemIn]
    sale_date: str
    is_waste: bool = False


class SalePatchIn(BaseModel):
    sale_qty: int
    sale_price_krw: float


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
    out = {
        "login_id": u["login_id"],
        "name": u["name"],
        "bio": u["bio"],
        "link": u["link"],
        "location": u["location"],
        "pinned_post_id": u["pinned_post_id"],
        "avatar": _media_url(u["avatar_path"], u["avatar_thumb"]),
        "telegram_linked": u["tg_chat_id"] is not None,
        "target_weight": float(u["target_weight"]) if u["target_weight"] is not None else None,
        "weight_privacy": u["weight_privacy"],
        "rank_level": u["rank_level"],
        "rank_name": RANK_NAMES[u["rank_level"]],
        "rank_score": u["rank_score"],
        "erp_access": bool(u["erp_access"]),
    }
    if OWNER_LOGIN_ID and u["login_id"] == OWNER_LOGIN_ID:
        out["is_owner"] = True
        out["open_reports"] = q1(
            "select count(*) c from healthweb.report where status = 'open'"
        )["c"]
    return out


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
    if body.link is not None:
        sets.append("link = :link"); binds["link"] = clean_link(body.link)
    if body.location is not None:
        sets.append("location = :loc"); binds["loc"] = body.location.strip()[:60] or None
    if body.pinned_post_id is not None:
        if body.pinned_post_id <= 0:
            sets.append("pinned_post_id = null")
        else:
            own = q1(
                "select 1 x from healthweb.post where id = :i and login_id = :v",
                i=body.pinned_post_id, v=u["login_id"],
            )
            if own is None:
                raise HTTPException(400, "본인 글만 고정할 수 있습니다")
            sets.append("pinned_post_id = :pp"); binds["pp"] = body.pinned_post_id
    if body.avatar_media_id is not None:
        if body.avatar_media_id <= 0:
            sets.append("avatar_media_id = null")
        else:
            _own_media(body.avatar_media_id, u["login_id"], "avatar")
            sets.append("avatar_media_id = :am"); binds["am"] = body.avatar_media_id
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


# ---------- 이미지 업로드 ----------

@app.post("/media")
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form(...),
    u: dict = Depends(current_user),
) -> dict:
    if kind not in ("avatar", "progress", "post", "receipt"):
        raise HTTPException(400, "잘못된 이미지 종류")
    if (file.content_type or "").lower() not in IMG_MIME:
        raise HTTPException(400, "JPEG · PNG · WebP 이미지만 올릴 수 있습니다")
    if not rate_ok(f"media:{u['login_id']}", 20, 3600):
        raise HTTPException(429, "업로드가 많습니다. 잠시 후 다시 시도해 주세요")
    raw = await file.read(MAX_UPLOAD + 1)
    if not raw:
        raise HTTPException(400, "빈 파일입니다")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "이미지는 8MB 이하여야 합니다")
    used = q1("select count(*) c from healthweb.media where login_id = :v", v=u["login_id"])["c"]
    if used >= MEDIA_QUOTA:
        raise HTTPException(429, "이미지 업로드 한도에 도달했습니다")

    meta = await run_in_threadpool(_process_image, raw, kind)
    mid = insert_id(
        "insert into healthweb.media (login_id, kind, path, thumb_path, width, height, bytes) "
        "values (:l, :k, :p, :t, :w, :h, :b) returning id into :new_id",
        l=u["login_id"], k=kind, p=meta["path"], t=meta["thumb_path"],
        w=meta["width"], h=meta["height"], b=meta["bytes"],
    )
    return {"id": mid, "width": meta["width"], "height": meta["height"],
            **_media_url(meta["path"], meta["thumb_path"])}


@app.delete("/media/{mid}")
def delete_media(mid: int, u: dict = Depends(current_user)) -> dict:
    m = q1(
        "select path, thumb_path from healthweb.media where id = :i and login_id = :v",
        i=mid, v=u["login_id"],
    )
    if m is None:
        raise HTTPException(404, "없는 이미지입니다")
    if q1(
        "select 1 x from healthweb.app_user where avatar_media_id = :i "
        "union all select 1 from healthweb.weight_entry where photo_media_id = :i "
        "union all select 1 from healthweb.post where image_media_id = :i "
        "union all select 1 from healthweb.purchase_item where source_media_id = :i "
        "union all select 1 from healthweb.purchase_item where thumb_media_id = :i",
        i=mid,
    ):
        raise HTTPException(400, "사용 중인 이미지입니다. 글·기록에서 먼저 빼주세요")
    dml("delete from healthweb.media where id = :i", i=mid)
    _unlink_media(m["path"], m["thumb_path"])
    return {"ok": True}


@app.get("/media/{key:path}")
def serve_media(key: str) -> FileResponse:
    if ".." in key or key.startswith(("/", "\\")):
        raise HTTPException(404, "없는 파일입니다")
    fp = (MEDIA_DIR / key).resolve()
    if not str(fp).startswith(str(_MEDIA_ROOT)) or not fp.is_file():
        raise HTTPException(404, "없는 파일입니다")
    return FileResponse(
        fp, media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---------- 몸무게 ----------

@app.get("/weights")
def list_weights(u: dict = Depends(current_user)) -> dict:
    rows = qall(
        "select we.id, to_char(we.logged_at,'YYYY-MM-DD') d, to_char(we.logged_at,'HH24:MI:SS') t, "
        "we.weight, we.note, m.path img, m.thumb_path img_t "
        "from healthweb.weight_entry we "
        "left join healthweb.media m on m.id = we.photo_media_id "
        "where we.login_id = :v order by we.logged_at",
        v=u["login_id"],
    )
    entries = [
        {"id": r["id"], "date": r["d"], "time": r["t"], "weight": float(r["weight"]),
         "note": r["note"], "photo": _media_url(r["img"], r["img_t"])}
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
    photo = _own_media(body.photo_media_id, u["login_id"], "progress", "post")
    if photo and not body.share:
        raise HTTPException(400, "사진은 글로 공유할 때만 첨부할 수 있습니다")

    entry_id = insert_id(
        "insert into healthweb.weight_entry (login_id, logged_at, weight, note, photo_media_id) "
        "values (:l, :d, :w, :n, :m) returning id into :new_id",
        l=u["login_id"], d=logged, w=body.weight, n=note, m=photo,
    )
    post_id = None
    if body.share:
        post_id = insert_id(
            "insert into healthweb.post (login_id, kind, body, weight_entry_id, image_media_id) "
            "values (:l, 'casual', :b, :e, :m) returning id into :new_id",
            l=u["login_id"], b=note or "오늘도 기록했어요.", e=entry_id, m=photo,
        )
    _refresh_rank(u["login_id"])
    return {"id": entry_id, "post_id": post_id}


@app.delete("/weights/{entry_id}")
def del_weight(entry_id: int, u: dict = Depends(current_user)) -> dict:
    owned = q1(
        "select 1 as x from healthweb.weight_entry where id = :i and login_id = :v",
        i=entry_id, v=u["login_id"],
    )
    if owned is None:
        raise HTTPException(404, "기록을 찾을 수 없습니다")
    photo = q1("select photo_media_id from healthweb.weight_entry where id = :i", i=entry_id)
    dml("update healthweb.post set weight_entry_id = null where weight_entry_id = :i", i=entry_id)
    dml("delete from healthweb.weight_entry where id = :i", i=entry_id)
    _gc_media(photo["photo_media_id"] if photo else None)
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
        "pinned": bool(r.get("pinned")),
        "image": _media_url(r.get("img_path"), r.get("img_thumb")),
        "avatar": _media_url(r.get("av_path"), r.get("av_thumb")),
        "rank_level": r.get("rank_level"),
    }
    if r.get("weight") is not None and r.get("weight_privacy") == "public":
        out["weight"] = float(r["weight"])
    return out


FEED_SQL = """
    select p.id, au.name, p.kind, p.body, p.created_at,
           we.weight, au.weight_privacy, au.rank_level,
           pm.path img_path, pm.thumb_path img_thumb,
           am.path av_path, am.thumb_path av_thumb,
           case when p.login_id = :viewer then 1 else 0 end mine,
           case when au.pinned_post_id = p.id then 1 else 0 end pinned,
           (select count(*) from healthweb.encouragement e where e.post_id = p.id) enc_count,
           (select count(*) from healthweb.post_comment c where c.post_id = p.id) cmt_count,
           (select count(*) from healthweb.encouragement e where e.post_id = p.id and e.login_id = :viewer) i_enc
    from healthweb.post p
    join healthweb.app_user au on au.login_id = p.login_id
    left join healthweb.weight_entry we on we.id = p.weight_entry_id
    left join healthweb.media pm on pm.id = p.image_media_id
    left join healthweb.media am on am.id = au.avatar_media_id
    where {block}
    {and_where}
    order by p.id desc
    fetch first :lim rows only
""".replace("{block}", BLOCK_FILTER.strip())


@app.get("/feed")
def feed(
    u: dict = Depends(current_user),
    cursor: Optional[int] = None,
    limit: int = 20,
    scope: str = "following",
) -> dict:
    limit = max(1, min(limit, 50))
    conds = []
    binds = {"viewer": u["login_id"], "lim": limit}
    if scope == "following":
        conds.append(
            "(p.login_id = :viewer or p.login_id in "
            "(select followee from healthweb.follow where follower = :viewer))"
        )
    if cursor:
        conds.append("p.id < :cur")
        binds["cur"] = cursor
    and_where = ("and " + " and ".join(conds)) if conds else ""
    rows = qall(FEED_SQL.format(and_where=and_where), **binds)
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
    iid = _own_media(body.image_media_id, u["login_id"], "post", "progress")
    pid = insert_id(
        "insert into healthweb.post (login_id, kind, body, weight_entry_id, image_media_id) "
        "values (:l, :k, :b, :e, :m) returning id into :new_id",
        l=u["login_id"], k=body.kind, b=text, e=eid, m=iid,
    )
    return {"id": pid}


@app.patch("/posts/{post_id}")
def edit_post(post_id: int, body: PostPatch, u: dict = Depends(current_user)) -> dict:
    owned = q1(
        "select 1 as x from healthweb.post where id = :p and login_id = :l",
        p=post_id, l=u["login_id"],
    )
    if owned is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    text = body.body.strip()
    if not (1 <= len(text) <= 2000):
        raise HTTPException(400, "본문은 1–2000자입니다")
    sets, binds = ["body = :b"], {"b": text, "p": post_id}
    if body.kind is not None:
        if body.kind not in POST_KINDS:
            raise HTTPException(400, "잘못된 글 종류")
        sets.append("kind = :k")
        binds["k"] = body.kind
    dml(f"update healthweb.post set {', '.join(sets)} where id = :p", **binds)
    return {"ok": True}


@app.get("/posts/{post_id}")
def get_post(post_id: int, u: dict = Depends(current_user)) -> dict:
    rows = qall(FEED_SQL.format(and_where="and p.id = :pid"), viewer=u["login_id"], lim=1, pid=post_id)
    if not rows:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    post = _post_row(rows[0])
    comments = qall(
        "select c.id, au.name, c.body, c.created_at, m.thumb_path av_thumb, m.path av_path, "
        "case when c.login_id = :viewer then 1 else 0 end mine "
        "from healthweb.post_comment c join healthweb.app_user au on au.login_id = c.login_id "
        "left join healthweb.media m on m.id = au.avatar_media_id "
        "where c.post_id = :p order by c.id",
        p=post_id, viewer=u["login_id"],
    )
    post["comments"] = [
        {"id": c["id"], "name": c["name"], "body": c["body"],
         "created_at": iso_z(c["created_at"]), "mine": bool(c["mine"]),
         "avatar": _media_url(c["av_path"], c["av_thumb"])}
        for c in comments
    ]
    return post


@app.post("/posts/{post_id}/encourage")
def encourage(post_id: int, u: dict = Depends(current_user)) -> dict:
    author = q1("select login_id from healthweb.post where id = :p", p=post_id)
    if author is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    try:
        dml(
            "insert into healthweb.encouragement (post_id, login_id) values (:p, :l)",
            p=post_id, l=u["login_id"],
        )
        notify(author["login_id"], "encourage", u["login_id"], post_id)
    except oracledb.IntegrityError:
        pass
    return {"ok": True}


@app.delete("/posts/{post_id}/encourage")
def unencourage(post_id: int, u: dict = Depends(current_user)) -> dict:
    dml(
        "delete from healthweb.encouragement where post_id = :p and login_id = :l",
        p=post_id, l=u["login_id"],
    )
    dml(
        "delete from healthweb.notification where kind = 'encourage' and post_id = :p "
        "and actor = :l and read_at is null",
        p=post_id, l=u["login_id"],
    )
    return {"ok": True}


@app.post("/posts/{post_id}/comments")
def add_comment(post_id: int, body: CommentIn, u: dict = Depends(current_user)) -> dict:
    text = body.body.strip()
    if not (1 <= len(text) <= 1000):
        raise HTTPException(400, "댓글은 1–1000자입니다")
    author = q1("select login_id from healthweb.post where id = :p", p=post_id)
    if author is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    cid = insert_id(
        "insert into healthweb.post_comment (post_id, login_id, body) "
        "values (:p, :l, :b) returning id into :new_id",
        p=post_id, l=u["login_id"], b=text,
    )
    notify(author["login_id"], "comment", u["login_id"], post_id)
    return {"id": cid}


def _purge_post(post_id: int) -> None:
    """글과 딸린 행(댓글·응원·알림·고정·이미지) 정리. 소유권 확인은 호출자 책임."""
    img = q1("select image_media_id from healthweb.post where id = :p", p=post_id)
    dml("delete from healthweb.post_comment where post_id = :p", p=post_id)
    dml("delete from healthweb.encouragement where post_id = :p", p=post_id)
    dml("delete from healthweb.notification where post_id = :p", p=post_id)
    dml("update healthweb.app_user set pinned_post_id = null where pinned_post_id = :p", p=post_id)
    dml("delete from healthweb.post where id = :p", p=post_id)
    _gc_media(img["image_media_id"] if img else None)  # weight_entry 가 아직 참조하면 남김


@app.delete("/posts/{post_id}")
def delete_post(post_id: int, u: dict = Depends(current_user)) -> dict:
    owned = q1("select 1 as x from healthweb.post where id = :p and login_id = :l", p=post_id, l=u["login_id"])
    if owned is None:
        raise HTTPException(404, "글을 찾을 수 없습니다")
    _purge_post(post_id)
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


def _longest_streak(day_strs: list[str]) -> int:
    """'YYYY-MM-DD' 문자열 목록에서 역대 최장 연속 구간 길이."""
    if not day_strs:
        return 0
    days = sorted({dt.datetime.strptime(s, "%Y-%m-%d").date() for s in day_strs})
    best = cur = 1
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def _rank_score(login_id: str) -> int:
    days = qall(
        "select distinct to_char(logged_at,'YYYY-MM-DD') d from healthweb.weight_entry where login_id = :v",
        v=login_id,
    )
    day_list = [r["d"] for r in days]
    chal = qall(
        "select ch.target_days, count(cc.check_date) checkins "
        "from healthweb.challenge_member cm "
        "join healthweb.challenge ch on ch.id = cm.challenge_id "
        "left join healthweb.challenge_checkin cc "
        "  on cc.challenge_id = ch.id and cc.login_id = cm.login_id "
        "where cm.login_id = :v group by ch.id, ch.target_days",
        v=login_id,
    )
    total_checkins = sum(r["checkins"] or 0 for r in chal)
    completed = sum(1 for r in chal if (r["checkins"] or 0) >= r["target_days"])
    return (
        len(day_list) * RANK_W_DAY
        + _longest_streak(day_list) * RANK_W_STREAK
        + completed * RANK_W_COMPLETE
        + total_checkins * RANK_W_CHECKIN
    )


def _rank_level(score: int) -> int:
    level = 1
    for threshold, lvl in RANK_THRESHOLDS:
        if score >= threshold:
            level = lvl
    return level


def _refresh_rank(login_id: str) -> None:
    """점수·등급 재계산. 등급은 절대 내려가지 않는다 — 실제 계산값이 이전 저장값보다 낮으면 무시."""
    score = _rank_score(login_id)
    prev = q1(
        "select rank_score, rank_level from healthweb.app_user where login_id = :v", v=login_id
    )
    prev_score = prev["rank_score"] if prev else 0
    prev_level = prev["rank_level"] if prev else 1
    if score <= prev_score:
        return
    level = _rank_level(score)
    dml(
        "update healthweb.app_user set rank_score = :s, rank_level = :l where login_id = :v",
        s=score, l=level, v=login_id,
    )
    if level > prev_level:
        dml(
            "insert into healthweb.notification (login_id, kind, actor, post_id, rank_level) "
            "values (:v, 'rank', :v, null, :l)",
            v=login_id, l=level,
        )
        if TG_TOKEN:
            row = q1("select tg_chat_id from healthweb.app_user where login_id = :v", v=login_id)
            if row and row["tg_chat_id"] is not None:
                text = f"\U0001f389 {RANK_NAMES[level]} 등급이 되었어요!\n{WEB_APP_URL}/me"
                threading.Thread(target=_push_worker, args=(int(row["tg_chat_id"]), text), daemon=True).start()


@app.get("/u/{handle}")
def profile(handle: str, u: dict = Depends(current_user)) -> dict:
    p = q1(
        "select au.login_id, au.name, au.bio, au.link, au.location, au.pinned_post_id, "
        "au.target_weight, au.weight_privacy, au.created_at, au.rank_level, au.erp_access, "
        "m.path av_path, m.thumb_path av_thumb "
        "from healthweb.app_user au "
        "left join healthweb.media m on m.id = au.avatar_media_id "
        "where lower(au.name) = lower(:h)",
        h=" ".join(handle.split()),
    )
    if p is None:
        raise HTTPException(404, "없는 사용자입니다")

    pl = p["login_id"]
    me = u["login_id"]
    if pl != me:
        i_blocked = q1(
            "select 1 x from healthweb.user_block where blocker = :me and blocked = :v", me=me, v=pl
        ) is not None
        if i_blocked:
            return {"name": p["name"], "blocked_by_me": True}
        if q1("select 1 x from healthweb.user_block where blocker = :v and blocked = :me", me=me, v=pl):
            raise HTTPException(404, "없는 사용자입니다")

    out = {
        "name": p["name"],
        "bio": p["bio"],
        "link": p["link"],
        "location": p["location"],
        "avatar": _media_url(p["av_path"], p["av_thumb"]),
        "created_at": iso_z(p["created_at"]),
        "weight_privacy": p["weight_privacy"],
        "streak": _streak(pl),
        "rank_level": p["rank_level"],
        "rank_name": RANK_NAMES[p["rank_level"]],
        "mine": pl == me,
        **({"erp_access": bool(p["erp_access"])} if OWNER_LOGIN_ID and me == OWNER_LOGIN_ID else {}),
        "post_count": q1("select count(*) c from healthweb.post where login_id = :v", v=pl)["c"],
        "challenge_count": q1(
            "select count(*) c from healthweb.challenge_member where login_id = :v", v=pl
        )["c"],
        "followers": q1("select count(*) c from healthweb.follow where followee = :v", v=pl)["c"],
        "following": q1("select count(*) c from healthweb.follow where follower = :v", v=pl)["c"],
        "i_follow": q1(
            "select 1 x from healthweb.follow where follower = :me and followee = :v",
            me=me, v=pl,
        ) is not None,
    }
    if p["weight_privacy"] in ("trend", "public"):
        recent = qall(
            "select weight, logged_at from healthweb.weight_entry where login_id = :v "
            "order by logged_at desc fetch first 30 rows only",
            v=pl,
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
                out["trend_series"] = [float(r["weight"]) for r in reversed(recent)]
                if p["target_weight"] is not None:
                    out["target_weight"] = float(p["target_weight"])

    pinned_id = p["pinned_post_id"]
    if pinned_id is not None:
        pin = qall(
            FEED_SQL.format(and_where="and p.id = :pp"),
            viewer=me, lim=1, pp=pinned_id,
        )
        out["pinned"] = _post_row(pin[0]) if pin else None
    posts = qall(
        FEED_SQL.format(and_where="and p.login_id = :pl"),
        viewer=me, lim=30, pl=pl,
    )
    out["posts"] = [_post_row(r) for r in posts if r["id"] != pinned_id]
    return out


# ---------- 팔로우 ----------

def _login_id_by_name(name: str) -> str:
    row = q1(
        "select login_id from healthweb.app_user where lower(name) = lower(:h)",
        h=" ".join(name.split()),
    )
    if row is None:
        raise HTTPException(404, "없는 사용자입니다")
    return row["login_id"]


@app.post("/u/{handle}/follow")
def follow(handle: str, u: dict = Depends(current_user)) -> dict:
    target = _login_id_by_name(handle)
    if target == u["login_id"]:
        raise HTTPException(400, "자기 자신은 팔로우할 수 없습니다")
    if is_blocked(u["login_id"], target):
        raise HTTPException(403, "차단된 사용자입니다")
    try:
        dml(
            "insert into healthweb.follow (follower, followee) values (:me, :t)",
            me=u["login_id"], t=target,
        )
        notify(target, "follow", u["login_id"])
    except oracledb.IntegrityError:
        pass
    return {"ok": True}


@app.delete("/u/{handle}/follow")
def unfollow(handle: str, u: dict = Depends(current_user)) -> dict:
    target = _login_id_by_name(handle)
    dml(
        "delete from healthweb.follow where follower = :me and followee = :t",
        me=u["login_id"], t=target,
    )
    return {"ok": True}


@app.get("/u/{handle}/{rel}")
def follow_list(handle: str, rel: str, u: dict = Depends(current_user)) -> dict:
    if rel not in ("followers", "following"):
        raise HTTPException(404, "not found")
    lid = _login_id_by_name(handle)
    col, other = ("followee", "follower") if rel == "followers" else ("follower", "followee")
    rows = qall(
        "select au.name, "
        "case when exists (select 1 from healthweb.follow x "
        "  where x.follower = :me and x.followee = au.login_id) then 1 else 0 end i_follow "
        "from healthweb.follow f join healthweb.app_user au on au.login_id = f." + other + " "
        "where f." + col + " = :lid order by f.created_at desc",
        me=u["login_id"], lid=lid,
    )
    return {"users": [{"name": r["name"], "i_follow": bool(r["i_follow"])} for r in rows]}


@app.post("/u/{handle}/block")
def block_user(handle: str, u: dict = Depends(current_user)) -> dict:
    target = _login_id_by_name(handle)
    if target == u["login_id"]:
        raise HTTPException(400, "자기 자신은 차단할 수 없습니다")
    try:
        dml(
            "insert into healthweb.user_block (blocker, blocked) values (:me, :t)",
            me=u["login_id"], t=target,
        )
    except oracledb.IntegrityError:
        pass
    # 차단하면 서로 팔로우 해제
    dml(
        "delete from healthweb.follow where (follower = :me and followee = :t) "
        "or (follower = :t and followee = :me)",
        me=u["login_id"], t=target,
    )
    return {"ok": True}


@app.delete("/u/{handle}/block")
def unblock_user(handle: str, u: dict = Depends(current_user)) -> dict:
    target = _login_id_by_name(handle)
    dml(
        "delete from healthweb.user_block where blocker = :me and blocked = :t",
        me=u["login_id"], t=target,
    )
    return {"ok": True}


# ---------- 검색 ----------

@app.get("/search")
def search(q: str, request: Request, u: dict = Depends(current_user)) -> dict:
    term = q.strip()
    if len(term) < 2:
        raise HTTPException(400, "두 글자 이상 입력하세요")
    if not rate_ok(f"search:{ip(request)}", 30, 60):
        raise HTTPException(429, "검색이 많습니다. 잠시 후 다시 시도해 주세요")
    me = u["login_id"]
    arg = like_arg(term)

    users = qall(
        "select au.name, au.bio, m.path av_path, m.thumb_path av_thumb, "
        "case when exists (select 1 from healthweb.follow f "
        "  where f.follower = :me and f.followee = au.login_id) then 1 else 0 end i_follow "
        "from healthweb.app_user au "
        "left join healthweb.media m on m.id = au.avatar_media_id "
        "where lower(au.name) like :arg escape '\\' "
        "and au.login_id not in ("
        "  select blocked from healthweb.user_block where blocker = :me "
        "  union all select blocker from healthweb.user_block where blocked = :me) "
        "order by au.name fetch first 12 rows only",
        me=me, arg=arg,
    )
    challenges = qall(
        "select c.id, c.title, "
        "(select count(*) from healthweb.challenge_member m where m.challenge_id = c.id) member_count, "
        "case when exists (select 1 from healthweb.challenge_member m "
        "  where m.challenge_id = c.id and m.login_id = :me) then 1 else 0 end i_joined "
        "from healthweb.challenge c where lower(c.title) like :arg escape '\\' "
        "order by c.id desc fetch first 12 rows only",
        me=me, arg=arg,
    )
    posts = qall(
        FEED_SQL.format(and_where="and lower(p.body) like :arg escape '\\'"),
        viewer=me, lim=12, arg=arg,
    )
    return {
        "q": term,
        "users": [
            {"name": r["name"], "bio": r["bio"], "i_follow": bool(r["i_follow"]),
             "avatar": _media_url(r["av_path"], r["av_thumb"])}
            for r in users
        ],
        "challenges": [
            {"id": r["id"], "title": r["title"], "member_count": r["member_count"],
             "i_joined": bool(r["i_joined"])}
            for r in challenges
        ],
        "posts": [_post_row(r) for r in posts],
    }


# ---------- 챌린지 (데일리 체크인) ----------

def _challenge_progress(challenge_id: int, login_id: str) -> dict:
    rows = qall(
        "select check_date from healthweb.challenge_checkin "
        "where challenge_id = :c and login_id = :l order by check_date desc",
        c=challenge_id, l=login_id,
    )
    dates = [r["check_date"] for r in rows]
    streak = 0
    if dates:
        have = set(dates)
        cur = dt.datetime.strptime(dates[0], "%Y-%m-%d").date()
        while cur.strftime("%Y-%m-%d") in have:
            streak += 1
            cur -= dt.timedelta(days=1)
    return {"done": len(dates), "streak": streak, "dates": dates}


@app.get("/challenges")
def list_challenges(u: dict = Depends(current_user)) -> dict:
    rows = qall(
        "select c.id, c.title, c.target_days, au.name owner_name, "
        "(select count(*) from healthweb.challenge_member m where m.challenge_id = c.id) member_count, "
        "case when exists (select 1 from healthweb.challenge_member m "
        "  where m.challenge_id = c.id and m.login_id = :me) then 1 else 0 end i_joined "
        "from healthweb.challenge c join healthweb.app_user au on au.login_id = c.owner "
        "order by c.id desc fetch first 50 rows only",
        me=u["login_id"],
    )
    out = []
    for r in rows:
        item = {
            "id": r["id"], "title": r["title"], "target_days": r["target_days"],
            "owner_name": r["owner_name"], "member_count": r["member_count"],
            "i_joined": bool(r["i_joined"]),
        }
        if item["i_joined"]:
            item["progress"] = _challenge_progress(r["id"], u["login_id"])["done"]
        out.append(item)
    return {"items": out}


@app.post("/challenges")
def create_challenge(body: ChallengeIn, u: dict = Depends(current_user)) -> dict:
    title = body.title.strip()
    if not (2 <= len(title) <= 60):
        raise HTTPException(400, "제목은 2–60자입니다")
    if not (1 <= body.target_days <= 365):
        raise HTTPException(400, "목표 일수는 1–365입니다")
    if not rate_ok(f"chal:{u['login_id']}", 5, 3600):
        raise HTTPException(429, "잠시 후 다시 시도해 주세요")
    desc = (body.description or "").strip()[:500] or None
    cid = insert_id(
        "insert into healthweb.challenge (owner, title, description, target_days) "
        "values (:o, :t, :d, :n) returning id into :new_id",
        o=u["login_id"], t=title, d=desc, n=body.target_days,
    )
    dml(
        "insert into healthweb.challenge_member (challenge_id, login_id) values (:c, :l)",
        c=cid, l=u["login_id"],
    )
    return {"id": cid}


@app.get("/challenges/{cid}")
def get_challenge(cid: int, u: dict = Depends(current_user)) -> dict:
    c = q1(
        "select c.id, c.title, c.description, c.target_days, c.owner, au.name owner_name, c.created_at "
        "from healthweb.challenge c join healthweb.app_user au on au.login_id = c.owner where c.id = :c",
        c=cid,
    )
    if c is None:
        raise HTTPException(404, "챌린지를 찾을 수 없습니다")
    members = qall(
        "select m.login_id, au.name from healthweb.challenge_member m "
        "join healthweb.app_user au on au.login_id = m.login_id "
        "where m.challenge_id = :c order by m.joined_at",
        c=cid,
    )
    mine = _challenge_progress(cid, u["login_id"])
    return {
        "id": c["id"], "title": c["title"], "description": c["description"],
        "target_days": c["target_days"], "owner_name": c["owner_name"],
        "mine": c["owner"] == u["login_id"], "created_at": iso_z(c["created_at"]),
        "i_joined": any(m["login_id"] == u["login_id"] for m in members),
        "my_progress": mine["done"], "my_streak": mine["streak"], "my_dates": mine["dates"],
        "members": [
            {"name": m["name"], "progress": _challenge_progress(cid, m["login_id"])["done"],
             "mine": m["login_id"] == u["login_id"]}
            for m in members
        ],
    }


@app.post("/challenges/{cid}/join")
def join_challenge(cid: int, u: dict = Depends(current_user)) -> dict:
    if q1("select 1 x from healthweb.challenge where id = :c", c=cid) is None:
        raise HTTPException(404, "챌린지를 찾을 수 없습니다")
    try:
        dml(
            "insert into healthweb.challenge_member (challenge_id, login_id) values (:c, :l)",
            c=cid, l=u["login_id"],
        )
    except oracledb.IntegrityError:
        pass
    return {"ok": True}


@app.delete("/challenges/{cid}/leave")
def leave_challenge(cid: int, u: dict = Depends(current_user)) -> dict:
    dml("delete from healthweb.challenge_checkin where challenge_id = :c and login_id = :l",
        c=cid, l=u["login_id"])
    dml("delete from healthweb.challenge_member where challenge_id = :c and login_id = :l",
        c=cid, l=u["login_id"])
    return {"ok": True}


@app.post("/challenges/{cid}/checkin")
def checkin(cid: int, body: CheckinIn, u: dict = Depends(current_user)) -> dict:
    d = body.date.strip()
    if not DATE_RE.match(d):
        raise HTTPException(400, "날짜 형식이 올바르지 않습니다")
    if q1("select 1 x from healthweb.challenge_member where challenge_id = :c and login_id = :l",
          c=cid, l=u["login_id"]) is None:
        raise HTTPException(400, "먼저 챌린지에 참여하세요")
    try:
        dml(
            "insert into healthweb.challenge_checkin (challenge_id, login_id, check_date) "
            "values (:c, :l, :d)",
            c=cid, l=u["login_id"], d=d,
        )
        _refresh_rank(u["login_id"])
    except oracledb.IntegrityError:
        pass
    return _challenge_progress(cid, u["login_id"])


@app.delete("/challenges/{cid}/checkin/{date}")
def uncheckin(cid: int, date: str, u: dict = Depends(current_user)) -> dict:
    dml(
        "delete from healthweb.challenge_checkin where challenge_id = :c and login_id = :l and check_date = :d",
        c=cid, l=u["login_id"], d=date,
    )
    return _challenge_progress(cid, u["login_id"])


# ---------- 공개 챌린지 페이지 (로그인 불필요) ----------

@app.get("/c/{cid}")
def public_challenge(cid: int, request: Request) -> dict:
    if not rate_ok(f"pubc:{ip(request)}", 60, 60):
        raise HTTPException(429, "요청이 많습니다")
    c = q1(
        "select c.id, c.title, c.description, c.target_days, au.name owner_name, c.created_at "
        "from healthweb.challenge c join healthweb.app_user au on au.login_id = c.owner "
        "where c.id = :c",
        c=cid,
    )
    if c is None:
        raise HTTPException(404, "챌린지를 찾을 수 없습니다")
    member_count = q1(
        "select count(*) n from healthweb.challenge_member where challenge_id = :c", c=cid
    )["n"]
    week_ago = (dt.date.today() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    active = q1(
        "select count(distinct login_id) n from healthweb.challenge_checkin "
        "where challenge_id = :c and check_date >= :d",
        c=cid, d=week_ago,
    )["n"]
    members = qall(
        "select au.name from healthweb.challenge_member m "
        "join healthweb.app_user au on au.login_id = m.login_id "
        "where m.challenge_id = :c order by m.joined_at fetch first 8 rows only",
        c=cid,
    )
    return {
        "id": c["id"], "title": c["title"], "description": c["description"],
        "target_days": c["target_days"], "owner_name": c["owner_name"],
        "created_at": iso_z(c["created_at"]),
        "member_count": member_count, "active_this_week": active,
        "sample_members": [m["name"] for m in members],
    }


# ---------- 알림 ----------

def _announcement_row(r: dict, admin: bool = False) -> dict:
    out = {
        "id": r["id"],
        "title": r["title"],
        "body": r["body"],
        "link": r["link"],
        "starts_at": iso_z(r["starts_at"]) if r["starts_at"] else None,
        "ends_at": iso_z(r["ends_at"]) if r["ends_at"] else None,
        "created_at": iso_z(r["created_at"]),
    }
    if admin:
        now = utcnow()
        if r["starts_at"] and r["starts_at"] > now:
            out["state"] = "scheduled"
        elif r["ends_at"] and r["ends_at"] < now:
            out["state"] = "expired"
        else:
            out["state"] = "live"
    return out


def _active_announcements() -> list[dict]:
    rows = qall(
        "select id, title, body, link, starts_at, ends_at, created_at "
        "from healthweb.announcement "
        "where (starts_at is null or starts_at <= :now) "
        "  and (ends_at is null or ends_at >= :now) "
        "order by id desc fetch first 3 rows only",
        now=utcnow(),
    )
    return [_announcement_row(r) for r in rows]


@app.get("/notifications")
def notifications(u: dict = Depends(current_user), cursor: Optional[int] = None, limit: int = 30) -> dict:
    limit = max(1, min(limit, 50))
    where = "and n.id < :cur" if cursor else ""
    binds = {"me": u["login_id"], "lim": limit}
    if cursor:
        binds["cur"] = cursor
    rows = qall(
        "select n.id, n.kind, n.post_id, n.rank_level, n.read_at, n.created_at, au.name actor_name "
        "from healthweb.notification n join healthweb.app_user au on au.login_id = n.actor "
        "where n.login_id = :me " + where + " "
        "and n.actor not in ("
        "  select blocked from healthweb.user_block where blocker = :me "
        "  union all select blocker from healthweb.user_block where blocked = :me) "
        "order by n.id desc fetch first :lim rows only",
        **binds,
    )
    items = [
        {"id": r["id"], "kind": r["kind"], "post_id": r["post_id"], "rank_level": r["rank_level"],
         "actor_name": r["actor_name"], "read": r["read_at"] is not None,
         "created_at": iso_z(r["created_at"])}
        for r in rows
    ]
    out = {"items": items, "next_cursor": items[-1]["id"] if len(items) == limit else None}
    if not cursor:  # 첫 페이지에만 공지
        out["announcements"] = _active_announcements()
    return out


@app.get("/notifications/unread-count")
def unread_count(u: dict = Depends(current_user)) -> dict:
    row = q1(
        "select count(*) c from healthweb.notification where login_id = :me and read_at is null",
        me=u["login_id"],
    )
    return {"count": row["c"]}


@app.post("/notifications/read")
def mark_read(u: dict = Depends(current_user)) -> dict:
    dml(
        "update healthweb.notification set read_at = systimestamp "
        "where login_id = :me and read_at is null",
        me=u["login_id"],
    )
    return {"ok": True}


# ---------- 신고 · 모더레이션 ----------

@app.post("/reports")
def create_report(body: ReportIn, request: Request, u: dict = Depends(current_user)) -> dict:
    if body.target_kind not in ("post", "comment", "user"):
        raise HTTPException(400, "잘못된 신고 대상")
    tid = (body.target_id or "").strip()[:40]
    if not tid:
        raise HTTPException(400, "신고 대상이 없습니다")
    if not rate_ok(f"report:{u['login_id']}", 10, 3600):
        raise HTTPException(429, "신고가 많습니다. 잠시 후 다시 시도해 주세요")

    if body.target_kind == "post":
        exists = q1("select 1 x from healthweb.post where id = :i", i=int(tid)) if tid.isdigit() else None
    elif body.target_kind == "comment":
        exists = q1("select 1 x from healthweb.post_comment where id = :i", i=int(tid)) if tid.isdigit() else None
    else:
        # user 신고는 이름으로 받아 login_id 로 저장
        row = q1(
            "select login_id from healthweb.app_user where lower(name) = lower(:h)",
            h=" ".join(tid.split()),
        )
        exists = row
        if row is not None:
            tid = row["login_id"]
            if tid == u["login_id"]:
                raise HTTPException(400, "자기 자신은 신고할 수 없습니다")
    if exists is None:
        raise HTTPException(404, "신고 대상을 찾을 수 없습니다")

    dup = q1(
        "select 1 x from healthweb.report where reporter = :r and target_kind = :k "
        "and target_id = :t and status = 'open'",
        r=u["login_id"], k=body.target_kind, t=tid,
    )
    if dup is None:
        dml(
            "insert into healthweb.report (reporter, target_kind, target_id, reason) "
            "values (:r, :k, :t, :rs)",
            r=u["login_id"], k=body.target_kind, t=tid,
            rs=(body.reason or "").strip()[:300] or None,
        )
    return {"ok": True}


@app.get("/admin/reports")
def admin_reports(u: dict = Depends(current_user), status: str = "open") -> dict:
    require_owner(u)
    if status not in ("open", "closed"):
        status = "open"
    rows = qall(
        "select r.id, au.name reporter_name, r.target_kind, r.target_id, r.reason, "
        "r.status, r.created_at from healthweb.report r "
        "join healthweb.app_user au on au.login_id = r.reporter "
        "where r.status = :s order by r.id desc fetch first 100 rows only",
        s=status,
    )
    out = []
    for r in rows:
        tid, tk = r["target_id"], r["target_kind"]
        ctx: dict
        if tk == "post" and tid.isdigit():
            p = q1(
                "select p.id, p.body, p.kind, au.name from healthweb.post p "
                "join healthweb.app_user au on au.login_id = p.login_id where p.id = :i",
                i=int(tid),
            )
            ctx = {"gone": True} if p is None else {
                "post_id": p["id"], "author": p["name"], "kind": p["kind"],
                "excerpt": (p["body"] or "")[:160],
            }
        elif tk == "comment" and tid.isdigit():
            cc = q1(
                "select c.id, c.body, c.post_id, au.name from healthweb.post_comment c "
                "join healthweb.app_user au on au.login_id = c.login_id where c.id = :i",
                i=int(tid),
            )
            ctx = {"gone": True} if cc is None else {
                "comment_id": cc["id"], "post_id": cc["post_id"], "author": cc["name"],
                "excerpt": (cc["body"] or "")[:160],
            }
        else:
            uu = q1("select name, bio from healthweb.app_user where login_id = :i", i=tid)
            ctx = {"gone": True} if uu is None else {"name": uu["name"], "bio": uu["bio"]}
        out.append({
            "id": r["id"], "reporter_name": r["reporter_name"], "target_kind": tk,
            "target_id": tid, "reason": r["reason"], "status": r["status"],
            "created_at": iso_z(r["created_at"]), "context": ctx,
        })
    return {"items": out}


@app.post("/admin/reports/{rid}/resolve")
def admin_resolve(rid: int, body: ResolveIn, u: dict = Depends(current_user)) -> dict:
    require_owner(u)
    r = q1(
        "select target_kind, target_id from healthweb.report where id = :i and status = 'open'",
        i=rid,
    )
    if r is None:
        raise HTTPException(404, "없는 신고입니다")
    tk, tid = r["target_kind"], r["target_id"]
    if body.action == "delete_post" and tk == "post" and tid.isdigit():
        if q1("select 1 x from healthweb.post where id = :i", i=int(tid)):
            _purge_post(int(tid))
    elif body.action == "delete_comment" and tk == "comment" and tid.isdigit():
        dml("delete from healthweb.post_comment where id = :i", i=int(tid))
    dml(
        "update healthweb.report set status = 'closed' "
        "where target_kind = :k and target_id = :t and status = 'open'",
        k=tk, t=tid,
    )
    return {"ok": True}


# ---------- 관리자 공지 ----------

def _announce_fields(body: AnnouncementIn) -> dict:
    text = (body.body or "").strip()
    if not (1 <= len(text) <= 1000):
        raise HTTPException(400, "공지 본문은 1–1000자입니다")
    title = (body.title or "").strip()[:80] or None
    link = clean_link(body.link) if body.link else None
    starts = parse_iso_utc(body.starts_at)
    ends = parse_iso_utc(body.ends_at)
    if starts and ends and ends < starts:
        raise HTTPException(400, "종료일이 시작일보다 빠릅니다")
    return {"title": title, "body": text, "link": link, "starts": starts, "ends": ends}


@app.get("/admin/announcements")
def admin_announcements(u: dict = Depends(current_user)) -> dict:
    require_owner(u)
    rows = qall(
        "select id, title, body, link, starts_at, ends_at, created_at "
        "from healthweb.announcement order by id desc",
    )
    return {"items": [_announcement_row(r, admin=True) for r in rows]}


@app.post("/admin/announcements")
def create_announcement(body: AnnouncementIn, u: dict = Depends(current_user)) -> dict:
    require_owner(u)
    f = _announce_fields(body)
    aid = insert_id(
        "insert into healthweb.announcement (title, body, link, starts_at, ends_at, created_by) "
        "values (:t, :b, :l, :s, :e, :o) returning id into :new_id",
        t=f["title"], b=f["body"], l=f["link"], s=f["starts"], e=f["ends"], o=u["login_id"],
    )
    return {"id": aid}


@app.patch("/admin/announcements/{aid}")
def update_announcement(aid: int, body: AnnouncementIn, u: dict = Depends(current_user)) -> dict:
    require_owner(u)
    if q1("select 1 x from healthweb.announcement where id = :i", i=aid) is None:
        raise HTTPException(404, "없는 공지입니다")
    f = _announce_fields(body)
    dml(
        "update healthweb.announcement set title = :t, body = :b, link = :l, "
        "starts_at = :s, ends_at = :e where id = :i",
        t=f["title"], b=f["body"], l=f["link"], s=f["starts"], e=f["ends"], i=aid,
    )
    return {"ok": True}


@app.delete("/admin/announcements/{aid}")
def delete_announcement(aid: int, u: dict = Depends(current_user)) -> dict:
    require_owner(u)
    dml("delete from healthweb.announcement where id = :i", i=aid)
    return {"ok": True}


# ---------- 텔레그램 알림 (옵트인) ----------

def _gen_code() -> str:
    return "HW-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def require_internal(x_internal_key: str = Header(default="")) -> None:
    if not INTERNAL_KEY or x_internal_key != INTERNAL_KEY:
        raise HTTPException(401, "unauthorized")


@app.post("/push/telegram/code")
def tg_code(request: Request, u: dict = Depends(current_user)) -> dict:
    if not TG_TOKEN:
        raise HTTPException(503, "텔레그램 알림이 아직 준비되지 않았습니다")
    if not rate_ok(f"tgcode:{u['login_id']}", 5, 3600):
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요")
    dml("delete from healthweb.tg_link_code where login_id = :l", l=u["login_id"])
    code = _gen_code()
    dml(
        "insert into healthweb.tg_link_code (code, login_id, created_at) values (:c, :l, :t)",
        c=code, l=u["login_id"], t=utcnow(),
    )
    return {"code": code, "deep_link": f"https://t.me/{TG_BOT_USERNAME}?start={code}"}


@app.get("/push/telegram")
def tg_status(u: dict = Depends(current_user)) -> dict:
    return {"linked": u["tg_chat_id"] is not None, "available": bool(TG_TOKEN)}


@app.delete("/push/telegram")
def tg_unlink(u: dict = Depends(current_user)) -> dict:
    dml("update healthweb.app_user set tg_chat_id = null where login_id = :l", l=u["login_id"])
    return {"ok": True}


@app.post("/internal/telegram/link")
def internal_tg_link(body: TgLinkIn, _: None = Depends(require_internal)) -> dict:
    row = q1(
        "select login_id from healthweb.tg_link_code where code = :c and created_at > :cut",
        c=body.code.strip().upper(), cut=utcnow() - dt.timedelta(minutes=10),
    )
    if row is None:
        raise HTTPException(404, "코드가 유효하지 않거나 만료되었습니다")
    lid = row["login_id"]
    dml("update healthweb.app_user set tg_chat_id = null where tg_chat_id = :cid", cid=body.chat_id)
    dml("update healthweb.app_user set tg_chat_id = :cid where login_id = :l", cid=body.chat_id, l=lid)
    dml("delete from healthweb.tg_link_code where login_id = :l", l=lid)
    name = q1("select name from healthweb.app_user where login_id = :l", l=lid)["name"]
    return {"ok": True, "name": name}


@app.post("/internal/telegram/unlink")
def internal_tg_unlink(body: TgUnlinkIn, _: None = Depends(require_internal)) -> dict:
    n = dml("update healthweb.app_user set tg_chat_id = null where tg_chat_id = :cid", cid=body.chat_id)
    return {"ok": True, "unlinked": n > 0}


# ---------- ERP (구매 기록, 오너가 지정한 사용자만) ----------

EXTRACT_PROMPT = """이 이미지는 쇼핑몰(타오바오 등) 주문 내역 화면입니다. 보이는 모든 상품 줄을 찾아
아래 JSON 형식으로만 답하세요. 다른 설명은 절대 붙이지 마세요.

{"items": [
  {"shop_name": "상점 이름(한국어로 번역) 또는 null", "product_name": "상품명(한국어로 번역)", "option_text": "색상·사이즈 등 옵션(한국어로 번역) 또는 null",
   "quantity": 수량(숫자), "price_cny": 단가(위안화, 숫자만, 통화기호 제외),
   "box_2d": [상품 대표 사진(썸네일) 영역의 ymin,xmin,ymax,xmax] (0~1000 정규화 정수 4개) 또는 null}
]}

원문이 중국어 등 외국어여도 shop_name·product_name·option_text 는 반드시 자연스러운 한국어로 번역해서 넣으세요(고유명사·브랜드명은 음차 가능).
quantity 는 화면에 실제로 표시된 구매 수량입니다 — "수량: 2", "x2", "×3", "2개", "2件" 등 어떤 표기든 찾아서 숫자만 반환하세요.
표시가 전혀 안 보이면 1로 하세요. quantity 를 문자열이 아닌 순수 정수로 답하세요.
box_2d 는 그 상품 줄에 있는 상품 사진(텍스트가 아닌 실제 이미지) 영역만 가리켜야 하며, 사진을 찾을 수 없으면 null 로 하세요.
상품을 하나도 못 찾으면 {"items": []} 로 답하세요. price_cny 는 반드시 숫자(예: 19.9)로, 못 읽으면 null."""

MAX_EXTRACT_ITEMS = 20  # 폭탄 이미지 방지용 상한 — 크롭·미디어 생성 개수 제한


def _extract_purchase_items(raw: bytes, mime: str) -> list[dict]:
    """동기 함수 — run_in_threadpool 로 호출."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=genai_types.HttpOptions(timeout=30_000, retry_options=genai_types.HttpRetryOptions(attempts=2)),
    )
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[genai_types.Part.from_bytes(data=raw, mime_type=mime), EXTRACT_PROMPT],
        config=genai_types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    data = json.loads(resp.text)
    items = data.get("items")
    return items if isinstance(items, list) else []


def _parse_qty(v: Any) -> int:
    """Gemini가 정수/실수/문자열("2개" 등) 어떤 형태로 주든 수량을 최대한 살려서 파싱. 실패 시 1."""
    try:
        n = int(float(v))
        return n if n > 0 else 1
    except (TypeError, ValueError):
        m = re.search(r"\d+", str(v or ""))
        return int(m.group()) if m else 1


def _fx_cny_to_krw() -> Optional[float]:
    """CNY->KRW 환율. 실패하면 None(원화 환산 없이 위안화만 저장)."""
    try:
        req = urllib.request.Request("https://open.er-api.com/v6/latest/CNY")
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        rate = data.get("rates", {}).get("KRW")
        return float(rate) if rate else None
    except Exception:
        return None


def _crop_purchase_thumb(raw: bytes, box: Any, login_id: str) -> Optional[dict]:
    """box_2d([ymin,xmin,ymax,xmax], 0~1000 정규화)로 원본에서 상품 사진만 잘라 media 로 저장.
    성공하면 {"id","path"}, 실패·유효하지 않은 box 면 None. 동기 함수 — run_in_threadpool 로 호출."""
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    if not (0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000):
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        x0, y0 = round(xmin / 1000 * w), round(ymin / 1000 * h)
        x1, y1 = round(xmax / 1000 * w), round(ymax / 1000 * h)
        if x1 - x0 < 16 or y1 - y0 < 16:
            return None
        crop = im.crop((x0, y0, x1, y1))
        crop.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        token = secrets.token_hex(16)
        key = f"{token[:2]}/{token}.jpg"
        (MEDIA_DIR / key).parent.mkdir(parents=True, exist_ok=True)
        b = io.BytesIO()
        crop.save(b, "JPEG", quality=80, optimize=True)
        (MEDIA_DIR / key).write_bytes(b.getvalue())
    except Exception:
        return None
    mid = insert_id(
        "insert into healthweb.media (login_id, kind, path, thumb_path, width, height, bytes) "
        "values (:l, 'item_thumb', :p, :p, :w, :h, :b) returning id into :new_id",
        l=login_id, p=key, w=crop.width, h=crop.height, b=len(b.getvalue()),
    )
    return {"id": mid, "path": key}


@app.patch("/admin/users/{handle}/erp-access")
def set_erp_access(handle: str, body: ErpAccessIn, u: dict = Depends(current_user)) -> dict:
    require_owner(u)
    row = q1(
        "select login_id from healthweb.app_user where lower(name) = lower(:h)",
        h=" ".join(handle.split()),
    )
    if row is None:
        raise HTTPException(404, "없는 사용자입니다")
    dml(
        "update healthweb.app_user set erp_access = :v where login_id = :l",
        v=1 if body.erp_access else 0, l=row["login_id"],
    )
    return {"ok": True}


@app.post("/purchases/extract")
async def extract_purchase(body: PurchaseExtractIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    if not GEMINI_API_KEY:
        raise HTTPException(503, "AI 추출 기능이 설정되지 않았습니다")
    if not rate_ok(f"extract:{u['login_id']}", 10, 3600):
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요")
    _own_media(body.media_id, u["login_id"], "receipt")
    m = q1("select path from healthweb.media where id = :i", i=body.media_id)
    if m is None:
        raise HTTPException(400, "잘못된 이미지입니다")
    raw = (MEDIA_DIR / m["path"]).read_bytes()

    try:
        raw_items = await run_in_threadpool(_extract_purchase_items, raw, "image/jpeg")
    except Exception:
        raise HTTPException(502, "이미지 분석에 실패했습니다. 다시 시도해 주세요")

    rate = await run_in_threadpool(_fx_cny_to_krw)
    out = []
    for it in raw_items[:MAX_EXTRACT_ITEMS]:
        if not isinstance(it, dict):
            continue
        unit_cny = it.get("price_cny")  # Gemini가 읽어주는 값은 화면에 표시된 단가(위안화)
        try:
            unit_cny = float(unit_cny) if unit_cny is not None else None
        except (TypeError, ValueError):
            unit_cny = None
        qty = _parse_qty(it.get("quantity"))
        # 금액(위안화/원화)은 단가 × 수량의 총액, 단가(원화)는 그 총액을 다시 수량으로 나눈 값 — 구매기능 요건 1
        amount_cny = round(unit_cny * qty, 2) if unit_cny is not None else None
        amount_krw = round(amount_cny * rate, 0) if (amount_cny is not None and rate) else None
        unit_krw = round(amount_krw / qty, 0) if amount_krw is not None else None
        thumb = None
        box = it.get("box_2d")
        if isinstance(box, list) and len(box) == 4:
            thumb = await run_in_threadpool(_crop_purchase_thumb, raw, box, u["login_id"])
        out.append({
            "shop_name": (str(it.get("shop_name")).strip() if it.get("shop_name") else None),
            "product_name": (str(it.get("product_name") or "")).strip()[:300] or "상품",
            "option_text": (str(it.get("option_text")).strip() if it.get("option_text") else None),
            "quantity": qty,
            "price_cny": amount_cny,
            "price_krw": amount_krw,
            "unit_price_krw": unit_krw,
            "fx_rate": rate,
            "thumb_media_id": thumb["id"] if thumb else None,
            "thumb_url": _media_url(thumb["path"])["url"] if thumb else None,
        })
    return {"items": out}


@app.post("/purchases")
def save_purchases(body: PurchaseSaveIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    if not body.items:
        raise HTTPException(400, "저장할 항목이 없습니다")
    order_date = body.order_date.strip()
    if not order_date:
        raise HTTPException(400, "구매일자를 입력해 주세요")
    smid = _own_media(body.source_media_id, u["login_id"], "receipt")
    row = q1(
        "select count(*) c from healthweb.purchase_item where login_id = :l and order_date = :od",
        l=u["login_id"], od=order_date,
    )
    seq = (row["c"] if row else 0) + 1
    date_part = order_date.replace("-", "")
    ids = []
    for it in body.items:
        name = it.product_name.strip()[:300]
        if not name:
            continue
        tmid = _own_media(it.thumb_media_id, u["login_id"], "item_thumb")
        qty = max(1, it.quantity or 1)
        unit_krw = round(it.price_krw / qty, 0) if it.price_krw is not None else None
        purchase_no = f"{date_part}-{seq:03d}"
        pid = insert_id(
            "insert into healthweb.purchase_item "
            "(login_id, purchase_no, shop_name, product_name, option_text, quantity, price_cny, price_krw, unit_price_krw, fx_rate, fx_at, order_date, source_media_id, thumb_media_id) "
            "values (:l, :no, :s, :p, :o, :q, :cny, :krw, :ukrw, :rate, :fa, :od, :m, :t) returning id into :new_id",
            l=u["login_id"], no=purchase_no, s=(it.shop_name or None), p=name, o=(it.option_text or None),
            q=qty, cny=it.price_cny, krw=it.price_krw, ukrw=unit_krw, rate=it.fx_rate,
            fa=utcnow() if it.fx_rate else None, od=order_date, m=smid, t=tmid,
        )
        ids.append(pid)
        seq += 1
    if not ids:
        raise HTTPException(400, "저장할 항목이 없습니다")
    return {"ids": ids}


@app.get("/purchases")
def list_purchases(
    u: dict = Depends(current_user), cursor: Optional[int] = None, limit: int = 30,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    unreceived_only: bool = False,
) -> dict:
    require_erp(u)
    limit = max(1, min(limit, 100))
    conds = ["p.login_id = :l"]
    binds: dict = {"l": u["login_id"]}
    if unreceived_only:
        conds.append("p.received = 0")
    else:
        eff = "coalesce(p.order_date, to_char(p.created_at, 'YYYY-MM-DD'))"
        if date_from:
            conds.append(f"{eff} >= :df"); binds["df"] = date_from
        if date_to:
            conds.append(f"{eff} <= :dt"); binds["dt"] = date_to
    where = " and ".join(conds)

    page_binds = dict(binds, lim=limit)
    page_where = where
    if cursor:
        page_where += " and p.id < :cur"
        page_binds["cur"] = cursor

    rows = qall(
        "select p.id, p.purchase_no, p.shop_name, p.product_name, p.option_text, p.quantity, p.price_cny, p.price_krw, "
        "p.unit_price_krw, p.fx_rate, p.order_date, p.source_media_id, p.received, p.created_at, m.path thumb_path "
        "from healthweb.purchase_item p left join healthweb.media m on m.id = p.thumb_media_id "
        f"where {page_where} order by p.id desc fetch first :lim rows only",
        **page_binds,
    )
    items = [{
        "id": r["id"], "purchase_no": r["purchase_no"], "shop_name": r["shop_name"], "product_name": r["product_name"],
        "option_text": r["option_text"], "quantity": r["quantity"],
        "price_cny": float(r["price_cny"]) if r["price_cny"] is not None else None,
        "price_krw": float(r["price_krw"]) if r["price_krw"] is not None else None,
        "unit_price_krw": float(r["unit_price_krw"]) if r["unit_price_krw"] is not None else None,
        "order_date": r["order_date"], "received": bool(r["received"]),
        "created_at": iso_z(r["created_at"]),
        "thumb_url": _media_url(r["thumb_path"])["url"] if r["thumb_path"] else None,
    } for r in rows]
    total = q1(
        f"select sum(price_krw) s, sum(price_cny) c from healthweb.purchase_item p where {where}",
        **binds,
    )
    return {
        "items": items, "next_cursor": items[-1]["id"] if len(items) == limit else None,
        "total_krw": float(total["s"]) if total and total["s"] is not None else 0,
        "total_cny": float(total["c"]) if total and total["c"] is not None else 0,
    }


@app.patch("/purchases/{pid}")
def update_purchase(pid: int, body: PurchasePatchIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    row = q1(
        "select price_krw from healthweb.purchase_item where id = :i and login_id = :l",
        i=pid, l=u["login_id"],
    )
    if row is None:
        raise HTTPException(404, "없는 기록입니다")
    sets: list[str] = []
    binds: dict = {"i": pid, "l": u["login_id"]}
    if body.received is not None:
        sets.append("received = :r")
        binds["r"] = 1 if body.received else 0
    if body.quantity is not None:
        if body.quantity <= 0:
            raise HTTPException(400, "수량은 1 이상이어야 합니다")
        sold = q1(
            "select coalesce(sum(sale_qty), 0) s from healthweb.sale_item where purchase_item_id = :i",
            i=pid,
        )
        if body.quantity < sold["s"]:
            raise HTTPException(400, "이미 판매·폐기된 수량보다 적게 설정할 수 없습니다")
        sets.append("quantity = :q")
        binds["q"] = body.quantity
        if row["price_krw"] is not None:
            sets.append("unit_price_krw = :u")
            binds["u"] = round(float(row["price_krw"]) / body.quantity, 0)
    if not sets:
        return {"ok": True}
    dml(f"update healthweb.purchase_item set {', '.join(sets)} where id = :i and login_id = :l", **binds)
    return {"ok": True}


@app.delete("/purchases/{pid}")
def delete_purchase(pid: int, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    row = q1(
        "select source_media_id, thumb_media_id from healthweb.purchase_item where id = :i and login_id = :l",
        i=pid, l=u["login_id"],
    )
    if row is None:
        raise HTTPException(404, "없는 기록입니다")
    has_sale = q1("select 1 x from healthweb.sale_item where purchase_item_id = :i and rownum = 1", i=pid)
    if has_sale:
        raise HTTPException(400, "판매 이력이 있어 삭제할 수 없습니다")
    dml("delete from healthweb.purchase_item where id = :i", i=pid)
    _gc_media(row["source_media_id"])
    _gc_media(row["thumb_media_id"])
    return {"ok": True}


# ---------- ERP: 비용 ----------

@app.post("/expenses")
def create_expense(body: ExpenseIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    expense_date = body.expense_date.strip()
    if not expense_date:
        raise HTTPException(400, "비용발생일자를 입력해 주세요")
    item_name = body.item_name.strip()[:200]
    if not item_name:
        raise HTTPException(400, "비용항목을 입력해 주세요")
    pid = body.purchase_item_id
    if pid is not None:
        prow = q1(
            "select 1 x from healthweb.purchase_item where id = :pid and login_id = :l",
            pid=pid, l=u["login_id"],
        )
        if prow is None:
            raise HTTPException(400, "구매ID를 확인해 주세요")
    eid = insert_id(
        "insert into healthweb.expense_item (login_id, expense_date, item_name, amount_krw, purchase_item_id) "
        "values (:l, :d, :n, :a, :pid) returning id into :new_id",
        l=u["login_id"], d=expense_date, n=item_name, a=body.amount_krw, pid=pid,
    )
    return {"id": eid}


@app.get("/expenses")
def list_expenses(
    u: dict = Depends(current_user), date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    require_erp(u)
    conds = ["e.login_id = :l"]
    binds: dict = {"l": u["login_id"]}
    if date_from:
        conds.append("e.expense_date >= :df"); binds["df"] = date_from
    if date_to:
        conds.append("e.expense_date <= :dt"); binds["dt"] = date_to
    where = " and ".join(conds)
    rows = qall(
        f"select e.id, e.expense_date, e.item_name, e.amount_krw, e.created_at, p.purchase_no "
        f"from healthweb.expense_item e left join healthweb.purchase_item p on p.id = e.purchase_item_id "
        f"where {where} order by e.expense_date desc, e.id desc",
        **binds,
    )
    items = [{
        "id": r["id"], "expense_date": r["expense_date"], "item_name": r["item_name"],
        "amount_krw": float(r["amount_krw"]), "created_at": iso_z(r["created_at"]),
        "purchase_no": r["purchase_no"],
    } for r in rows]
    total = q1(f"select sum(e.amount_krw) s from healthweb.expense_item e where {where}", **binds)
    return {"items": items, "total_krw": float(total["s"]) if total and total["s"] is not None else 0}


@app.patch("/expenses/{eid}")
def update_expense(eid: int, body: ExpensePatchIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    row = q1(
        "select 1 x from healthweb.expense_item where id = :i and login_id = :l",
        i=eid, l=u["login_id"],
    )
    if row is None:
        raise HTTPException(404, "없는 기록입니다")
    has_sale = q1("select 1 x from healthweb.sale_item where expense_item_id = :i and rownum = 1", i=eid)
    if has_sale:
        raise HTTPException(400, "폐기로 자동 생성된 비용은 금액을 변경할 수 없습니다")
    n = dml(
        "update healthweb.expense_item set amount_krw = :a where id = :i and login_id = :l",
        a=body.amount_krw, i=eid, l=u["login_id"],
    )
    if not n:
        raise HTTPException(404, "없는 기록입니다")
    return {"ok": True}


@app.delete("/expenses/{eid}")
def delete_expense(eid: int, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    row = q1("select 1 x from healthweb.expense_item where id = :i and login_id = :l", i=eid, l=u["login_id"])
    if row is None:
        raise HTTPException(404, "없는 기록입니다")
    has_sale = q1("select 1 x from healthweb.sale_item where expense_item_id = :i and rownum = 1", i=eid)
    if has_sale:
        raise HTTPException(400, "폐기 비용을 삭제하려면 판매 목록에서 폐기판매를 삭제하세요")
    dml("delete from healthweb.expense_item where id = :i and login_id = :l", i=eid, l=u["login_id"])
    return {"ok": True}


# ---------- ERP: 재고/판매 ----------

@app.get("/stock")
def list_stock(u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    rows = qall(
        "select * from ("
        "  select p.id, p.purchase_no, p.product_name, p.quantity, p.unit_price_krw, m.path thumb_path, "
        "         p.quantity - coalesce(s.sold, 0) as remaining_qty "
        "  from healthweb.purchase_item p "
        "  left join healthweb.media m on m.id = p.thumb_media_id "
        "  left join (select purchase_item_id, sum(sale_qty) sold from healthweb.sale_item group by purchase_item_id) s "
        "    on s.purchase_item_id = p.id "
        "  where p.login_id = :l and p.received = 1"
        ") where remaining_qty > 0 order by id desc",
        l=u["login_id"],
    )
    items = [{
        "purchase_item_id": r["id"], "purchase_no": r["purchase_no"], "product_name": r["product_name"],
        "remaining_qty": r["remaining_qty"],
        "unit_price_krw": float(r["unit_price_krw"]) if r["unit_price_krw"] is not None else None,
        "remaining_amount_krw": (
            float(r["unit_price_krw"]) * r["remaining_qty"] if r["unit_price_krw"] is not None else None
        ),
        "thumb_url": _media_url(r["thumb_path"])["url"] if r["thumb_path"] else None,
    } for r in rows]
    return {"items": items}


@app.post("/sales")
def save_sales(body: SaleSaveIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    sale_date = body.sale_date.strip()
    if not sale_date:
        raise HTTPException(400, "판매일자를 입력해 주세요")
    if not body.items:
        raise HTTPException(400, "판매할 상품을 선택해 주세요")
    ids = []
    for it in body.items:
        row = q1(
            "select quantity, received, unit_price_krw from healthweb.purchase_item "
            "where id = :pid and login_id = :l",
            pid=it.purchase_item_id, l=u["login_id"],
        )
        if row is None or not row["received"]:
            raise HTTPException(404, "없는 재고입니다")
        sold = q1(
            "select coalesce(sum(sale_qty), 0) s from healthweb.sale_item where purchase_item_id = :pid",
            pid=it.purchase_item_id,
        )
        remaining = row["quantity"] - sold["s"]
        if it.sale_qty <= 0 or it.sale_qty > remaining:
            raise HTTPException(400, "판매 수량이 재고 수량을 초과했습니다")
        if body.is_waste:
            price, amount = 0.0, 0.0
        else:
            if it.sale_price_krw <= 0:
                raise HTTPException(400, "판매가격을 입력해 주세요")
            price = it.sale_price_krw
            amount = round(price * it.sale_qty, 0)
        sid = insert_id(
            "insert into healthweb.sale_item "
            "(login_id, purchase_item_id, sale_date, sale_qty, sale_price_krw, sale_amount_krw, is_waste) "
            "values (:l, :pid, :d, :q, :p, :a, :w) returning id into :new_id",
            l=u["login_id"], pid=it.purchase_item_id, d=sale_date, q=it.sale_qty, p=price, a=amount,
            w=1 if body.is_waste else 0,
        )
        if body.is_waste:
            unit_price = float(row["unit_price_krw"]) if row["unit_price_krw"] is not None else 0.0
            waste_amount = round(unit_price * it.sale_qty, 0)
            eid = insert_id(
                "insert into healthweb.expense_item (login_id, expense_date, item_name, amount_krw, purchase_item_id) "
                "values (:l, :d, '상품 폐기', :a, :pid) returning id into :new_id",
                l=u["login_id"], d=sale_date, a=waste_amount, pid=it.purchase_item_id,
            )
            dml("update healthweb.sale_item set expense_item_id = :e where id = :i", e=eid, i=sid)
        ids.append(sid)
    return {"ids": ids}


@app.get("/sales")
def list_sales(
    u: dict = Depends(current_user), date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    require_erp(u)
    conds = ["s.login_id = :l"]
    binds: dict = {"l": u["login_id"]}
    if date_from:
        conds.append("s.sale_date >= :df"); binds["df"] = date_from
    if date_to:
        conds.append("s.sale_date <= :dt"); binds["dt"] = date_to
    where = " and ".join(conds)
    rows = qall(
        f"select s.id, s.sale_date, s.sale_qty, s.sale_price_krw, s.sale_amount_krw, s.is_waste, "
        f"p.purchase_no, p.product_name, p.unit_price_krw, m.path thumb_path "
        f"from healthweb.sale_item s join healthweb.purchase_item p on p.id = s.purchase_item_id "
        f"left join healthweb.media m on m.id = p.thumb_media_id "
        f"where {where} order by s.sale_date desc, s.id desc",
        **binds,
    )
    items = [{
        "id": r["id"], "sale_date": r["sale_date"], "purchase_no": r["purchase_no"], "product_name": r["product_name"],
        "sale_qty": r["sale_qty"], "sale_price_krw": float(r["sale_price_krw"]),
        "sale_amount_krw": float(r["sale_amount_krw"]), "is_waste": bool(r["is_waste"]),
        "waste_value_krw": (
            round(r["sale_qty"] * float(r["unit_price_krw"]), 0) if r["unit_price_krw"] is not None else None
        ),
        "thumb_url": _media_url(r["thumb_path"])["url"] if r["thumb_path"] else None,
    } for r in rows]
    total = q1(f"select sum(s.sale_amount_krw) t from healthweb.sale_item s where {where}", **binds)
    return {"items": items, "total_krw": float(total["t"]) if total and total["t"] is not None else 0}


@app.patch("/sales/{sid}")
def update_sale(sid: int, body: SalePatchIn, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    row = q1(
        "select purchase_item_id, is_waste from healthweb.sale_item where id = :i and login_id = :l",
        i=sid, l=u["login_id"],
    )
    if row is None:
        raise HTTPException(404, "없는 기록입니다")
    if row["is_waste"]:
        raise HTTPException(400, "폐기 처리 건은 수정할 수 없습니다. 삭제 후 다시 등록해 주세요")
    pid = row["purchase_item_id"]
    prow = q1("select quantity from healthweb.purchase_item where id = :pid", pid=pid)
    others = q1(
        "select coalesce(sum(sale_qty), 0) s from healthweb.sale_item where purchase_item_id = :pid and id != :i",
        pid=pid, i=sid,
    )
    capacity = prow["quantity"] - others["s"]
    if body.sale_qty <= 0 or body.sale_qty > capacity:
        raise HTTPException(400, "판매 수량이 재고 수량을 초과했습니다")
    if body.sale_price_krw <= 0:
        raise HTTPException(400, "판매가격을 입력해 주세요")
    amount = round(body.sale_price_krw * body.sale_qty, 0)
    dml(
        "update healthweb.sale_item set sale_qty = :q, sale_price_krw = :p, sale_amount_krw = :a where id = :i",
        q=body.sale_qty, p=body.sale_price_krw, a=amount, i=sid,
    )
    return {"ok": True}


@app.delete("/sales/{sid}")
def delete_sale(sid: int, u: dict = Depends(current_user)) -> dict:
    require_erp(u)
    row = q1(
        "select expense_item_id from healthweb.sale_item where id = :i and login_id = :l",
        i=sid, l=u["login_id"],
    )
    if row is None:
        raise HTTPException(404, "없는 기록입니다")
    dml("delete from healthweb.sale_item where id = :i", i=sid)
    if row["expense_item_id"]:
        dml("delete from healthweb.expense_item where id = :i", i=row["expense_item_id"])
    return {"ok": True}


# ---------- ERP: 손익 ----------

_YM_RE = re.compile(r"^\d{4}-\d{2}$")


def _month_range(mf: str, mt: str) -> list[str]:
    y1, m1 = int(mf[:4]), int(mf[5:7])
    y2, m2 = int(mt[:4]), int(mt[5:7])
    months = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


@app.get("/profit")
def get_profit(u: dict = Depends(current_user), month_from: str = "", month_to: str = "") -> dict:
    require_erp(u)
    mf, mt = month_from.strip(), month_to.strip()
    if not _YM_RE.match(mf) or not _YM_RE.match(mt):
        raise HTTPException(400, "조회 시작월/종료월을 YYYY-MM 형식으로 입력해 주세요")
    if mf > mt:
        raise HTTPException(400, "시작월이 종료월보다 늦을 수 없습니다")
    months = _month_range(mf, mt)
    if len(months) > 60:
        raise HTTPException(400, "조회 기간이 너무 깁니다")

    rev_rows = qall(
        "select substr(s.sale_date, 1, 7) ym, sum(s.sale_amount_krw) revenue, "
        "sum(s.sale_qty * nvl(p.unit_price_krw, 0)) cogs "
        "from healthweb.sale_item s join healthweb.purchase_item p on p.id = s.purchase_item_id "
        "where s.login_id = :l and s.is_waste = 0 and substr(s.sale_date, 1, 7) between :mf and :mt "
        "group by substr(s.sale_date, 1, 7)",
        l=u["login_id"], mf=mf, mt=mt,
    )
    exp_rows = qall(
        "select substr(expense_date, 1, 7) ym, sum(amount_krw) expense from healthweb.expense_item "
        "where login_id = :l and substr(expense_date, 1, 7) between :mf and :mt "
        "group by substr(expense_date, 1, 7)",
        l=u["login_id"], mf=mf, mt=mt,
    )
    rev_by_ym = {r["ym"]: r for r in rev_rows}
    exp_by_ym = {r["ym"]: r for r in exp_rows}

    result = []
    tot_revenue = tot_cogs = tot_expense = 0.0
    for ym in months:
        rv = rev_by_ym.get(ym)
        ex = exp_by_ym.get(ym)
        revenue = float(rv["revenue"]) if rv and rv["revenue"] is not None else 0.0
        cogs = float(rv["cogs"]) if rv and rv["cogs"] is not None else 0.0
        expense = float(ex["expense"]) if ex and ex["expense"] is not None else 0.0
        profit = revenue - (cogs + expense)
        result.append({"month": ym, "revenue": revenue, "cogs": cogs, "expense": expense, "profit": profit})
        tot_revenue += revenue; tot_cogs += cogs; tot_expense += expense
    total = {
        "revenue": tot_revenue, "cogs": tot_cogs, "expense": tot_expense,
        "profit": tot_revenue - (tot_cogs + tot_expense),
    }
    return {"months": result, "total": total}
