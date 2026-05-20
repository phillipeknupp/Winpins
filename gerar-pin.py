"""
Gera winpins_icon.ico compatível com PyInstaller e Windows Explorer.
Usa ICO binário puro (sem depender do encoder PIL) para máxima compatibilidade.

Uso: python gerar_icone.py
"""
import struct
import io
from PIL import Image, ImageDraw


# ── Desenho do alfinete ───────────────────────────────────────────────────────

def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    m  = max(2, size // 16)
    d.ellipse([m, m, size - m, size - m], fill=(30, 60, 120, 255))

    cx, head_r, head_cy = size // 2, max(2, size // 5), size // 3
    d.ellipse([cx-head_r, head_cy-head_r, cx+head_r, head_cy+head_r],
              fill=(220, 60, 60, 255))

    sx0, sy0, sx1, sy1 = cx-head_r+3, head_cy-head_r+3, cx-2, head_cy-2
    if sx1 > sx0 and sy1 > sy0:
        d.ellipse([sx0, sy0, sx1, sy1], fill=(255, 200, 200, 180))

    hw = max(1, size // 14)
    ht = head_cy + head_r - 1
    hb = size - m - max(2, size // 10)
    d.rectangle([cx-hw, ht, cx+hw, hb], fill=(220, 60, 60, 255))
    tip = max(3, size // 10)
    d.polygon([(cx-hw-1, hb), (cx+hw+1, hb), (cx, hb+tip)],
              fill=(220, 60, 60, 255))

    return img


# ── Geração do ICO binário puro ───────────────────────────────────────────────

def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_ico(sizes) -> bytes:
    """
    Monta um arquivo .ico válido manualmente.
    Formato ICO:
      - Header  : 6 bytes
      - Diretório: N × 16 bytes
      - Dados   : N blocos PNG (Windows Vista+ aceita PNG dentro do ICO)
    """
    images = []
    for s in sizes:
        img  = make_icon(s)
        data = image_to_png_bytes(img)
        images.append((s, data))

    count = len(images)

    # Header: reserved=0, type=1 (ICO), count
    header = struct.pack("<HHH", 0, 1, count)

    # Cada entrada do diretório: 16 bytes
    # width, height, color_count, reserved, planes, bit_count, size, offset
    dir_size   = count * 16
    data_offset = 6 + dir_size

    directory = b""
    chunks    = b""
    offset    = data_offset

    for s, data in images:
        w = h = s if s < 256 else 0   # 0 significa 256 no formato ICO
        entry = struct.pack(
            "<BBBBHHII",
            w, h,       # width, height (0 = 256)
            0,          # color count (0 = sem paleta)
            0,          # reserved
            1,          # planes
            32,         # bit count
            len(data),  # tamanho dos dados
            offset,     # offset a partir do início do arquivo
        )
        directory += entry
        chunks    += data
        offset    += len(data)

    return header + directory + chunks


# ── Main ──────────────────────────────────────────────────────────────────────

SIZES  = [16, 24, 32, 48, 64, 128, 256]
OUTPUT = "winpins_icon.ico"

ico_bytes = build_ico(SIZES)
with open(OUTPUT, "wb") as f:
    f.write(ico_bytes)

print(f"Icone gerado: {OUTPUT}  ({len(ico_bytes):,} bytes, {len(SIZES)} tamanhos)")
print("Tamanhos incluidos:", SIZES)
