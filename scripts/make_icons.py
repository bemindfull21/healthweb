"""홈 화면 아이콘 생성 — 좌우 절반 두 색, 가운데 흰색 M. 정사각형 풀블리드(모서리 안 둥글림).

OS(iOS/Android)가 자체적으로 모서리를 둥글리므로 여기서 미리 둥글리면
배경색이 여백처럼 비쳐 보인다 — 그래서 네 귀퉁이까지 색을 꽉 채운다.

실행: api/venv 의 python으로 (Pillow 있음) — 이 파일 기준 상위 폴더에 PNG 3장 저장.
    ../api/venv/Scripts/python.exe scripts/make_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent

GREEN = (47, 107, 79, 255)   # --accent / weight
ROSE = (181, 72, 111, 255)   # --love
WHITE = (255, 255, 255, 255)

S = 1024  # 마스터 해상도


def make_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 좌(green)/우(rose) 절반, 모서리까지 꽉 채움
    d.rectangle([0, 0, S // 2, S], fill=GREEN)
    d.rectangle([S // 2, 0, S, S], fill=ROSE)

    # 굵은 M (둥근 이음새) — 0..100 좌표계를 S로 스케일, 폰트 없이 폴리라인으로 직접 그림
    def p(x, y):
        return (x / 100 * S, y / 100 * S)
    pts = [p(26, 76), p(26, 24), p(50, 54), p(74, 24), p(74, 76)]
    width = int(0.135 * S)
    d.line(pts, fill=WHITE, width=width, joint="curve")
    r = width / 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)
    return img


if __name__ == "__main__":
    master = make_master().convert("RGB")  # 알파 없음 — iOS가 투명을 검은색으로 표시하는 문제 방지
    master.save(OUT / "icon-512.png")
    master.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    master.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    print(f"saved icon-512.png, icon-192.png, apple-touch-icon.png in {OUT}")
