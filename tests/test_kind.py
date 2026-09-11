"""글 종류 재편(브라그/결심/반성/그냥) + 수정 시 종류 변경 스모크."""
import json, urllib.request, urllib.error
from _db import connect as _db_connect
BASE = "http://127.0.0.1:8971"
U = ("kindu", "카인드유", "hunter2pw")


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
    cur.execute("delete from healthweb.notification where login_id='kindu' or actor='kindu'")
    cur.execute("delete from healthweb.post where login_id='kindu'")
    cur.execute("delete from healthweb.weight_entry where login_id='kindu'")
    cur.execute("delete from healthweb.app_user where login_id='kindu'")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]

print("1) 새 4종류로 글 작성 성공")
ids = {}
for k in ("brag", "resolve", "reflect", "casual"):
    r = call("POST", "/posts", {"kind": k, "body": f"{k} 테스트"}, t=tok)
    assert r[0] == 200, (k, r)
    ids[k] = r[1]["id"]
print("  ids:", ids)

print("2) 옛날 종류(log/routine/reflection/question)는 이제 거부")
for k in ("log", "routine", "reflection", "question"):
    r = call("POST", "/posts", {"kind": k, "body": "구버전 종류"}, t=tok)
    assert r[0] == 400, (k, r)
print("  전부 400 확인")

print("3) 수정 시 종류 변경 가능")
r = call("PATCH", f"/posts/{ids['casual']}", {"body": "이제 자랑으로 바꿈", "kind": "brag"}, t=tok)
show("edit kind", r); assert r[0] == 200
detail = call("GET", f"/posts/{ids['casual']}", t=tok)[1]
assert detail["kind"] == "brag" and detail["body"] == "이제 자랑으로 바꿈", detail

print("4) 수정 시 kind 생략하면 종류 그대로 유지")
r = call("PATCH", f"/posts/{ids['reflect']}", {"body": "본문만 바꿈"}, t=tok)
assert r[0] == 200
detail = call("GET", f"/posts/{ids['reflect']}", t=tok)[1]
assert detail["kind"] == "reflect" and detail["body"] == "본문만 바꿈", detail

print("5) 수정 시 잘못된 kind -> 400")
r = call("PATCH", f"/posts/{ids['brag']}", {"body": "x", "kind": "routine"}, t=tok)
show("bad kind on edit", r); assert r[0] == 400

print("6) 몸무게 공유 글은 kind='casual'로 자동 생성되고, kind 상관없이 무게 노출")
w = call("POST", "/weights", {"weight": 61.5, "share": True, "note": "무게 테스트"}, t=tok)[1]
pid = w["post_id"]
detail = call("GET", f"/posts/{pid}", t=tok)[1]
assert detail["kind"] == "casual", detail
call("PATCH", f"/auth/me", {"weight_privacy": "public"}, t=tok)
detail2 = call("GET", f"/posts/{pid}", t=tok)[1]
print(f"  weight post before kind change: {json.dumps(detail2, ensure_ascii=False)[:150]}")
assert detail2.get("weight") == 61.5, detail2
r = call("PATCH", f"/posts/{pid}", {"body": "무게 기록", "kind": "brag"}, t=tok)
assert r[0] == 200
detail3 = call("GET", f"/posts/{pid}", t=tok)[1]
print(f"  weight post after kind change to brag: {json.dumps(detail3, ensure_ascii=False)[:150]}")
assert detail3.get("weight") == 61.5, detail3  # kind 바뀌어도 무게는 계속 노출(weight_entry_id 기준)

cleanup()
print("\n\u2705 ALL PASS")
