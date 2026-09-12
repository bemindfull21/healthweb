"""ERP 손익 스모크 — 월별 매출/구매원가/비용/수익 집계 + 입력값 검증."""
import json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect

Q = urllib.parse.quote
BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너삼", "hunter2pw")   # run_local_api.sh 의 OWNER_LOGIN_ID
U = ("profitu", "프로핏유", "hunter2pw")


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


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:250]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("delete from healthweb.sale_item where login_id in ('profitu','p3bowner')")
    cur.execute("delete from healthweb.expense_item where login_id in ('profitu','p3bowner')")
    cur.execute("delete from healthweb.purchase_item where login_id in ('profitu','p3bowner')")
    cur.execute("delete from healthweb.app_user where login_id in ('profitu','p3bowner')")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok_ow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
tok_u = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]
call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": True}, token=tok_ow)

print("1) erp_access 없으면 403 — 임시로 회수했다가 이후 계속 사용하도록 재부여")
call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": False}, token=tok_ow)
r = call("GET", "/profit?month_from=2026-08&month_to=2026-09", token=tok_u)
show("no access", r); assert r[0] == 403
call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": True}, token=tok_ow)

print("2) 8월: 구매(수량4·단가₩1000) 입고 후 3개 판매(개당₩2000) + 비용 ₩5000")
r = call("POST", "/purchases", {
    "items": [{"product_name": "손익상품", "quantity": 4, "price_krw": 4000}],  # 단가 1000
    "order_date": "2026-08-10",
}, token=tok_u)
assert r[0] == 200
pid = r[1]["ids"][0]
assert call("PATCH", f"/purchases/{pid}", {"received": True}, token=tok_u)[0] == 200
r = call("POST", "/sales", {"sale_date": "2026-08-15", "items": [
    {"purchase_item_id": pid, "sale_qty": 3, "sale_price_krw": 2000},
]}, token=tok_u)
show("sale", r); assert r[0] == 200
r = call("POST", "/expenses", {"expense_date": "2026-08-20", "item_name": "포장비", "amount_krw": 5000}, token=tok_u)
show("expense", r); assert r[0] == 200

print("3) 9월엔 판매 1개만(개당₩2500), 비용 없음")
r = call("POST", "/sales", {"sale_date": "2026-09-02", "items": [
    {"purchase_item_id": pid, "sale_qty": 1, "sale_price_krw": 2500},
]}, token=tok_u)
show("sale sep", r); assert r[0] == 200

print("4) 손익 조회: 8월 매출6000/원가3000/비용5000/수익-2000, 9월 매출2500/원가1000/비용0/수익1500")
r = call("GET", "/profit?month_from=2026-08&month_to=2026-09", token=tok_u)
show("profit", r); assert r[0] == 200
by_m = {m["month"]: m for m in r[1]["months"]}
aug, sep = by_m["2026-08"], by_m["2026-09"]
assert aug["revenue"] == 6000 and aug["cogs"] == 3000 and aug["expense"] == 5000 and aug["profit"] == -2000, aug
assert sep["revenue"] == 2500 and sep["cogs"] == 1000 and sep["expense"] == 0 and sep["profit"] == 1500, sep
tot = r[1]["total"]
assert tot["revenue"] == 8500 and tot["cogs"] == 4000 and tot["expense"] == 5000 and tot["profit"] == -500, tot

print("5) 데이터 없는 달도 0으로 채워서 나옴")
r = call("GET", "/profit?month_from=2026-07&month_to=2026-09", token=tok_u)
show("with empty month", r); assert r[0] == 200
by_m2 = {m["month"]: m for m in r[1]["months"]}
assert by_m2["2026-07"] == {"month": "2026-07", "revenue": 0, "cogs": 0, "expense": 0, "profit": 0}, by_m2["2026-07"]

print("6) 잘못된 입력 거부")
r = call("GET", "/profit", token=tok_u)
show("missing params", r); assert r[0] == 400
r = call("GET", "/profit?month_from=2026-09&month_to=2026-08", token=tok_u)
show("reversed range", r); assert r[0] == 400
r = call("GET", "/profit?month_from=2026-9&month_to=2026-09", token=tok_u)
show("bad format", r); assert r[0] == 400

cleanup()
print("\n✅ ALL PASS")
