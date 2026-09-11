"""관리자 공지 스모크 — CRUD · 유효기간 · /notifications 노출."""
import json, urllib.request, urllib.error, datetime
from _db import connect as _db_connect
BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너공지", "hunter2pw")   # runserver.sh OWNER_LOGIN_ID
U = ("annu", "공지관찰", "hunter2pw")


def call(m, p, b=None, t=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    if d: r.add_header("Content-Type", "application/json")
    if t: r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r) as x: return x.status, json.loads(x.read() or "{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or "{}")


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:170]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("delete from healthweb.announcement where created_by in ('p3bowner','annu')")
    for l in ("p3bowner", "annu"):
        cur.execute("delete from healthweb.notification where login_id=:l or actor=:l", l=l)
        cur.execute("delete from healthweb.app_user where login_id=:l", l=l)
    c.commit(); c.close(); print("  cleanup done")


ISO = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
now = datetime.datetime.utcnow()

cleanup()
tow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
tu = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]

print("1) 비오너 → 403")
assert call("GET", "/admin/announcements", t=tu)[0] == 403
assert call("POST", "/admin/announcements", {"body": "x"}, t=tu)[0] == 403

print("2) 즉시 공지 생성")
r = call("POST", "/admin/announcements", {"title": "점검 안내", "body": "오늘 밤 짧은 점검이 있어요."}, t=tow)
show("create", r); live_id = r[1]["id"]

print("3) 예정 공지 (내일 시작)")
sch = call("POST", "/admin/announcements", {"body": "다음 주 챌린지 오픈", "starts_at": ISO(now + datetime.timedelta(days=1))}, t=tow)[1]["id"]

print("4) 만료 공지 (어제 종료)")
exp = call("POST", "/admin/announcements", {"body": "지난 이벤트", "ends_at": ISO(now - datetime.timedelta(days=1))}, t=tow)[1]["id"]

print("5) 종료일 < 시작일 → 400")
assert call("POST", "/admin/announcements",
    {"body": "잘못", "starts_at": ISO(now + datetime.timedelta(days=2)), "ends_at": ISO(now)}, t=tow)[0] == 400

print("6) /notifications — 활성 공지만 노출")
r = call("GET", "/notifications", t=tu); show("notif", r)
ann_ids = [a["id"] for a in r[1].get("announcements", [])]
assert live_id in ann_ids, ann_ids
assert sch not in ann_ids and exp not in ann_ids

print("7) /admin/announcements — 상태 라벨")
r = call("GET", "/admin/announcements", t=tow)
st = {a["id"]: a["state"] for a in r[1]["items"]}
assert st[live_id] == "live" and st[sch] == "scheduled" and st[exp] == "expired", st

print("8) 수정 → /notifications 반영")
call("PATCH", f"/admin/announcements/{live_id}", {"title": "점검 완료", "body": "점검이 끝났습니다. 감사합니다."}, t=tow)
r = call("GET", "/notifications", t=tu)
a = next(a for a in r[1]["announcements"] if a["id"] == live_id)
assert a["title"] == "점검 완료" and "끝났" in a["body"]

print("9) 링크 정규화")
r = call("POST", "/admin/announcements", {"body": "링크 테스트", "link": "example.org/x"}, t=tow)
lid = r[1]["id"]
la = next(a for a in call("GET", "/notifications", t=tu)[1]["announcements"] if a["id"] == lid)
assert la["link"] == "https://example.org/x", la

print("10) 삭제")
call("DELETE", f"/admin/announcements/{live_id}", t=tow)
call("DELETE", f"/admin/announcements/{lid}", t=tow)
r = call("GET", "/notifications", t=tu)
assert all(a["id"] not in (live_id, lid) for a in r[1].get("announcements", []))

print("11) cursor 있으면 공지 없음(첫 페이지만)")
r = call("GET", "/notifications?cursor=999999", t=tu)
assert "announcements" not in r[1]

cleanup()
print("\n\u2705 ALL PASS")
