"""주간 건강 브리핑(GET /brief) 스모크 — 클라우드 루틴 전용 읽기 엔드포인트."""
import datetime as dt
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect

Q = urllib.parse.quote
BASE = "http://127.0.0.1:8971"
KEY = "localbrief"
U = ("briefu", "브리핑유", "hunter2pw")


def call(method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data: req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:200]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("delete from healthweb.challenge_checkin where login_id = 'briefu'")
    cur.execute("delete from healthweb.challenge_member where login_id = 'briefu'")
    cur.execute("delete from healthweb.challenge where owner = 'briefu'")
    cur.execute("delete from healthweb.weight_entry where login_id = 'briefu'")
    cur.execute("delete from healthweb.app_user where login_id = 'briefu'")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2], "target_weight": 68})[1]["token"]

now = dt.datetime.now()
fmt = "%Y-%m-%dT%H:%M"


def d(days_ago):
    return (now - dt.timedelta(days=days_ago)).strftime(fmt)


print("0) 기간(7일) 안팎에 걸쳐 몸무게 기록 + 챌린지 체크인 준비")
r = call("POST", "/weights", {"weight": 71.0, "logged_at": d(10)}, token=tok)  # 기간 밖 — prior
show("weight -10d", r); assert r[0] == 200
r = call("POST", "/weights", {"weight": 70.0, "logged_at": d(5)}, token=tok)  # 기간 안
show("weight -5d", r); assert r[0] == 200
r = call("POST", "/weights", {"weight": 69.0, "logged_at": d(1)}, token=tok)  # 기간 안
show("weight -1d", r); assert r[0] == 200

r = call("POST", "/challenges", {"title": "브리핑테스트", "target_days": 10}, token=tok)
show("challenge", r); assert r[0] == 200
cid = r[1]["id"]
today = dt.date.today()
r = call("POST", f"/challenges/{cid}/checkin", {"date": (today - dt.timedelta(days=11)).strftime("%Y-%m-%d")}, token=tok)
assert r[0] == 200  # 기간 밖 체크인
r = call("POST", f"/challenges/{cid}/checkin", {"date": (today - dt.timedelta(days=3)).strftime("%Y-%m-%d")}, token=tok)
assert r[0] == 200  # 기간 안 체크인
r = call("POST", f"/challenges/{cid}/checkin", {"date": today.strftime("%Y-%m-%d")}, token=tok)
assert r[0] == 200  # 기간 안 체크인

print("1) 키 없이/틀린 키로 요청하면 401")
r = call("GET", f"/brief?login_id={U[0]}&days=7")
show("no key", r); assert r[0] == 401
r = call("GET", f"/brief?login_id={U[0]}&days=7", headers={"X-Brief-Key": "wrong"})
show("wrong key", r); assert r[0] == 401

print("2) 없는 사용자는 404")
r = call("GET", "/brief?login_id=nosuchuser999&days=7", headers={"X-Brief-Key": KEY})
show("unknown user", r); assert r[0] == 404

print("3) 정상 조회 — 최근 7일 기록·직전 기록·챌린지 체크인 수")
r = call("GET", f"/brief?login_id={U[0]}&days=7", headers={"X-Brief-Key": KEY})
show("brief", r); assert r[0] == 200
body = r[1]
assert body["target_weight"] == 68.0, body
assert len(body["entries"]) == 2, body  # -5d, -1d 만 (기간 밖 -10d 제외)
assert body["prior_weight"] == 71.0, body  # -10d 기록이 직전값으로 잡힘
chal = next(c for c in body["challenges"] if c["title"] == "브리핑테스트")
assert chal["total_checkins"] == 3, chal
assert chal["recent_checkins"] == 2, chal  # -11d 제외, -3d/오늘만

cleanup()
print("\n✅ ALL PASS")
