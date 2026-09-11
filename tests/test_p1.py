"""Phase 1 API 스모크 (login_id/name 교체판)."""
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect

BASE = "http://127.0.0.1:8971"
L1, N1, P1 = "smoke1", "김스모크", "hunter2pw"
L2, N2, P2 = "smoke2", "이둘", "hunter2pw"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data: req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:140]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    ids = "('%s','%s','smoke9')" % (L1, L2)
    cur.execute(f"update healthweb.app_user set pinned_post_id=null where login_id in {ids}")
    for t in ("encouragement", "post_comment", "notification"):
        cur.execute(f"delete from healthweb.{t} where post_id in "
                    f"(select id from healthweb.post where login_id in {ids})")
    for t in ("challenge_checkin", "challenge_member", "notification", "post_comment",
              "encouragement", "post", "weight_entry"):
        cur.execute(f"delete from healthweb.{t} where login_id in {ids}")
    cur.execute(f"delete from healthweb.notification where actor in {ids}")
    cur.execute(f"delete from healthweb.follow where follower in {ids} or followee in {ids}")
    cur.execute(f"delete from healthweb.user_block where blocker in {ids} or blocked in {ids}")
    cur.execute(f"delete from healthweb.app_user where login_id in {ids}")
    c.commit(); c.close(); print("  cleanup done")


cleanup()

print("1) /auth/check")
show("login_id free", call("GET", f"/auth/check?login_id={L1}"))
show("name free", call("GET", "/auth/check?name=%EA%B9%80%EC%8A%A4%EB%AA%A8%ED%81%AC"))
show("bad login_id", call("GET", "/auth/check?login_id=Ab_c"))

print("2) signup")
r = call("POST", "/auth/signup", {"login_id": L1, "name": N1, "password": P1, "target_weight": 68})
show("signup 1", r); assert r[0] == 200; t1 = r[1]["token"]
r2 = call("POST", "/auth/signup", {"login_id": L2, "name": N2, "password": P2})
t2 = r2[1]["token"]; assert r2[0] == 200

print("3) dup login_id / dup name -> 409")
show("dup id", call("POST", "/auth/signup", {"login_id": L1, "name": "다른이름", "password": P1}))
show("dup name", call("POST", "/auth/signup", {"login_id": "smoke9", "name": N1, "password": P1}))

print("4) check now taken")
show("id taken", call("GET", f"/auth/check?login_id={L1}"))
show("name taken", call("GET", f"/auth/check?name={urllib.parse.quote(N1)}"))

print("5) signin / me")
r = call("POST", "/auth/signin", {"login_id": L1.upper(), "password": P1}); show("signin", r); assert r[0] == 200
show("me", call("GET", "/auth/me", token=t1))

print("6) weight + share")
r = call("POST", "/weights", {"weight": 72.3, "logged_at": "2026-09-08T09:00", "note": "", "share": True}, token=t1)
show("weight", r); assert r[1]["post_id"]; log_post = r[1]["post_id"]

print("7) feed — 이름 노출, login_id 없음")
r = call("GET", "/feed?scope=all", token=t2); show("feed", r)
it = r[1]["items"][0]
assert it["name"] == N1 and "login_id" not in it and "username" not in it, it

print("8) post + encourage + comment")
pid = call("POST", "/posts", {"kind": "resolve", "body": "30분 걸었다"}, token=t2)[1]["id"]
call("POST", f"/posts/{pid}/encourage", token=t1)
call("POST", f"/posts/{pid}/comments", {"body": "좋아요"}, token=t1)
r = call("GET", f"/posts/{pid}", token=t1); show("post detail", r)
assert r[1]["encourage_count"] == 1 and r[1]["comments"][0]["name"] == N1

print("9) profile by name (URL-encoded)")
r = call("GET", f"/u/{urllib.parse.quote(N1)}", token=t2); show("profile", r)
assert r[1]["name"] == N1 and "login_id" not in r[1] and r[1]["streak"] == 1

print("10) PATCH name (중복이면 409)")
show("rename dup", call("PATCH", "/auth/me", {"name": N2}, token=t1))
show("rename ok", call("PATCH", "/auth/me", {"name": "김새이름"}, token=t1))
r = call("GET", "/auth/me", token=t1); assert r[1]["name"] == "김새이름"

print("11) reset: login_id + name(변경된 것)")
show("reset old name -> 401", call("POST", "/auth/reset", {"login_id": L1, "name": N1, "new_password": "x"*8}))
show("reset new name -> ok", call("POST", "/auth/reset", {"login_id": L1, "name": "김새이름", "new_password": "newpass99"}))
show("signin new pw", call("POST", "/auth/signin", {"login_id": L1, "password": "newpass99"}))

cleanup()
print("\n✅ ALL PASS")
