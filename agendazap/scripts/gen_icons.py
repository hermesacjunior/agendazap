"""Gera os PNGs do PWA (192/512 + apple-touch 180) com o logo AZ: fundo com
gradiente roxo full-bleed (seguro como maskable) e "AZ" branco em negrito
centralizado. Rode localmente:

    venv/Scripts/python.exe scripts/gen_icons.py

Os PNGs gerados sao commitados como assets estaticos; a producao nao precisa
do Pillow.
"""
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = "app/static/icons"
ACCENT_TOP = (91, 106, 248)    # #5b6af8 (canto superior)
ACCENT_BOT = (124, 58, 237)    # #7c3aed (canto inferior)
WHITE = (255, 255, 255, 255)

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
]


def _load_font(px):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, px)
        except Exception:
            continue
    return ImageFont.load_default()


def _vertical_gradient(size, top, bottom):
    base = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(base)
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b))
    return base.convert("RGBA")


def draw_icon(size):
    img = _vertical_gradient(size, ACCENT_TOP, ACCENT_BOT)
    draw = ImageDraw.Draw(img)
    text = "AZ"

    # Ajusta o tamanho da fonte para o "AZ" ocupar ~56% da largura (dentro da
    # safe zone de 80% exigida por icones maskable).
    target_w = size * 0.56
    px = int(size * 0.5)
    font = _load_font(px)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    if tw > 0:
        px = max(8, int(px * target_w / tw))
        font = _load_font(px)
        bbox = draw.textbbox((0, 0), text, font=font)

    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=WHITE)
    return img


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    draw_icon(192).save(f"{OUT_DIR}/icon-192.png")
    draw_icon(512).save(f"{OUT_DIR}/icon-512.png")
    # apple-touch: iOS aplica cantos arredondados sozinho -> fundo full-bleed.
    draw_icon(180).convert("RGB").save(f"{OUT_DIR}/apple-touch-icon.png")
    print("Gerados: icon-192.png, icon-512.png, apple-touch-icon.png em", OUT_DIR)


if __name__ == "__main__":
    main()
