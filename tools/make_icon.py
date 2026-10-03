"""Gera avatarize/assets/icon.png e icon.ico. Rodar: uv run python tools/make_icon.py"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "avatarize" / "assets"
S = 2048  # desenha grande e reduz (antialiasing)

STOPS = [(0.0, (79, 91, 255)), (0.55, (150, 74, 255)), (1.0, (255, 92, 160))]


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(size: int) -> Image.Image:
    """Gradiente diagonal (canto superior esquerdo -> inferior direito) com 3 cores."""
    line = Image.new("RGB", (512, 1))
    for i in range(512):
        t = i / 511
        for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
            if t0 <= t <= t1:
                line.putpixel((i, 0), lerp(c0, c1, (t - t0) / (t1 - t0)))
                break
    big = line.resize((int(size * 1.5), int(size * 1.5)), Image.BILINEAR).rotate(-45, resample=Image.BICUBIC)
    off = (big.width - size) // 2
    return big.crop((off, off, off + size, off + size))


def squircle(size: int, margin: float, n: float = 5.0) -> Image.Image:
    """Máscara de 'squircle' (superelipse), o formato dos ícones modernos."""
    r = size * (0.5 - margin)
    c = size / 2
    pts = []
    for i in range(720):
        a = 2 * math.pi * i / 720
        ca, sa = math.cos(a), math.sin(a)
        pts.append((c + r * math.copysign(abs(ca) ** (2 / n), ca), c + r * math.copysign(abs(sa) ** (2 / n), sa)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    return mask


def sparkle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    pts = []
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.22
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


def arc(draw: ImageDraw.ImageDraw, cx, cy, radius, width, a0, a1, fill) -> None:
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.arc(box, a0, a1, fill=fill, width=int(width))
    for a in (a0, a1):  # pontas arredondadas
        rad = math.radians(a)
        mid = radius - width / 2
        x, y = cx + mid * math.cos(rad), cy + mid * math.sin(rad)
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=fill)


def render(small: bool = False) -> Image.Image:
    """small=True: versão simplificada e mais grossa para 16-32 px."""
    W = S
    shape = squircle(W, 0.02 if small else 0.035)
    base = gradient(W).convert("RGBA")

    glow = Image.new("L", (W, W), 0)
    ImageDraw.Draw(glow).ellipse([-0.25 * W, -0.35 * W, 0.75 * W, 0.55 * W], fill=50)
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.12))
    base = Image.composite(Image.new("RGBA", (W, W), (255, 255, 255, 255)), base, glow)

    fg = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)
    white = (255, 255, 255, 255)
    hx, hy = 0.38 * W, 0.42 * W
    head = (0.155 if small else 0.135) * W
    d.ellipse([hx - head, hy - head, hx + head, hy + head], fill=white)
    top = hy + head + (0.05 if small else 0.06) * W
    d.rounded_rectangle([hx - 0.25 * W, top, hx + 0.25 * W, top + 0.5 * W], radius=0.21 * W, fill=white)

    stroke = (0.06 if small else 0.042) * W
    radii = [0.26, 0.36] if small else [0.235, 0.31, 0.385]
    alphas = [255, 190] if small else [255, 200, 140]
    for r, a in zip(radii, alphas):
        arc(d, hx, hy, r * W, stroke, -38, 38, (255, 255, 255, a))
    if not small:
        sparkle(d, 0.78 * W, 0.215 * W, 0.075 * W, (255, 236, 160, 255))
        sparkle(d, 0.865 * W, 0.335 * W, 0.032 * W, (255, 255, 255, 230))

    shadow = Image.new("RGBA", (W, W), (30, 10, 70, 0))
    shadow.putalpha(fg.getchannel("A").point(lambda v: v * 0.45).filter(ImageFilter.GaussianBlur(W * 0.02)))
    shadow = ImageChops.offset(shadow, 0, int(W * 0.015))

    art = Image.alpha_composite(Image.alpha_composite(base, shadow), fg)
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    out.paste(art, (0, 0), shape)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    full, small = render(), render(small=True)
    full.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    sizes = [256, 128, 64, 48, 32, 24, 16]
    imgs = [(small if s <= 32 else full).resize((s, s), Image.LANCZOS) for s in sizes]
    imgs[0].save(OUT / "icon.ico", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    print("ícones salvos em", OUT)


if __name__ == "__main__":
    main()
