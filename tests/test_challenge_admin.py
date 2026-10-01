"""챌린지 관리(오너) 스모크 — 활용도 목록 · 비활성화(읽기 전용) · 종료 알림 · 다시 활성화."""
import json, urllib.request, urllib.error, urllib.parse, datetime
from _db import connect as _db_connect
BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너공지", "hunter2pw")   # run_local_api.sh OWNER_LOGIN_ID
M = ("chalm", "챌린지멤버", "hunter2pw")
O = ("chalo", "챌린지외부", "hunter2pw")
TODAY = datetime.date.today().strftime("%Y-%m-%d")


def call(m, p, b=None, t=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    if d: r.add_header("Content-Type", "application/json")
    if t: r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r) as x: return x.status, json.loads(x.read() or "{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or "{}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    ids = (OW[0], M[0], O[0])
    for l in ids:
        cur.execute("delete from healthweb.notification where login_id=:l or actor=:l", l=l)
        cur.execute("delete from healthweb.notification where challenge_id in "
                    "(select id from healthweb.challenge where owner=:l)", l=l)
        cur.execute("delete from healthweb.challenge_checkin where login_id=:l or challenge_id in "
                    "(select id from healthweb.challenge where owner=:l)", l=l)
        cur.execute("delete from healthweb.challenge_member where login_id=:l or challenge_id in "
                    "(select id from healthweb.challenge where owner=:l)", l=l)
    for l in ids:
        cur.execute("delete from healthweb.challenge where owner=:l", l=l)
    for l in ids:
        cur.execute("delete from healthweb.app_user where login_id=:l", l=l)
    c.commit(); c.close(); print("  cleanup done")


cleanup()
try:
    tow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
    tm = call("POST", "/auth/signup", {"login_id": M[0], "name": M[1], "password": M[2]})[1]["token"]
    to = call("POST", "/auth/signup", {"login_id": O[0], "name": O[1], "password": O[2]})[1]["token"]

    cid = call("POST", "/challenges", {"title": "관리테스트챌린지", "target_days": 5}, t=to)[1]["id"]
    assert call("POST", f"/challenges/{cid}/join", t=tm)[0] == 200
    assert call("POST", f"/challenges/{cid}/checkin", {"date": TODAY}, t=tm)[0] == 200

    print("1) 비오너 → 403")
    assert call("GET", "/admin/challenges", t=tm)[0] == 403
    assert call("PATCH", f"/admin/challenges/{cid}", {"is_active": False}, t=tm)[0] == 403

    print("2) 관리 목록 — 지표")
    r = call("GET", "/admin/challenges", t=tow)
    assert r[0] == 200, r
    c = next(i for i in r[1]["items"] if i["id"] == cid)
    assert c["member_count"] == 2 and c["active_7d"] == 1 and c["last_check"] == TODAY, c
    assert c["is_active"] and not c["low_usage"], c  # 오늘 만듦 → 저활용 아님

    print("3) 비활성화 → 참여자 2명(만든 사람+멤버)에게 알림")
    r = call("PATCH", f"/admin/challenges/{cid}", {"is_active": False}, t=tow)
    assert r[0] == 200 and r[1]["notified"] == 2, r
    n = call("GET", "/notifications", t=tm)[1]["items"]
    assert n and n[0]["kind"] == "chal_end" and n[0]["challenge_id"] == cid \
        and n[0]["challenge_title"] == "관리테스트챌린지", n[:1]

    print("4) 읽기 전용 — 체크/해제/참여 400, 상세는 열람 가능")
    assert call("POST", f"/challenges/{cid}/checkin", {"date": TODAY}, t=tm)[0] == 400
    assert call("DELETE", f"/challenges/{cid}/checkin/{TODAY}", t=tm)[0] == 400
    assert call("POST", f"/challenges/{cid}/join", t=tow)[0] == 400
    d = call("GET", f"/challenges/{cid}", t=tm)
    assert d[0] == 200 and d[1]["is_active"] is False and d[1]["my_progress"] == 1 and d[1]["deactivated_at"], d

    print("5) 노출 — 비참여자 목록·검색엔 없음, 참여자 목록엔 종료로, 오늘 체크 표엔 없음")
    ids = lambda t, q="": [i["id"] for i in call("GET", "/challenges" + q, t=t)[1]["items"]]
    assert cid not in ids(tow)                       # 오너지만 체크박스 끔
    assert cid in ids(tow, "?include_inactive=true")  # 오너 + 체크박스
    lst = call("GET", "/challenges", t=tm)[1]["items"]
    mine = [i for i in lst if i["id"] == cid]
    assert mine and mine[0]["is_active"] is False, mine
    s = call("GET", "/search?q=" + urllib.parse.quote("관리테스트"), t=tow)[1]
    assert all(i["id"] != cid for i in s["challenges"]), s["challenges"]
    w = call("GET", f"/challenges/mine/week?end={TODAY}", t=tm)[1]["items"]
    assert all(i["id"] != cid for i in w), w
    p = call("GET", f"/c/{cid}")
    assert p[0] == 200 and p[1]["is_active"] is False, p

    print("6) 비오너가 include_inactive 보내도 무시")
    # 멤버가 나가면 비참여 비오너 → include_inactive 를 보내도 안 보여야 함
    assert call("DELETE", f"/challenges/{cid}/leave", t=tm)[0] == 200
    assert cid not in ids(tm, "?include_inactive=true")

    print("7) 관리 목록 기본은 활성만, 체크하면 비활성 포함")
    assert all(i["id"] != cid for i in call("GET", "/admin/challenges", t=tow)[1]["items"])
    r = call("GET", "/admin/challenges?include_inactive=true", t=tow)[1]["items"]
    assert any(i["id"] == cid and not i["is_active"] for i in r), r

    print("8) 다시 활성화 → 체크 가능, 안 읽은 종료 알림 회수")
    r = call("PATCH", f"/admin/challenges/{cid}", {"is_active": True}, t=tow)
    assert r[0] == 200 and r[1]["is_active"] is True, r
    n = call("GET", "/notifications", t=to)[1]["items"]  # chalo 는 알림을 아직 안 읽음
    assert all(i["kind"] != "chal_end" for i in n), n
    assert call("POST", f"/challenges/{cid}/checkin", {"date": TODAY}, t=to)[0] == 200
    print("ALL OK")
finally:
    cleanup()
