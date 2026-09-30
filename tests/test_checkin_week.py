"""오늘 체크 표 — GET /challenges/mine/week · 체크인 날짜 범위(최근 7일) 제한."""
import json, urllib.request, urllib.error, datetime
from _db import connect as _db_connect

BASE = "http://127.0.0.1:8971"
U = ("wkchk", "주간체크", "hunter2pw")
TODAY = datetime.date.today()


def ymd(days_ago):
    return (TODAY - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")


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


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("delete from healthweb.challenge_checkin where login_id=:l", l=U[0])
    cur.execute("delete from healthweb.notification where login_id=:l", l=U[0])
    cur.execute("delete from healthweb.challenge_member where login_id=:l", l=U[0])
    cur.execute("delete from healthweb.challenge where owner=:l", l=U[0])
    cur.execute("delete from healthweb.app_user where login_id=:l", l=U[0])
    c.commit(); c.close(); print("  cleanup done")


cleanup()
try:
    tok = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]

    print("1) 참여 챌린지 없으면 빈 목록")
    r = call("GET", f"/challenges/mine/week?end={ymd(0)}", token=tok)
    assert r[0] == 200 and r[1]["items"] == [] and r[1]["start"] == ymd(6), r

    print("2) 챌린지 2개 만들고(자동 참여) 체크인")
    c1 = call("POST", "/challenges", {"title": "주간A", "target_days": 10}, token=tok)[1]["id"]
    c2 = call("POST", "/challenges", {"title": "주간B", "target_days": 5}, token=tok)[1]["id"]
    for d in (0, 2, 6):
        assert call("POST", f"/challenges/{c1}/checkin", {"date": ymd(d)}, token=tok)[0] == 200
    assert call("POST", f"/challenges/{c2}/checkin", {"date": ymd(1)}, token=tok)[0] == 200

    print("3) 범위 밖 날짜는 400 (10일 전 · 사흘 뒤)")
    r = call("POST", f"/challenges/{c1}/checkin", {"date": ymd(10)}, token=tok)
    assert r[0] == 400, r
    r = call("POST", f"/challenges/{c1}/checkin", {"date": ymd(-3)}, token=tok)
    assert r[0] == 400, r

    print("4) 주간 표: 가입 순서대로, 7일 창 안의 체크만")
    # 창 밖(10일 전) 체크를 DB 로 직접 넣어 done 에는 잡히고 checked 에는 안 잡히는지 확인
    c = _db_connect(); c.cursor().execute(
        "insert into healthweb.challenge_checkin (challenge_id, login_id, check_date) values (:c, :l, :d)",
        c=c1, l=U[0], d=ymd(10)); c.commit(); c.close()
    r = call("GET", f"/challenges/mine/week?end={ymd(0)}", token=tok)
    assert r[0] == 200, r
    items = r[1]["items"]
    assert [i["id"] for i in items] == [c1, c2], items
    assert items[0]["checked"] == sorted([ymd(0), ymd(2), ymd(6)]) and items[0]["done"] == 4, items[0]
    assert items[1]["checked"] == [ymd(1)] and items[1]["done"] == 1, items[1]

    print("5) 체크 해제 반영")
    assert call("DELETE", f"/challenges/{c1}/checkin/{ymd(2)}", token=tok)[0] == 200
    items = call("GET", f"/challenges/mine/week?end={ymd(0)}", token=tok)[1]["items"]
    assert ymd(2) not in items[0]["checked"], items[0]

    print("6) 잘못된 end → 400")
    assert call("GET", "/challenges/mine/week?end=abc", token=tok)[0] == 400
    print("ALL OK")
finally:
    cleanup()
