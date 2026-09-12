"""ERP 비용 스모크 — 권한 게이팅 + CRUD(등록/기간조회/금액수정/삭제) + 구매ID 연결(필수)."""
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect

Q = urllib.parse.quote
BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너삼", "hunter2pw")   # run_local_api.sh 의 OWNER_LOGIN_ID
U = ("expu", "익스펜스유", "hunter2pw")
U2 = ("expu2", "익스펜스유투", "hunter2pw")


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
    cur.execute("delete from healthweb.expense_item where login_id in ('expu','expu2','p3bowner')")
    cur.execute("delete from healthweb.purchase_item where login_id in ('expu','expu2','p3bowner')")
    cur.execute("delete from healthweb.app_user where login_id in ('expu','expu2','p3bowner')")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok_ow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
tok_u = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]
tok_u2 = call("POST", "/auth/signup", {"login_id": U2[0], "name": U2[1], "password": U2[2]})[1]["token"]

print("1) erp_access 없으면 403")
r = call("GET", "/expenses", token=tok_u)
show("no access", r); assert r[0] == 403

print("2) 오너가 권한 부여")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": True}, token=tok_ow)
show("grant", r); assert r[0] == 200
r = call("PATCH", f"/admin/users/{Q(U2[1])}/erp-access", {"erp_access": True}, token=tok_ow)
assert r[0] == 200

print("0) 비용에 연결할 구매 건 등록")
r = call("POST", "/purchases", {
    "items": [{"product_name": "비용테스트상품", "quantity": 1, "price_krw": 5000}],
    "order_date": "2026-09-01",
}, token=tok_u)
show("purchase", r); assert r[0] == 200
pid = r[1]["ids"][0]
r = call("POST", "/purchases", {
    "items": [{"product_name": "타사용자상품", "quantity": 1, "price_krw": 1000}],
    "order_date": "2026-09-01",
}, token=tok_u2)
assert r[0] == 200
pid_other = r[1]["ids"][0]

print("3) 비용발생일자/비용항목/비용(원화)/구매ID 등록")
r = call("POST", "/expenses", {"expense_date": "2026-09-10", "item_name": "택배비", "amount_krw": 3000, "purchase_item_id": pid}, token=tok_u)
show("create", r); assert r[0] == 200
eid1 = r[1]["id"]
r = call("POST", "/expenses", {"expense_date": "2026-09-05", "item_name": "포장재", "amount_krw": 12000, "purchase_item_id": pid}, token=tok_u)
show("create2", r); assert r[0] == 200
eid2 = r[1]["id"]

print("3b) 비용발생일자/비용항목 빈 값 거부")
r = call("POST", "/expenses", {"expense_date": "", "item_name": "택배비", "amount_krw": 1000, "purchase_item_id": pid}, token=tok_u)
show("empty date", r); assert r[0] == 400
r = call("POST", "/expenses", {"expense_date": "2026-09-10", "item_name": "  ", "amount_krw": 1000, "purchase_item_id": pid}, token=tok_u)
show("empty name", r); assert r[0] == 400

print("3c) 구매ID 없거나 남의 구매ID면 거부")
r = call("POST", "/expenses", {"expense_date": "2026-09-10", "item_name": "택배비", "amount_krw": 1000, "purchase_item_id": 99999999}, token=tok_u)
show("nonexistent purchase id", r); assert r[0] == 400
r = call("POST", "/expenses", {"expense_date": "2026-09-10", "item_name": "택배비", "amount_krw": 1000, "purchase_item_id": pid_other}, token=tok_u)
show("other user's purchase id", r); assert r[0] == 400

print("4) 기간 조회 — 범위 안/밖 + 구매ID 표시")
r = call("GET", "/expenses?date_from=2026-09-10&date_to=2026-09-10", token=tok_u)
show("in range", r); assert r[0] == 200 and len(r[1]["items"]) == 1 and r[1]["items"][0]["id"] == eid1
assert r[1]["total_krw"] == 3000, r[1]
assert r[1]["items"][0]["purchase_no"], r[1]  # 구매ID(purchase_no)가 같이 표시됨
r = call("GET", "/expenses?date_from=2026-09-01&date_to=2026-09-10", token=tok_u)
show("wider range", r); assert r[0] == 200 and len(r[1]["items"]) == 2 and r[1]["total_krw"] == 15000
r = call("GET", "/expenses?date_from=2026-09-11&date_to=2026-09-20", token=tok_u)
show("out of range", r); assert r[0] == 200 and len(r[1]["items"]) == 0 and r[1]["total_krw"] == 0

print("5) 비용(원화) 금액 수정")
r = call("PATCH", f"/expenses/{eid1}", {"amount_krw": 3500}, token=tok_u)
show("patch amount", r); assert r[0] == 200
r = call("GET", "/expenses?date_from=2026-09-10&date_to=2026-09-10", token=tok_u)
assert r[1]["items"][0]["amount_krw"] == 3500, r[1]
r = call("PATCH", f"/expenses/{99999999}", {"amount_krw": 100}, token=tok_u)
show("patch nonexistent", r); assert r[0] == 404

print("6) 타 사용자 기록은 수정·삭제 불가 (404)")
r = call("PATCH", f"/expenses/{eid1}", {"amount_krw": 1}, token=tok_u2)
show("other user patch", r); assert r[0] == 404
r = call("DELETE", f"/expenses/{eid1}", token=tok_u2)
show("other user delete", r); assert r[0] == 404

print("7) X 삭제")
r = call("DELETE", f"/expenses/{eid1}", token=tok_u)
show("delete", r); assert r[0] == 200
r = call("GET", "/expenses?date_from=2026-09-01&date_to=2026-09-20", token=tok_u)
assert len(r[1]["items"]) == 1 and r[1]["items"][0]["id"] == eid2, r[1]

print("8) 오너가 권한 회수하면 다시 403")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": False}, token=tok_ow)
assert r[0] == 200
r = call("GET", "/expenses", token=tok_u)
show("revoked", r); assert r[0] == 403

cleanup()
print("\n✅ ALL PASS")
