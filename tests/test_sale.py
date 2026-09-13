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
    cur.execute("delete from healthweb.expense_item where login_id in ('saleu','saleu2','p3bowner')")
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
assert "thumb_url" in item and item["thumb_url"] is None, item  # 썸네일 없는 구매 건은 null

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

print("4b) 이미 판매된 수량보다 적게 구매 수량 변경 불가 (판매된 만큼까지는 허용)")
r = call("PATCH", f"/purchases/{pid}", {"quantity": 2}, token=tok_u)  # 이미 3개 판매됨
show("reduce below sold", r); assert r[0] == 400
r = call("PATCH", f"/purchases/{pid}", {"quantity": 3}, token=tok_u)
show("reduce to sold exactly", r); assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
assert pid not in [x["purchase_item_id"] for x in r[1]["items"]], r[1]  # 남은수량 0 → 재고 목록에서 빠짐
r = call("PATCH", f"/purchases/{pid}", {"quantity": 10}, token=tok_u)  # 원상복구 — 이후 테스트가 quantity=10 가정
show("restore quantity", r); assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid)
assert item["remaining_qty"] == 7, item

print("5) 판매 목록 조회 — 판매일자/구매ID/상품/수량/가격/금액")
r = call("GET", "/sales?date_from=2026-09-05&date_to=2026-09-05", token=tok_u)
show("sales list", r); assert r[0] == 200 and len(r[1]["items"]) == 1
row = r[1]["items"][0]
assert row["sale_qty"] == 3 and row["sale_price_krw"] == 150 and row["sale_amount_krw"] == 450, row
assert "thumb_url" in row and row["thumb_url"] is None, row
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

print("11) 판매 건 삭제 → 재고가 삭제한 만큼 복원됨")
r = call("POST", "/purchases", {
    "items": [{"product_name": "삭제테스트상품", "quantity": 5, "price_krw": 1000}],  # 단가 200
    "order_date": "2026-09-01",
}, token=tok_u)
assert r[0] == 200
pid2 = r[1]["ids"][0]
assert call("PATCH", f"/purchases/{pid2}", {"received": True}, token=tok_u)[0] == 200
r = call("POST", "/sales", {"sale_date": "2026-09-07", "items": [
    {"purchase_item_id": pid2, "sale_qty": 2, "sale_price_krw": 300},
]}, token=tok_u)
show("sell for delete test", r); assert r[0] == 200
sid2 = r[1]["ids"][0]
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid2)
assert item["remaining_qty"] == 3, item
r = call("DELETE", f"/sales/{sid2}", token=tok_u)
show("delete sale", r); assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid2)
assert item["remaining_qty"] == 5, item  # 삭제로 원복
r = call("GET", "/sales?date_from=2026-09-07&date_to=2026-09-07", token=tok_u)
assert len(r[1]["items"]) == 0, r[1]

print("12) 재고 폐기 저장 — 판매가 아니라 폐기(is_waste)로 저장 + 비용 자동 생성")
r = call("POST", "/sales", {"sale_date": "2026-09-08", "is_waste": True, "items": [
    {"purchase_item_id": pid2, "sale_qty": 2},
]}, token=tok_u)
show("waste save", r); assert r[0] == 200
wid = r[1]["ids"][0]
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid2)
assert item["remaining_qty"] == 3, item  # 폐기도 재고를 줄임
r = call("GET", "/sales?date_from=2026-09-08&date_to=2026-09-08", token=tok_u)
show("waste in sales list", r); assert r[0] == 200
wrow = r[1]["items"][0]
assert wrow["is_waste"] is True and wrow["sale_qty"] == 2, wrow
assert wrow["sale_price_krw"] == 0 and wrow["sale_amount_krw"] == 0, wrow  # 매출로 잡히지 않음
assert wrow["waste_value_krw"] == 400, wrow  # 화면 표시용 참고값 = 수량(2)×구매단가(200)
r = call("GET", "/expenses?date_from=2026-09-08&date_to=2026-09-08", token=tok_u)
show("waste expense", r); assert r[0] == 200 and len(r[1]["items"]) == 1
exp = r[1]["items"][0]
assert exp["item_name"] == "상품 폐기" and exp["amount_krw"] == 400, exp  # 2개 * 단가200
stock_pid2 = next(x for x in call("GET", "/stock", token=tok_u)[1]["items"] if x["purchase_item_id"] == pid2)
assert exp["purchase_no"] == stock_pid2["purchase_no"], (exp, stock_pid2)  # 폐기 대상 구매ID가 비용에 같이 저장됨
waste_eid = exp["id"]

print("12b) 폐기 비용은 비용 탭에서 직접 삭제 불가 — 판매 목록에서 지우라고 안내")
r = call("DELETE", f"/expenses/{waste_eid}", token=tok_u)
show("delete waste expense directly", r)
assert r[0] == 400 and r[1]["detail"] == "폐기 비용을 삭제하려면 판매 목록에서 폐기판매를 삭제하세요", r

print("12c) 폐기 비용은 금액도 수정 불가")
r = call("PATCH", f"/expenses/{waste_eid}", {"amount_krw": 1}, token=tok_u)
show("patch waste expense rejected", r)
assert r[0] == 400 and r[1]["detail"] == "폐기로 자동 생성된 비용은 금액을 변경할 수 없습니다", r

print("13) 폐기 건은 수정 불가")
r = call("PATCH", f"/sales/{wid}", {"sale_qty": 1, "sale_price_krw": 100}, token=tok_u)
show("patch waste rejected", r); assert r[0] == 400

print("14) 폐기 건 삭제 → 연결된 비용도 같이 삭제 + 재고 복원")
r = call("DELETE", f"/sales/{wid}", token=tok_u)
show("delete waste", r); assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
item = next(x for x in r[1]["items"] if x["purchase_item_id"] == pid2)
assert item["remaining_qty"] == 5, item
r = call("GET", "/expenses?date_from=2026-09-08&date_to=2026-09-08", token=tok_u)
assert len(r[1]["items"]) == 0, r[1]  # 비용도 같이 지워짐

print("15) 판매 이력이 있는 구매 건은 삭제 거부 → 판매 삭제 후엔 삭제 가능")
r = call("POST", "/sales", {"sale_date": "2026-09-09", "items": [
    {"purchase_item_id": pid2, "sale_qty": 1, "sale_price_krw": 300},
]}, token=tok_u)
assert r[0] == 200
sid3 = r[1]["ids"][0]
r = call("DELETE", f"/purchases/{pid2}", token=tok_u)
show("delete purchase with sale history", r)
assert r[0] == 400 and r[1]["detail"] == "판매 이력이 있어 삭제할 수 없습니다", r
r = call("DELETE", f"/sales/{sid3}", token=tok_u)
assert r[0] == 200
r = call("DELETE", f"/purchases/{pid2}", token=tok_u)
show("delete purchase after sale removed", r); assert r[0] == 200

print("16) erp_access 없으면 /stock·/sales 403")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": False}, token=tok_ow)
assert r[0] == 200
r = call("GET", "/stock", token=tok_u)
show("stock revoked", r); assert r[0] == 403
r = call("GET", "/sales", token=tok_u)
show("sales revoked", r); assert r[0] == 403

cleanup()
print("\n✅ ALL PASS")
