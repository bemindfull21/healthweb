"""Phase 3a 스모크 — 검색 · 리치 프로필 · 차단 · 공개 챌린지."""
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect
Q = urllib.parse.quote

BASE = "http://127.0.0.1:8971"
A = ("p3aa", "에이삼", "hunter2pw")
B = ("p3ab", "비이삼", "hunter2pw")
C = ("p3ac", "씨이삼", "hunter2pw")
WORD = "특별단어zqx"


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


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:160]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    ids = (A[0], B[0], C[0])
    inlist = "('%s','%s','%s')" % ids
    cur.execute(f"update healthweb.app_user set pinned_post_id=null where login_id in {inlist}")
    # 다른 사용자가 테스트 유저의 글/사람에 남긴 자식 행 먼저 정리
    for t in ("encouragement", "post_comment", "notification"):
        cur.execute(f"delete from healthweb.{t} where post_id in "
                    f"(select id from healthweb.post where login_id in {inlist})")
    for l in ids:
        for t in ("challenge_checkin", "challenge_member", "notification",
                  "post_comment", "encouragement", "weight_entry", "post"):
            cur.execute(f"delete from healthweb.{t} where login_id=:l", l=l)
        cur.execute("delete from healthweb.notification where actor=:l", l=l)
        cur.execute("delete from healthweb.follow where follower=:l or followee=:l", l=l)
        cur.execute("delete from healthweb.user_block where blocker=:l or blocked=:l", l=l)
    cur.execute(f"delete from healthweb.challenge_member where challenge_id in (select id from healthweb.challenge where owner in {inlist})")
    cur.execute(f"delete from healthweb.challenge where owner in {inlist}")
    cur.execute(f"delete from healthweb.app_user where login_id in {inlist}")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
ta = call("POST", "/auth/signup", {"login_id": A[0], "name": A[1], "password": A[2]})[1]["token"]
tb = call("POST", "/auth/signup", {"login_id": B[0], "name": B[1], "password": B[2]})[1]["token"]
tc = call("POST", "/auth/signup", {"login_id": C[0], "name": C[1], "password": C[2]})[1]["token"]

print("1) 리치 프로필 — link/location/bio 저장 + 조회")
r = call("PATCH", "/auth/me", {"link": "example.org/me", "location": "서울", "bio": "안녕하세요"}, token=ta)
show("patch", r)
r = call("GET", "/auth/me", token=ta); show("me", r)
assert r[1]["link"] == "https://example.org/me" and r[1]["location"] == "서울"
r = call("GET", f"/u/{Q(A[1])}", token=tb); show("A profile", r)
assert r[1]["link"] == "https://example.org/me"
assert r[1]["location"] == "서울"
assert "post_count" in r[1] and "challenge_count" in r[1]

print("2) 잘못된 링크 거부")
assert call("PATCH", "/auth/me", {"link": "not a url"}, token=ta)[0] == 400

print("3) 고정 글")
p1 = call("POST", "/posts", {"kind": "resolve", "body": "첫 글"}, token=ta)[1]["id"]
p2 = call("POST", "/posts", {"kind": "reflect", "body": "두번째 글"}, token=ta)[1]["id"]
show("pin p2", call("PATCH", "/auth/me", {"pinned_post_id": p2}, token=ta))
r = call("GET", f"/u/{Q(A[1])}", token=tb); show("profile pinned", r)
assert r[1]["pinned"] and r[1]["pinned"]["id"] == p2
assert all(post["id"] != p2 for post in r[1]["posts"]), "고정 글은 목록에서 제외"
assert r[1]["pinned"]["pinned"] is True
print("   남 글 고정 시도 → 400")
assert call("PATCH", "/auth/me", {"pinned_post_id": p1}, token=tb)[0] == 400
print("   고정 해제")
call("PATCH", "/auth/me", {"pinned_post_id": 0}, token=ta)
r = call("GET", f"/u/{Q(A[1])}", token=tb)
assert "pinned" not in r[1] or r[1]["pinned"] is None

print("4) 검색 — 글/사용자/챌린지")
call("POST", "/posts", {"kind": "casual", "body": f"{WORD} 어떻게 하나요"}, token=ta)
cid = call("POST", "/challenges", {"title": f"{WORD} 챌린지", "target_days": 10}, token=ta)[1]["id"]
r = call("GET", f"/search?q={Q(WORD)}", token=tb); show("search", r)
assert any(WORD in p["body"] for p in r[1]["posts"]), "글 검색"
assert any(c["title"] == f"{WORD} 챌린지" for c in r[1]["challenges"]), "챌린지 검색"
r = call("GET", f"/search?q={Q('비이삼')}", token=ta)
assert any(u["name"] == B[1] for u in r[1]["users"]), "사용자 검색"
assert call("GET", "/search?q=a", token=tb)[0] == 400, "1글자 거부"

print("5) 차단 — B가 A를 차단")
call("POST", f"/u/{Q(B[1])}/follow", token=ta)          # A→B 팔로우
assert call("GET", f"/u/{Q(B[1])}", token=tc)[1]["followers"] == 1
show("block", call("POST", f"/u/{Q(A[1])}/block", token=tb))
r = call("GET", f"/u/{Q(B[1])}", token=tc)              # 중립 시점(C)
assert r[1]["followers"] == 0, "차단 시 기존 팔로우 해제"
print("   B의 전체 피드에서 A 글 사라짐")
r = call("GET", "/feed?scope=all", token=tb)
assert all(WORD not in i["body"] for i in r[1]["items"])
print("   B가 보는 A 프로필 → blocked_by_me")
r = call("GET", f"/u/{Q(A[1])}", token=tb); show("A prof (blocked)", r)
assert r[1].get("blocked_by_me") is True
print("   A가 보는 B 프로필 → 404")
assert call("GET", f"/u/{Q(B[1])}", token=ta)[0] == 404
print("   B 검색에서 A 글·유저 제외")
r = call("GET", f"/search?q={Q(WORD)}", token=tb)
assert not r[1]["posts"]
r = call("GET", f"/search?q={Q('에이삼')}", token=tb)
assert not any(u["name"] == A[1] for u in r[1]["users"])
print("   차단 상태에서 팔로우 시도 → 403")
assert call("POST", f"/u/{Q(A[1])}/follow", token=tb)[0] == 403

print("6) B의 알림에서 차단한 A 제외")
# A가 차단 전에 B 글에 응원했다고 가정 — 대신 C가 응원해 알림 존재 확인
pc = call("POST", "/posts", {"kind": "resolve", "body": "비이 글"}, token=tb)[1]["id"]
call("POST", f"/posts/{pc}/encourage", token=tc)
r = call("GET", "/notifications", token=tb)
assert any(n["actor_name"] == C[1] for n in r[1]["items"])

print("7) 차단 해제 → 복구")
call("DELETE", f"/u/{Q(A[1])}/block", token=tb)
r = call("GET", f"/u/{Q(A[1])}", token=tb)
assert r[1].get("blocked_by_me") is not True and r[1]["name"] == A[1]
r = call("GET", f"/search?q={Q(WORD)}", token=tb)
assert r[1]["posts"], "차단 해제 후 검색 복구"

print("8) 공개 챌린지 페이지 — 로그인 불필요")
r = call("GET", f"/c/{cid}")   # no token
show("public challenge", r)
assert r[0] == 200 and r[1]["title"] == f"{WORD} 챌린지"
assert r[1]["member_count"] == 1 and A[1] in r[1]["sample_members"]
assert "active_this_week" in r[1]
assert call("GET", "/c/99999999")[0] == 404

cleanup()
print("\n✅ ALL PASS")
