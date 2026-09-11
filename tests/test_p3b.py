"""Phase 3b 스모크 — 이미지 업로드 · 아바타 · 진행/글 사진 · 신고 · 관리자."""
import io, json, urllib.request, urllib.error, urllib.parse
from _db import connect as _db_connect
from PIL import Image
Q = urllib.parse.quote

BASE = "http://127.0.0.1:8971"
OW = ("p3bowner", "오너삼", "hunter2pw")   # runserver.sh 의 OWNER_LOGIN_ID
A = ("p3ba", "에이삼비", "hunter2pw")
B = ("p3bb", "비이삼비", "hunter2pw")


def png_bytes(color=(120, 160, 140), size=(600, 800)):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return b.getvalue()


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


def upload(token, data, kind="post", fname="x.png", ctype="image/png"):
    bnd = "----b3b"
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


def get_url(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.headers.get("Content-Type"), len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None, 0


def show(l, r): print(f"  {l}: {r[0]}  {json.dumps(r[1], ensure_ascii=False)[:150]}")


def cleanup():
    c = _db_connect()
    cur = c.cursor(); ids = "('%s','%s','%s')" % (OW[0], A[0], B[0])
    cur.execute(f"update healthweb.app_user set pinned_post_id=null, avatar_media_id=null where login_id in {ids}")
    cur.execute(f"update healthweb.weight_entry set photo_media_id=null where login_id in {ids}")
    cur.execute(f"update healthweb.post set image_media_id=null where login_id in {ids}")
    cur.execute(f"delete from healthweb.report where reporter in {ids}")
    cur.execute(f"delete from healthweb.report where target_id in {ids}")
    for t in ("encouragement", "post_comment", "notification"):
        cur.execute(f"delete from healthweb.{t} where post_id in (select id from healthweb.post where login_id in {ids})")
    for t in ("challenge_checkin", "challenge_member", "notification", "post_comment",
              "encouragement", "post", "weight_entry", "media"):
        cur.execute(f"delete from healthweb.{t} where login_id in {ids}")
    cur.execute(f"delete from healthweb.notification where actor in {ids}")
    cur.execute(f"delete from healthweb.follow where follower in {ids} or followee in {ids}")
    cur.execute(f"delete from healthweb.user_block where blocker in {ids} or blocked in {ids}")
    cur.execute(f"delete from healthweb.challenge where owner in {ids}")
    cur.execute(f"delete from healthweb.app_user where login_id in {ids}")
    c.commit(); c.close(); print("  cleanup done")


cleanup()
tow = call("POST", "/auth/signup", {"login_id": OW[0], "name": OW[1], "password": OW[2]})[1]["token"]
ta = call("POST", "/auth/signup", {"login_id": A[0], "name": A[1], "password": A[2]})[1]["token"]
tb = call("POST", "/auth/signup", {"login_id": B[0], "name": B[1], "password": B[2]})[1]["token"]

print("1) 업로드 + 서빙")
r = upload(ta, png_bytes(), "post"); show("upload png", r)
assert r[0] == 200 and r[1]["url"].endswith(".jpg"), r
mid = r[1]["id"]
st, ct, ln = get_url(r[1]["url"])
assert st == 200 and ct == "image/jpeg" and ln > 100, (st, ct, ln)
st, ct, ln = get_url(r[1]["thumb_url"]); assert st == 200
assert r[1]["width"] <= 1280 and r[1]["height"] <= 1280

print("2) 거부 — 비이미지 / kind 오류 / 초대형")
assert upload(ta, b"not an image", "post", "x.txt", "text/plain")[0] == 400
assert upload(ta, png_bytes(), "bogus")[0] == 400
big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (9 * 1024 * 1024)
assert upload(ta, big, "post")[0] == 413

print("3) 아바타")
av = upload(ta, png_bytes((200, 120, 90)), "avatar")[1]["id"]
show("set avatar", call("PATCH", "/auth/me", {"avatar_media_id": av}, token=ta))
me = call("GET", "/auth/me", token=ta)[1]
assert me["avatar"] and me["avatar"]["url"], me
prof = call("GET", f"/u/{Q(A[1])}", token=tb)[1]
assert prof["avatar"] and prof["avatar"]["thumb_url"]
call("PATCH", "/auth/me", {"avatar_media_id": 0}, token=ta)
assert call("GET", "/auth/me", token=ta)[1]["avatar"] is None

print("4) 글 이미지 — 피드/상세에 노출 + 작성자 아바타")
call("PATCH", "/auth/me", {"avatar_media_id": upload(ta, png_bytes((90, 90, 200)), "avatar")[1]["id"]}, token=ta)
img = upload(ta, png_bytes((160, 90, 90)), "post")[1]["id"]
pid = call("POST", "/posts", {"kind": "resolve", "body": "사진 있는 글", "image_media_id": img}, token=ta)[1]["id"]
r = call("GET", "/feed?scope=all", token=tb)
it = next(i for i in r[1]["items"] if i["id"] == pid)
assert it["image"] and it["image"]["url"], it
assert it["avatar"] and it["avatar"]["url"], it
det = call("GET", f"/posts/{pid}", token=tb)[1]
assert det["image"]["url"]

print("5) 남의 이미지 첨부 → 400")
assert call("POST", "/posts", {"kind": "resolve", "body": "훔친 이미지", "image_media_id": img}, token=tb)[0] == 400

print("6) 진행 사진 — share 필수")
ph = upload(ta, png_bytes((140, 140, 140)), "progress")[1]["id"]
assert call("POST", "/weights", {"weight": 70.0, "share": False, "photo_media_id": ph}, token=ta)[0] == 400
r = call("POST", "/weights", {"weight": 70.0, "logged_at": "2026-09-09T08:00", "share": True, "photo_media_id": ph}, token=ta)
show("weight+photo", r); wpost = r[1]["post_id"]
w = call("GET", "/weights", token=ta)[1]
assert any(e.get("photo") and e["photo"]["url"] for e in w["entries"]), w
lp = call("GET", f"/posts/{wpost}", token=tb)[1]
assert lp["image"]["url"]

print("7) media 삭제 — 미사용만")
free = upload(ta, png_bytes(), "post")[1]["id"]
assert call("DELETE", f"/media/{free}", token=ta)[0] == 200
assert call("DELETE", f"/media/{img}", token=ta)[0] == 400   # 글에 사용 중

print("8) 글 삭제 → 이미지 GC")
gcimg = upload(ta, png_bytes((10, 20, 30)), "post")
gcurl = gcimg[1]["url"]; gcpid = call("POST", "/posts", {"kind": "reflect", "body": "지울 글", "image_media_id": gcimg[1]["id"]}, token=ta)[1]["id"]
assert get_url(gcurl)[0] == 200
call("DELETE", f"/posts/{gcpid}", token=ta)
assert get_url(gcurl)[0] == 404, "글 삭제 시 이미지 파일도 정리"

print("9) 신고 + 관리자 큐")
show("report", call("POST", "/reports", {"target_kind": "post", "target_id": str(pid), "reason": "테스트"}, token=tb))
call("POST", "/reports", {"target_kind": "post", "target_id": str(pid)}, token=tb)  # 중복
assert call("GET", "/admin/reports", token=ta)[0] == 403, "비오너 차단"
ar = call("GET", "/admin/reports", token=tow); show("admin list", ar)
assert len(ar[1]["items"]) == 1 and ar[1]["items"][0]["context"]["post_id"] == pid
rid = ar[1]["items"][0]["id"]
assert call("GET", "/auth/me", token=tow)[1]["is_owner"] is True
assert call("GET", "/auth/me", token=tow)[1]["open_reports"] == 1

print("10) 관리자 처리 — 글 삭제")
call("POST", f"/admin/reports/{rid}/resolve", {"action": "delete_post"}, token=tow)
assert call("GET", f"/posts/{pid}", token=tb)[0] == 404
assert call("GET", "/admin/reports", token=tow)[1]["items"] == []
assert call("GET", "/auth/me", token=tow)[1]["open_reports"] == 0

cleanup()
print("\n\u2705 ALL PASS")
