"""Gera os PNGs do PWA (192/512 + apple-touch 180) a partir do mesmo desenho
do icon.svg: fundo roxo full-bleed (seguro como maskable) + calendario e check
brancos centrados na safe zone (~80%). Rode localmente:

    venv/Scripts/python.exe scripts/gen_icons.py

Os PNGs gerados sao commitados como assets estaticos; a producao nao precisa
do Pillow.
"""
from PIL import Image, ImageDraw

OUT_DIR = "app/static/icons"
ACCENT_TOP = (91, 106, 248)    # #5b6af8
ACCENT_BOT = (124, 91, 248)    # #7c5bf8
WHITE = (255, 255, 255, 255)


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


def _scaled(coord, size):
    return coord * size / 512.0


def draw_icon(size, transparent_bg=False):
    if transparent_bg:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle(
            [0, 0, size - 1, size - 1], radius=_scaled(110, size),
            fill=ACCENT_TOP,
        )
    else:
        img = _vertical_gradient(size, ACCENT_TOP, ACCENT_BOT)

    draw = ImageDraw.Draw(img)
    sw = max(2, int(_scaled(20, size)))           # stroke principal
    cw = max(2, int(_scaled(26, size)))           # stroke do check

    def s(v):
        return _scaled(v, size)

    # Corpo do calendario (retangulo arredondado, contorno branco)
    draw.rounded_rectangle(
        [s(128), s(150), s(384), s(384)], radius=s(34),
        outline=WHITE, width=sw,
    )
    # Linha do cabecalho
    draw.line([(s(128), s(214)), (s(384), s(214))], fill=WHITE, width=sw)
    # Argolas
    draw.line([(s(190), s(128)), (s(190), s(172))], fill=WHITE, width=sw)
    draw.line([(s(322), s(128)), (s(322), s(172))], fill=WHITE, width=sw)
    # Check
    draw.line(
        [(s(196), s(300)), (s(236), s(340)), (s(320), s(248))],
        fill=WHITE, width=cw, joint="curve",
    )
    return img


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    draw_icon(192).save(f"{OUT_DIR}/icon-192.png")
    draw_icon(512).save(f"{OUT_DIR}/icon-512.png")
    # apple-touch: iOS aplica cantos arredondados sozinho -> fundo full-bleed,
    # sem transparencia.
    draw_icon(180).convert("RGB").save(f"{OUT_DIR}/apple-touch-icon.png")
    print("Gerados: icon-192.png, icon-512.png, apple-touch-icon.png em", OUT_DIR)


if __name__ == "__main__":
    main()
