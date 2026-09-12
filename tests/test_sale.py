"""ERP 재고/판매 스모크 — 재고 조회 + 판매 등록(수량 상한) + 판매 목록/수정(재고 재계산)."""
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect

Q = urllib.parse.quote
BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너삼", "hunter2pw")   # run_local_api.sh 의 OWNER_LOGIN_ID
U = ("saleu", "세일유", "hunter2pw")
U2 = ("saleu2", "세일유투", "hunter2pw")


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


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:200]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("delete from healthweb.sale_item where login_id in ('saleu','saleu2','p3bowner')")
    cur.execute("delete from healthweb.purchase_item where login_id in ('saleu','saleu2','p3bowner')")
    cur.execute("delete from healthweb.app_user where login_id in ('saleu','saleu2','p3bowner')")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok_ow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
tok_u = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]
tok_u2 = call("POST", "/auth/signup", {"login_id": U2[0], "name": U2[1], "password": U2[2]})[1]["token"]
call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": True}, token=tok_ow)
call("PATCH", f"/admin/users/{Q(U2[1])}/erp-access", {"erp_access": True}, token=tok_ow)

print("0) 구매 등록(수량10·₩1000총액→단가₩100) 후 입고 체크")
r = call("POST", "/purchases", {
    "items": [{"product_name": "테스트상품", "quantity": 10, "price_krw": 1000}],
    "order_date": "2026-09-01",
}, token=tok_u)
show("purchase", r); assert r[0] == 200
pid = r[1]["ids"][0]

print("1) 입고 전에는 재고에 안 뜸")
r = call("GET", "/stock", token=tok_u)
show("stock before received", r); assert r[0] == 200 and pid not in [x["purchase_item_id"] for x in r[1]["items"]]

r = call("PATCH", f"/purchases/{pid}", {"received": True}, token=tok_u)
assert r[0] == 200

print("2) 재고 조회 — 남은수량10, 단가원화100, 남은금액1000")
r = call("GET", "/stock", token=tok_u)
show("stock", r); assert r[0] == 200
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid)
assert item["remaining_qty"] == 10, item
assert item["unit_price_krw"] == 100, item
assert item["remaining_amount_krw"] == 1000, item

print("3) 재고 수량 초과 판매 거부")
r = call("POST", "/sales", {"sale_date": "2026-09-05", "items": [
    {"purchase_item_id": pid, "sale_qty": 11, "sale_price_krw": 150},
]}, token=tok_u)
show("oversell", r); assert r[0] == 400

print("4) 일부 판매(3개) 후 재고 7개로 감소")
r = call("POST", "/sales", {"sale_date": "2026-09-05", "items": [
    {"purchase_item_id": pid, "sale_qty": 3, "sale_price_krw": 150},
]}, token=tok_u)
show("sell 3", r); assert r[0] == 200
sid = r[1]["ids"][0]
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid)
assert item["remaining_qty"] == 7, item

print("5) 판매 목록 조회 — 판매일자/구매ID/상품/수량/가격/금액")
r = call("GET", "/sales?date_from=2026-09-05&date_to=2026-09-05", token=tok_u)
show("sales list", r); assert r[0] == 200 and len(r[1]["items"]) == 1
row = r[1]["items"][0]
assert row["sale_qty"] == 3 and row["sale_price_krw"] == 150 and row["sale_amount_krw"] == 450, row
assert row["product_name"] == "테스트상품" and row["purchase_no"], row
assert r[1]["total_krw"] == 450, r[1]

print("6) 판매수량 초과 변경 거부 (남은 재고+본인수량=10 을 넘으면 안 됨)")
r = call("PATCH", f"/sales/{sid}", {"sale_qty": 11, "sale_price_krw": 150}, token=tok_u)
show("patch oversell", r); assert r[0] == 400

print("7) 판매수량/가격 변경 성공 → 재고에 반영")
r = call("PATCH", f"/sales/{sid}", {"sale_qty": 5, "sale_price_krw": 200}, token=tok_u)
show("patch ok", r); assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid)
assert item["remaining_qty"] == 5, item  # 10 - 5
r = call("GET", "/sales?date_from=2026-09-05&date_to=2026-09-05", token=tok_u)
row = r[1]["items"][0]
assert row["sale_qty"] == 5 and row["sale_price_krw"] == 200 and row["sale_amount_krw"] == 1000, row

print("8) 나머지 5개 전부 판매하면 재고에서 사라짐")
r = call("POST", "/sales", {"sale_date": "2026-09-06", "items": [
    {"purchase_item_id": pid, "sale_qty": 5, "sale_price_krw": 200},
]}, token=tok_u)
show("sell rest", r); assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
assert pid not in [x["purchase_item_id"] for x in r[1]["items"]], r[1]

print("9) 타 사용자는 남의 판매 기록 수정 불가 (404)")
r = call("PATCH", f"/sales/{sid}", {"sale_qty": 1, "sale_price_krw": 1}, token=tok_u2)
show("other user patch", r); assert r[0] == 404

print("10) erp_access 없으면 /stock·/sales 403")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": False}, token=tok_ow)
assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
show("stock revoked", r); assert r[0] == 403
r = call("GET", "/sales", token=tok_u)
show("sales revoked", r); assert r[0] == 403

cleanup()
print("\n✅ ALL PASS")
