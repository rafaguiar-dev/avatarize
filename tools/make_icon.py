"""Gera avatarize/assets/icon.png e icon.ico. Rodar: uv run python tools/make_icon.py"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "avatarize" / "assets"
S = 2048  # desenha grande e reduz (antialiasing)

PINK, PINK_LIGHT = (255, 61, 132), (255, 138, 192)
BG_TOP, BG_BOTTOM = (40, 40, 45), (13, 13, 15)
STOPS = [(0.0, PINK), (1.0, PINK_LIGHT)]


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


def hgradient(size: int, x0: float, x1: float) -> Image.Image:
    """Gradiente horizontal rosa -> rosa-claro entre x0 e x1 (frações da largura)."""
    line = Image.new("RGB", (size, 1))
    for x in range(size):
        t = min(1.0, max(0.0, (x / size - x0) / (x1 - x0)))
        line.putpixel((x, 0), lerp(PINK, PINK_LIGHT, t))
    return line.resize((size, size), Image.NEAREST)


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
    """Tema Grafite: fundo grafite + desenho em gradiente rosa-choque.
    small=True: versão simplificada e mais grossa para 16-32 px."""
    W = S
    shape = squircle(W, 0.02 if small else 0.035)

    base = Image.new("RGBA", (W, W), BG_TOP)
    shade = Image.new("L", (1, 256))
    for y in range(256):
        shade.putpixel((0, y), y)
    base = Image.composite(Image.new("RGBA", (W, W), BG_BOTTOM), base, shade.resize((W, W)))
    for (cx, cy, rad, color, alpha) in ((0.25, 0.4, 0.5, PINK, 34), (0.8, 0.65, 0.45, PINK_LIGHT, 30)):
        glow = Image.new("L", (W, W), 0)
        ImageDraw.Draw(glow).ellipse([(cx - rad) * W, (cy - rad) * W, (cx + rad) * W, (cy + rad) * W], fill=alpha)
        base = Image.composite(Image.new("RGBA", (W, W), color + (255,)), base, glow.filter(ImageFilter.GaussianBlur(W * 0.16)))

    mask = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(mask)
    hx, hy = 0.38 * W, 0.43 * W
    head = (0.15 if small else 0.13) * W
    d.ellipse([hx - head, hy - head, hx + head, hy + head], fill=255)
    top = hy + head + (0.05 if small else 0.055) * W
    d.rounded_rectangle([hx - 0.24 * W, top, hx + 0.24 * W, top + 0.5 * W], radius=0.2 * W, fill=255)
    stroke = (0.06 if small else 0.042) * W
    radii = [0.255, 0.355] if small else [0.23, 0.305, 0.38]
    alphas = [255, 190] if small else [255, 200, 140]
    for r, a in zip(radii, alphas):
        arc(d, hx, hy, r * W, stroke, -38, 38, a)

    fill = hgradient(W, 0.16, 0.78).convert("RGBA")
    glyph = fill.copy()
    glyph.putalpha(mask)
    halo = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    halo.paste(fill, (0, 0), mask.point(lambda v: v * 0.6).filter(ImageFilter.GaussianBlur(W * 0.035)))

    art = Image.alpha_composite(Image.alpha_composite(base, halo), glyph)
    if not small:
        d2 = ImageDraw.Draw(art)
        sparkle(d2, 0.775 * W, 0.215 * W, 0.07 * W, (238, 240, 250, 255))
        sparkle(d2, 0.86 * W, 0.33 * W, 0.03 * W, (255, 194, 218, 230))

    edge = Image.new("L", (W, W), 0)
    edge.paste(255, (0, 0), shape)
    inner = edge.filter(ImageFilter.MinFilter(9))
    rim = ImageChops.subtract(edge, inner).point(lambda v: v * 0.22)
    art = Image.composite(Image.new("RGBA", (W, W), (200, 200, 208, 255)), art, rim)

    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    out.paste(art, (0, 0), shape)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    full, small = render(), render(small=True)
    full.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    full.resize((256, 256), Image.LANCZOS).save(OUT.parent / "web" / "logo.png")
    sizes = [256, 128, 64, 48, 32, 24, 16]
    imgs = [(small if s <= 32 else full).resize((s, s), Image.LANCZOS) for s in sizes]
    imgs[0].save(OUT / "icon.ico", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    print("ícones salvos em", OUT)


if __name__ == "__main__":
    main()
