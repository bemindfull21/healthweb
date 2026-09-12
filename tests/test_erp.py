"""ERP(구매 기록) 스모크 — 권한 게이팅 + 추출(번역+썸네일 크롭) + 저장/조회/삭제."""
import io, json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect
from PIL import Image, ImageDraw, ImageFont

Q = urllib.parse.quote
BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너삼", "hunter2pw")   # run_local_api.sh 의 OWNER_LOGIN_ID
U = ("erpu", "얼피유", "hunter2pw")
U2 = ("erpu2", "얼피유투", "hunter2pw")


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


def upload(token, data, kind="receipt", fname="x.png", ctype="image/png"):
    bnd = "----erp"
    body = (
        f'--{bnd}\r\nContent-Disposition: form-data; name="kind"\r\n\r\n{kind}\r\n'.encode()
        + f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode()
        + f'Content-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n"
        + f'--{bnd}--\r\n'.encode()
    )
    req = urllib.request.Request(BASE + "/media", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={bnd}")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def fake_receipt_bytes():
    """중국어 텍스트 + 사각형 '상품 사진' 1개가 있는 합성 주문내역 — 번역·좌표 추출 둘 다 실제로 검증."""
    img = Image.new("RGB", (500, 220), (255, 255, 255))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 20)
    d.rectangle([20, 20, 110, 110], fill=(200, 80, 80))
    d.text((130, 30), "店铺: 优雅家居旗舰店", font=font, fill=(0, 0, 0))
    d.text((130, 60), "无线蓝牙耳机 黑色", font=font, fill=(0, 0, 0))
    d.text((130, 90), "数量: 2  单价: ¥99.90", font=font, fill=(0, 0, 0))
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:150]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor()
    cur.execute("delete from healthweb.purchase_item where login_id in ('erpu','erpu2','p3bowner')")
    cur.execute("delete from healthweb.media where login_id in ('erpu','erpu2','p3bowner')")
    cur.execute("delete from healthweb.app_user where login_id in ('erpu','erpu2','p3bowner')")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tok_ow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
tok_u = call("POST", "/auth/signup", {"login_id": U[0], "name": U[1], "password": U[2]})[1]["token"]
tok_u2 = call("POST", "/auth/signup", {"login_id": U2[0], "name": U2[1], "password": U2[2]})[1]["token"]

print("1) erp_access 없으면 403")
r = call("GET", "/purchases", token=tok_u)
show("no access", r); assert r[0] == 403

print("2) 오너가 아니면 권한 부여 불가 (403)")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": True}, token=tok_u)
show("non-owner grant", r); assert r[0] == 403

print("3) 오너가 권한 부여")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": True}, token=tok_ow)
show("grant", r); assert r[0] == 200
me = call("GET", "/auth/me", token=tok_u)[1]
assert me["erp_access"] is True, me

print("4) 권한 부여 후 빈 목록 조회 가능")
r = call("GET", "/purchases", token=tok_u)
show("empty list", r); assert r[0] == 200 and r[1]["items"] == [] and r[1]["total_krw"] == 0

print("5) 영수증 이미지 업로드 + AI 추출 (실제 Gemini 호출 — 한국어 번역 + 상품 사진 썸네일 크롭까지 검증)")
up = upload(tok_u, fake_receipt_bytes(), kind="receipt")
show("upload", up); assert up[0] == 200
mid = up[1]["id"]
r = call("POST", "/purchases/extract", {"media_id": mid}, token=tok_u)
show("extract", r); assert r[0] == 200 and isinstance(r[1]["items"], list) and len(r[1]["items"]) >= 1
extracted = r[1]["items"][0]
assert "블루투스" in extracted["product_name"] or "이어폰" in extracted["product_name"], extracted  # 한국어 번역 확인
assert extracted["quantity"] == 2, extracted  # "数量: 2" 수량 추출 확인
assert extracted["thumb_media_id"] and extracted["thumb_url"], extracted  # box_2d 크롭 성공 확인
thumb_mid = extracted["thumb_media_id"]
# 화면엔 단가(¥99.90)만 보이는데 금액(위안화/원화)은 수량(2) 을 곱한 총액이어야 함 — 예전엔 단가만 넣던 버그
assert abs(extracted["price_cny"] - 99.9 * 2) < 0.01, extracted
assert extracted["price_krw"] == round(extracted["price_cny"] * extracted["fx_rate"], 0), extracted
# 단가(원화) = 금액(원화) / 수량, 반올림
assert extracted["unit_price_krw"] == round(extracted["price_krw"] / extracted["quantity"], 0), extracted

print("6) 추출된 항목(썸네일 포함) + 수동 항목(썸네일 없음) 함께 저장")
r = call("POST", "/purchases", {
    "items": [
        {"shop_name": extracted["shop_name"], "product_name": extracted["product_name"],
         "option_text": extracted["option_text"], "quantity": extracted["quantity"],
         "price_cny": extracted["price_cny"], "price_krw": extracted["price_krw"],
         "thumb_media_id": thumb_mid},
        {"shop_name": None, "product_name": "케이스", "quantity": 1, "price_cny": 15, "price_krw": None},
    ],
    "order_date": "2026-09-10", "source_media_id": mid,
}, token=tok_u)
show("save", r); assert r[0] == 200 and len(r[1]["ids"]) == 2
ids = r[1]["ids"]  # ids[0] = 썸네일 있는 항목, ids[1] = 케이스

print("7) 목록 + 합계 + 썸네일 노출 확인")
r = call("GET", "/purchases", token=tok_u)
show("list", r); assert r[0] == 200
items = r[1]["items"]
assert len(items) == 2, items
by_id = {it["id"]: it for it in items}
assert by_id[ids[0]]["thumb_url"], by_id[ids[0]]  # 썸네일 있는 항목
assert by_id[ids[1]]["thumb_url"] is None, by_id[ids[1]]  # 수동 항목은 썸네일 없음
assert round(r[1]["total_cny"], 1) == round(extracted["price_cny"] + 15, 1), r[1]
# 구매ID = 주문일자-일련번호(3자리), 같은 주문일자 안에서 저장 순서대로 채번
assert by_id[ids[0]]["purchase_no"].startswith("20260910-"), by_id[ids[0]]
assert by_id[ids[1]]["purchase_no"] == by_id[ids[0]]["purchase_no"][:9] + str(int(by_id[ids[0]]["purchase_no"][9:]) + 1).zfill(3), by_id
assert by_id[ids[1]]["unit_price_krw"] is None, by_id[ids[1]]  # price_krw 없이 저장한 항목은 단가도 None

print("7b) 입고 체크 + 미입고만 조회")
assert by_id[ids[0]]["received"] is False and by_id[ids[1]]["received"] is False, items  # 기본값 미입고
r = call("PATCH", f"/purchases/{ids[1]}", {"received": True}, token=tok_u)
show("mark received", r); assert r[0] == 200
r = call("GET", "/purchases?unreceived_only=true", token=tok_u)
show("unreceived only", r); assert r[0] == 200
unrec_ids = [it["id"] for it in r[1]["items"]]
assert ids[0] in unrec_ids and ids[1] not in unrec_ids, r[1]
r = call("PATCH", f"/purchases/{99999999}", {"received": True}, token=tok_u)
show("patch nonexistent", r); assert r[0] == 404

print("7c) 구매일자 기간 조회 (미입고만 조회는 기간 무시)")
r = call("GET", "/purchases?date_from=2026-09-10&date_to=2026-09-10", token=tok_u)
show("in range", r); assert r[0] == 200 and len(r[1]["items"]) == 2
r = call("GET", "/purchases?date_from=2026-09-11&date_to=2026-09-20", token=tok_u)
show("out of range", r); assert r[0] == 200 and len(r[1]["items"]) == 0 and r[1]["total_krw"] == 0
r = call("GET", "/purchases?unreceived_only=true&date_from=2026-09-11&date_to=2026-09-20", token=tok_u)
show("unreceived ignores range", r); assert r[0] == 200 and ids[0] in [it["id"] for it in r[1]["items"]]

print("8) 상품명 비어있으면 저장 거부")
r = call("POST", "/purchases", {"items": [{"product_name": "  "}], "order_date": "2026-09-10"}, token=tok_u)
show("empty product", r); assert r[0] == 400

print("8b) 구매일자 비어있으면 저장 거부 (필수 입력)")
r = call("POST", "/purchases", {"items": [{"product_name": "정상 상품"}], "order_date": ""}, token=tok_u)
show("empty order_date", r); assert r[0] == 400

print("9) ERP 권한이 있어도 남의 구매 기록은 못 지움 (자기 것만 GET/DELETE 대상)")
r = call("PATCH", f"/admin/users/{Q(U2[1])}/erp-access", {"erp_access": True}, token=tok_ow)
assert r[0] == 200
r = call("DELETE", f"/purchases/{ids[0]}", token=tok_u2)
show("other erp user delete item", r); assert r[0] == 404

print("10) 본인 삭제 성공 + 썸네일 media GC 확인")
r = call("DELETE", f"/purchases/{ids[0]}", token=tok_u)
show("delete", r); assert r[0] == 200
r = call("GET", "/purchases", token=tok_u)
assert len(r[1]["items"]) == 1, r[1]
c = _db_connect(); cur = c.cursor()
cur.execute("select count(*) from healthweb.media where id = :i", i=thumb_mid)
gone = cur.fetchone()[0] == 0
c.close()
assert gone, f"thumb media {thumb_mid} 가 GC 되지 않음"

print("11) 오너가 권한 회수하면 다시 403")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": False}, token=tok_ow)
assert r[0] == 200
r = call("GET", "/purchases", token=tok_u)
show("revoked", r); assert r[0] == 403

cleanup()
print("\n✅ ALL PASS")
