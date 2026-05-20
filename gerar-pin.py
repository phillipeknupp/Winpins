"""
Gera winpins_icon.ico na pasta atual.
Uso: python gerar_icone.py
"""
from PIL import Image, ImageDraw

def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bg    = (30, 60, 120, 255)
    pin   = (220, 60, 60, 255)
    shine = (255, 200, 200, 180)

    m = max(2, size // 16)
    d.ellipse([m, m, size - m, size - m], fill=bg)

    cx      = size // 2
    head_r  = max(2, size // 5)
    head_cy = size // 3
    d.ellipse([cx-head_r, head_cy-head_r, cx+head_r, head_cy+head_r], fill=pin)

    # brilho (só se couber)
    sx0, sy0, sx1, sy1 = cx-head_r+3, head_cy-head_r+3, cx-2, head_cy-2
    if sx1 > sx0 and sy1 > sy0:
        d.ellipse([sx0, sy0, sx1, sy1], fill=shine)

    # haste
    hw  = max(1, size // 14)
    ht  = head_cy + head_r - 1
    hb  = size - m - max(2, size//10)
    d.rectangle([cx-hw, ht, cx+hw, hb], fill=pin)
    d.polygon([(cx-hw-1, hb), (cx+hw+1, hb), (cx, hb+max(3, size//10))], fill=pin)

    return img.convert("RGBA")


sizes  = [16, 24, 32, 48, 64, 128, 256]
images = [make_icon(s) for s in sizes]
images[0].save(
    "winpins_icon.ico",
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=images[1:],
)
print("Icone salvo: winpins_icon.ico")