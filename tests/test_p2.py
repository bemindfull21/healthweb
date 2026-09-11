"""Phase 2 스모크 — 팔로우 · 피드 scope · 챌린지 · 알림."""
import json, urllib.request, urllib.error, urllib.parse, datetime
from _db import connect as _db_connect
Q = urllib.parse.quote

BASE = "http://127.0.0.1:8971"
A = ("p2a", "에이", "hunter2pw")
B = ("p2b", "비이", "hunter2pw")
TODAY = datetime.date.today().strftime("%Y-%m-%d")
YEST = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


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


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:150]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    for l in (A[0], B[0]):
        for t in ("challenge_checkin", "challenge_member", "notification",
                  "post_comment", "encouragement", "post", "weight_entry"):
            cur.execute(f"delete from healthweb.{t} where login_id=:l", l=l)
        cur.execute("delete from healthweb.notification where actor=:l", l=l)
        cur.execute("delete from healthweb.follow where follower=:l or followee=:l", l=l)
    cur.execute("delete from healthweb.challenge_checkin where challenge_id in (select id from healthweb.challenge where owner in (:a,:b))", a=A[0], b=B[0])
    cur.execute("delete from healthweb.challenge_member where challenge_id in (select id from healthweb.challenge where owner in (:a,:b))", a=A[0], b=B[0])
    cur.execute("delete from healthweb.challenge where owner in (:a,:b)", a=A[0], b=B[0])
    for l in (A[0], B[0]):
        cur.execute("delete from healthweb.app_user where login_id=:l", l=l)
    c.commit(); c.close(); print("  cleanup done")


cleanup()
ta = call("POST", "/auth/signup", {"login_id": A[0], "name": A[1], "password": A[2]})[1]["token"]
tb = call("POST", "/auth/signup", {"login_id": B[0], "name": B[1], "password": B[2]})[1]["token"]

print("1) B가 글 작성")
pb = call("POST", "/posts", {"kind": "resolve", "body": "비이의 루틴"}, token=tb)[1]["id"]

print("2) A 피드(following) — B 안 팔로우 → 비어있음 / all → 보임")
show("following", call("GET", "/feed?scope=following", token=ta))
r = call("GET", "/feed?scope=all", token=ta)
assert any(i["id"] == pb for i in r[1]["items"])

print("3) A가 B 팔로우")
show("follow", call("POST", f"/u/{Q(B[1])}/follow", token=ta))
r = call("GET", "/feed?scope=following", token=ta)
assert any(i["id"] == pb for i in r[1]["items"]), "팔로우 후 피드에 떠야"

print("4) 프로필에 팔로워 수 / i_follow")
r = call("GET", f"/u/{Q(B[1])}", token=ta); show("B profile", r)
assert r[1]["followers"] == 1 and r[1]["i_follow"] is True
r = call("GET", f"/u/{Q(B[1])}/followers", token=tb); show("B followers", r)
assert r[1]["users"][0]["name"] == A[1]

print("5) A가 B글에 응원 + 댓글 → B에게 알림")
call("POST", f"/posts/{pb}/encourage", token=ta)
call("POST", f"/posts/{pb}/comments", {"body": "좋아요"}, token=ta)
r = call("GET", "/notifications", token=tb); show("B notif", r)
kinds = sorted(n["kind"] for n in r[1]["items"])
assert kinds == ["comment", "encourage", "follow"], kinds
show("unread", call("GET", "/notifications/unread-count", token=tb))
assert call("GET", "/notifications/unread-count", token=tb)[1]["count"] == 3

print("6) 응원 취소 → encourage 알림 삭제")
call("DELETE", f"/posts/{pb}/encourage", token=ta)
r = call("GET", "/notifications", token=tb)
assert not any(n["kind"] == "encourage" for n in r[1]["items"])

print("7) 알림 읽음 처리")
call("POST", "/notifications/read", token=tb)
assert call("GET", "/notifications/unread-count", token=tb)[1]["count"] == 0

print("8) 자기 행동엔 알림 없음 (B가 자기 글 응원)")
call("POST", f"/posts/{pb}/encourage", token=tb)
assert call("GET", "/notifications/unread-count", token=tb)[1]["count"] == 0

print("9) 챌린지 생성 (A)")
r = call("POST", "/challenges", {"title": "매일 기록 21일", "description": "매일 몸무게 한 번", "target_days": 21}, token=ta)
show("create", r); cid = r[1]["id"]
r = call("GET", "/challenges", token=ta); show("list", r)
assert any(c["id"] == cid and c["i_joined"] and c["member_count"] == 1 for c in r[1]["items"])

print("10) B 참여 + 체크인")
show("join", call("POST", f"/challenges/{cid}/join", token=tb))
show("checkin yest", call("POST", f"/challenges/{cid}/checkin", {"date": YEST}, token=tb))
r = call("POST", f"/challenges/{cid}/checkin", {"date": TODAY}, token=tb)
show("checkin today", r)
assert r[1]["done"] == 2 and r[1]["streak"] == 2

print("11) 중복 체크인 무시")
r = call("POST", f"/challenges/{cid}/checkin", {"date": TODAY}, token=tb)
assert r[1]["done"] == 2

print("12) 챌린지 상세 — 멤버별 progress")
r = call("GET", f"/challenges/{cid}", token=ta); show("detail", r)
assert r[1]["member_count"] if "member_count" in r[1] else True
assert len(r[1]["members"]) == 2
bmem = [m for m in r[1]["members"] if m["name"] == B[1]][0]
assert bmem["progress"] == 2

print("13) 체크 취소")
r = call("DELETE", f"/challenges/{cid}/checkin/{TODAY}", token=tb)
assert r[1]["done"] == 1

print("14) 챌린지 나가기 → 체크인도 삭제")
call("DELETE", f"/challenges/{cid}/leave", token=tb)
r = call("GET", f"/challenges/{cid}", token=ta)
assert len(r[1]["members"]) == 1

print("15) 언팔로우")
call("DELETE", f"/u/{Q(B[1])}/follow", token=ta)
r = call("GET", f"/u/{Q(B[1])}", token=ta)
assert r[1]["followers"] == 0 and r[1]["i_follow"] is False

cleanup()
print("\n✅ ALL PASS")
