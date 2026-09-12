"""ERP(구매 기록) 스모크 — 권한 게이팅 + 추출 + 저장/조회/삭제."""
import io, json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect
from PIL import Image

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


def png_bytes(color=(200, 200, 200), size=(300, 300)):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return b.getvalue()


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

print("5) 영수증 이미지 업로드 + AI 추출 (실제 Gemini 호출, 텍스트 없는 이미지라 items=[] 예상)")
up = upload(tok_u, png_bytes(), kind="receipt")
show("upload", up); assert up[0] == 200
mid = up[1]["id"]
r = call("POST", "/purchases/extract", {"media_id": mid}, token=tok_u)
show("extract", r); assert r[0] == 200 and isinstance(r[1]["items"], list)

print("6) 수동 항목으로 저장 (위안화+원화 둘 다)")
r = call("POST", "/purchases", {
    "items": [
        {"shop_name": "타오바오샵", "product_name": "무선 이어폰", "option_text": "블랙", "quantity": 2, "price_cny": 99.9, "price_krw": 19500},
        {"shop_name": None, "product_name": "케이스", "quantity": 1, "price_cny": 15, "price_krw": None},
    ],
    "order_date": "2026-09-10", "source_media_id": mid,
}, token=tok_u)
show("save", r); assert r[0] == 200 and len(r[1]["ids"]) == 2
ids = r[1]["ids"]

print("7) 목록 + 합계 확인")
r = call("GET", "/purchases", token=tok_u)
show("list", r); assert r[0] == 200
items = r[1]["items"]
assert len(items) == 2, items
assert r[1]["total_krw"] == 19500, r[1]
assert round(r[1]["total_cny"], 1) == 114.9, r[1]

print("8) 상품명 비어있으면 저장 거부")
r = call("POST", "/purchases", {"items": [{"product_name": "  "}]}, token=tok_u)
show("empty product", r); assert r[0] == 400

print("9) ERP 권한이 있어도 남의 구매 기록은 못 지움 (자기 것만 GET/DELETE 대상)")
r = call("PATCH", f"/admin/users/{Q(U2[1])}/erp-access", {"erp_access": True}, token=tok_ow)
assert r[0] == 200
r = call("DELETE", f"/purchases/{ids[0]}", token=tok_u2)
show("other erp user delete item", r); assert r[0] == 404

print("10) 본인 삭제 성공")
r = call("DELETE", f"/purchases/{ids[0]}", token=tok_u)
show("delete", r); assert r[0] == 200
r = call("GET", "/purchases", token=tok_u)
assert len(r[1]["items"]) == 1, r[1]

print("11) 오너가 권한 회수하면 다시 403")
r = call("PATCH", f"/admin/users/{Q(U[1])}/erp-access", {"erp_access": False}, token=tok_ow)
assert r[0] == 200
r = call("GET", "/purchases", token=tok_u)
show("revoked", r); assert r[0] == 403

cleanup()
print("\n✅ ALL PASS")
