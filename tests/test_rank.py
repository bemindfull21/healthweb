"""등급(자기돌봄 습관) 스모크 — 초기값 · 점수 누적 · 승급 알림 · 하락 없음 · 피드/프로필 노출."""
import json, urllib.request, urllib.error, urllib.parse, datetime
from _db import connect as _db_connect
BASE = "http://127.0.0.1:8971"
U = ("rku", "등급유저", "hunter2pw")


def call(m, p, b=None, t=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    if d: r.add_header("Content-Type", "application/json")
    if t: r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r) as x: return x.status, json.loads(x.read() or "{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or "{}")


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:200]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("select id from healthweb.challenge where owner=:l", l=U[0])
    cids = [r[0] for r in cur]
    for cid in cids:
        cur.execute("delete from healthweb.challenge_checkin where challenge_id=:c", c=cid)
        cur.execute("delete from healthweb.challenge_member where challenge_id=:c", c=cid)
        cur.execute("delete from healthweb.challenge where id=:c", c=cid)
    cur.execute("delete from healthweb.notification where login_id=:l or actor=:l", l=U[0])
    cur.execute("delete from healthweb.post where login_id=:l", l=U[0])
    cur.execute("delete from healthweb.weight_entry where login_id=:l", l=U[0])
    cur.execute("delete from healthweb.app_user where login_id=:l", l=U[0])
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]

print("1) 가입 직후 흑연(1)")
me = call("GET", "/auth/me", t=tok)[1]
assert me["rank_level"] == 1 and me["rank_name"] == "흑연", me

print("2) 연속 20일 기록 (백데이트) -> 점수 누적, 등급 상승 + 승급 알림")
today = datetime.date.today()
for i in range(20, 0, -1):
    d = today - datetime.timedelta(days=i)
    body = {"weight": 65.0, "logged_at": d.isoformat() + "T08:00:00"}
    if i == 1:
        body["share"] = True
    r = call("POST", "/weights", body, t=tok)
    assert r[0] == 200, r
me = call("GET", "/auth/me", t=tok)[1]
show("me after 20 days", (200, me))
assert me["rank_level"] >= 2, me  # 20일*1 + 20일 연속*2 = 60점 -> 흑요석(50+)

print("3) 알림에 rank 승급 항목이 있다")
notif = call("GET", "/notifications", t=tok)[1]
rank_items = [n for n in notif["items"] if n["kind"] == "rank"]
assert len(rank_items) >= 1, notif
assert rank_items[0]["rank_level"] == me["rank_level"], rank_items

print("4) 피드 글에도 rank_level이 실려온다")
feed = call("GET", "/feed", t=tok)[1]
mine = [p for p in feed["items"] if p.get("name") == U[1]]
assert mine and mine[0]["rank_level"] == me["rank_level"], mine[:1]

print("5) 공개 프로필에도 rank_level/rank_name")
prof = call("GET", f"/u/{urllib.parse.quote(U[1])}", t=tok)[1]
assert prof["rank_level"] == me["rank_level"] and prof["rank_name"], prof

print("6) 챌린지 완주로 점수 추가 상승")
cid = call("POST", "/challenges", {"title": "등급 테스트 챌린지", "target_days": 3}, t=tok)[1]["id"]
for i in range(3):
    d = (today - datetime.timedelta(days=i)).isoformat()
    call("POST", f"/challenges/{cid}/checkin", {"date": d}, t=tok)
me2 = call("GET", "/auth/me", t=tok)[1]
print(f"  score 반영 확인용 rank_level={me2['rank_level']}")
assert me2["rank_level"] >= me["rank_level"], (me, me2)

print("7) 기록을 지워도 등급은 내려가지 않는다")
weights = call("GET", "/weights", t=tok)[1]["entries"]
for w in weights[:15]:
    call("DELETE", f"/weights/{w['id']}", t=tok)
# 다시 하나 기록해서 재계산 트리거
call("POST", "/weights", {"weight": 65.0, "logged_at": today.isoformat() + "T08:00:00Z"}, t=tok)
me3 = call("GET", "/auth/me", t=tok)[1]
assert me3["rank_level"] >= me2["rank_level"], (me2, me3)

cleanup()
print("\n\u2705 ALL PASS")
