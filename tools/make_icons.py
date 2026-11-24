#!/usr/bin/env python3
"""진홍's 포토 갤러리 아이콘 생성 (PIL).
짙은 초록 그라데이션 + 살짝 기울인 흰 사진(폴라로이드) + 해·산 실루엣 + 따뜻한 점.
"""
import os
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 2048  # 작업 캔버스 (1024 좌표의 2배)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def gradient(size, c0, c1):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        for x in range(0, size, 4):
            tt = min(1.0, 0.15 + t * 0.7 + (x / size) * 0.25)
            c = lerp(c0, c1, tt)
            for dx in range(4):
                if x + dx < size:
                    px[x + dx, y] = c
    return img


def photo_layer(size):
    k = size / 1024.0
    lay = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    def sc(*v):
        return tuple(int(round(x * k)) for x in v)

    # 그림자
    sh = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(sc(250, 210, 790, 820), radius=int(46 * k), fill=(6, 26, 21, 150))
    sh = sh.filter(ImageFilter.GaussianBlur(int(40 * k)))
    lay.alpha_composite(sh, (int(16 * k), int(30 * k)))

    # 폴라로이드 흰 종이
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle(sc(238, 180, 786, 810), radius=int(44 * k), fill=(255, 253, 248, 255))

    # ── 사진 내용: 별도 캔버스에 그린 뒤 둥근 모서리로 잘라 붙인다 ──
    cw, ch = int(468 * k), int(430 * k)
    content = Image.new("RGB", (cw, ch), (0, 0, 0))
    cp = content.load()
    for y in range(ch):
        c = lerp((182, 219, 205), (247, 233, 206), (y / max(1, ch - 1)) ** 0.85)
        for x in range(cw):
            cp[x, y] = c
    cd = ImageDraw.Draw(content)

    def cc(x, y):
        return (int(round(x * k)), int(round(y * k)))

    # 해
    cd.ellipse([cc(318, 58), cc(412, 152)], fill=(240, 176, 106))
    # 뒷산
    cd.polygon([cc(0, 372), cc(150, 208), cc(300, 372)], fill=(96, 143, 122))
    # 앞산
    cd.polygon([cc(150, 392), cc(268, 262), cc(430, 392)], fill=(52, 99, 83))
    # 아래 언덕
    cd.rectangle([cc(0, 366), cc(468, 430)], fill=(38, 78, 64))

    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=int(20 * k), fill=255)
    lay.paste(content, (int(278 * k), int(220 * k)), mask)

    # 아래 고정 여백(폴라로이드)의 작은 점
    d = ImageDraw.Draw(lay)
    d.ellipse(sc(472, 706, 552, 786), fill=(226, 180, 140, 255))

    return lay.rotate(-7, resample=Image.BICUBIC, center=(512 * k, 512 * k))


def build(final=1024, maskable=False):
    inner = int(S * 0.74)
    canvas = gradient(S, (67, 122, 104), (20, 46, 38)).convert("RGBA")

    gloss = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse((-S * 0.5, -S * 0.75, S * 0.8, S * 0.4), fill=(190, 226, 210, 60))
    gloss = gloss.filter(ImageFilter.GaussianBlur(int(S * 0.07)))
    art = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    art.alpha_composite(gloss)

    lay = photo_layer(S)
    if maskable:
        small = lay.resize((int(S * 0.92), int(S * 0.92)), Image.LANCZOS)
        off = (S - small.size[0]) // 2
        art.alpha_composite(small, (off, off))
    else:
        art.alpha_composite(lay)

    canvas = Image.alpha_composite(canvas, art)

    if maskable:
        out = canvas
    else:
        m = Image.new("L", (S, S), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.225), fill=255)
        out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        out.paste(canvas, (0, 0), m)
    return out.resize((final, final), Image.LANCZOS)


def main():
    build(1024).save(os.path.join(OUT, "icon-1024.png"))
    build(512).save(os.path.join(OUT, "icon-512.png"))
    build(192).save(os.path.join(OUT, "icon-192.png"))
    build(512, maskable=True).convert("RGB").save(os.path.join(OUT, "icon-maskable-512.png"))
    build(180).save(os.path.join(OUT, "apple-touch-icon.png"))
    ico = build(64)
    ico.save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
