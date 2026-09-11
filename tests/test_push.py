"""텔레그램 알림 연결 스모크 — 일회용 코드 · /internal 링크 · 재배정 · notify 경로."""
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect
Q = urllib.parse.quote
BASE = "http://127.0.0.1:8971"
KEY = "localinternal"
A = ("pusha", "푸시에이", "hunter2pw")
B = ("pushb", "푸시비이", "hunter2pw")


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


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:150]}")


def db():
    return _db_connect()


def cleanup():
    c = db(); cur = c.cursor(); ids = "('pusha','pushb')"
    cur.execute(f"update healthweb.app_user set tg_chat_id=null where login_id in {ids}")
    cur.execute(f"delete from healthweb.tg_link_code where login_id in {ids}")
    cur.execute(f"delete from healthweb.notification where login_id in {ids} or actor in {ids}")
    cur.execute(f"delete from healthweb.follow where follower in {ids} or followee in {ids}")
    cur.execute(f"delete from healthweb.app_user where login_id in {ids}")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
ta = call("POST", "/auth/signup", {"login_id": A[0], "name": A[1], "password": A[2]})[1]["token"]
tb = call("POST", "/auth/signup", {"login_id": B[0], "name": B[1], "password": B[2]})[1]["token"]

print("1) 코드 발급")
r = call("POST", "/push/telegram/code", token=ta); show("code", r)
assert r[0] == 200 and r[1]["code"].startswith("HW-")
assert "t.me/health_trainer21_bot?start=" in r[1]["deep_link"]
code_a = r[1]["code"]

print("2) 연결 전 상태")
assert call("GET", "/push/telegram", token=ta)[1] == {"linked": False, "available": True}
assert call("GET", "/auth/me", token=ta)[1]["telegram_linked"] is False

print("3) 잘못된 internal key → 401")
assert call("POST", "/internal/telegram/link", {"code": code_a, "chat_id": 111}, headers={"X-Internal-Key": "wrong"})[0] == 401
assert call("POST", "/internal/telegram/link", {"code": code_a, "chat_id": 111})[0] == 401

print("4) 봇이 연결 (chat_id 12345)")
r = call("POST", "/internal/telegram/link", {"code": code_a, "chat_id": 12345}, headers={"X-Internal-Key": KEY})
show("link", r)
assert r[0] == 200 and r[1]["name"] == A[1]
assert call("GET", "/push/telegram", token=ta)[1]["linked"] is True
assert call("GET", "/auth/me", token=ta)[1]["telegram_linked"] is True

print("5) 코드는 1회용 — 재사용 불가")
assert call("POST", "/internal/telegram/link", {"code": code_a, "chat_id": 999}, headers={"X-Internal-Key": KEY})[0] == 404

print("6) 만료된 코드 → 404")
import datetime as _dt
old = _dt.datetime.utcnow().replace(microsecond=0) - _dt.timedelta(minutes=20)
c = db(); cur = c.cursor()
cur.execute("insert into healthweb.tg_link_code (code, login_id, created_at) values ('HW-OLD123','pusha', :t)", t=old)
c.commit(); c.close()
assert call("POST", "/internal/telegram/link", {"code": "HW-OLD123", "chat_id": 999}, headers={"X-Internal-Key": KEY})[0] == 404

print("7) chat_id 재배정 — 같은 chat_id를 B에 연결하면 A는 해제")
code_b = call("POST", "/push/telegram/code", token=tb)[1]["code"]
r = call("POST", "/internal/telegram/link", {"code": code_b, "chat_id": 12345}, headers={"X-Internal-Key": KEY})
assert r[0] == 200 and r[1]["name"] == B[1]
assert call("GET", "/push/telegram", token=tb)[1]["linked"] is True
assert call("GET", "/push/telegram", token=ta)[1]["linked"] is False, "A는 chat_id를 뺏김"

print("8) 웹에서 연결 해제")
assert call("DELETE", "/push/telegram", token=tb)[0] == 200
assert call("GET", "/push/telegram", token=tb)[1]["linked"] is False

print("9) internal unlink — 없는 chat_id")
assert call("POST", "/internal/telegram/unlink", {"chat_id": 88888}, headers={"X-Internal-Key": KEY})[1]["unlinked"] is False

print("10) notify 경로 — tg 연결 상태에서 팔로우해도 요청 정상")
code_a2 = call("POST", "/push/telegram/code", token=ta)[1]["code"]
call("POST", "/internal/telegram/link", {"code": code_a2, "chat_id": 55555}, headers={"X-Internal-Key": KEY})
r = call("POST", f"/u/{Q(A[1])}/follow", token=tb)
assert r[0] == 200
n = call("GET", "/notifications", token=ta)[1]
assert any(x["kind"] == "follow" and x["actor_name"] == B[1] for x in n["items"]), n

cleanup()
print("\n\u2705 ALL PASS")
