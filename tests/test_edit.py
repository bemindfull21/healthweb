"""글 수정(PATCH /posts/:id) 스모크."""
import json, urllib.request, urllib.error
from _db import connect as _db_connect
BASE = "http://127.0.0.1:8971"
A = ("edita", "에디에이", "hunter2pw")
B = ("editb", "에디비", "hunter2pw")


def call(m, p, b=None, t=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    if d: r.add_header("Content-Type", "application/json")
    if t: r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r) as x: return x.status, json.loads(x.read() or "{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or "{}")


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:150]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    for l in ("edita", "editb"):
        cur.execute("delete from healthweb.notification where login_id=:l or actor=:l", l=l)
        cur.execute("delete from healthweb.post where login_id=:l", l=l)
        cur.execute("delete from healthweb.app_user where login_id=:l", l=l)
    c.commit(); c.close(); print("  cleanup done")


cleanup()
ta = call("POST", "/auth/signup", {"login_id": A[0], "name": A[1], "password": A[2]})[1]["token"]
tb = call("POST", "/auth/signup", {"login_id": B[0], "name": B[1], "password": B[2]})[1]["token"]

print("1) 글 작성")
pid = call("POST", "/posts", {"kind": "resolve", "body": "원본 내용"}, t=ta)[1]["id"]
print(f"  post id = {pid}")

print("2) 본인이 수정 -> 200, 반영됨")
r = call("PATCH", f"/posts/{pid}", {"body": "수정된 내용"}, t=ta)
show("edit", r); assert r[0] == 200
detail = call("GET", f"/posts/{pid}", t=ta)[1]
assert detail["body"] == "수정된 내용", detail

print("3) 남의 글 수정 시도 -> 404")
r = call("PATCH", f"/posts/{pid}", {"body": "해킹시도"}, t=tb)
show("other user edit", r); assert r[0] == 404

print("4) 빈 본문 -> 400")
r = call("PATCH", f"/posts/{pid}", {"body": "   "}, t=ta)
show("empty body", r); assert r[0] == 400

print("5) 2000자 초과 -> 400")
r = call("PATCH", f"/posts/{pid}", {"body": "가" * 2001}, t=ta)
show("too long", r); assert r[0] == 400

print("6) 없는 글 -> 404")
r = call("PATCH", "/posts/999999999", {"body": "x"}, t=ta)
show("not found", r); assert r[0] == 404

print("7) 원래 내용은 그대로 남아있는지(4·5번이 실패해서 안 바뀜)")
detail = call("GET", f"/posts/{pid}", t=ta)[1]
assert detail["body"] == "수정된 내용", detail

cleanup()
print("\n\u2705 ALL PASS")
