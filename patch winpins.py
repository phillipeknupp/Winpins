"""
Corrige o bug do brilho do ellipse em make_tray_icon().
Roda antes da compilacao pelo build_winpins.bat.
"""
import sys

FILENAME = "winpins.py"

OLD = (
    "    d.ellipse([cx - head_r + 3, head_cy - head_r + 3, cx - 2, head_cy - 2],\n"
    "              fill=(255, 200, 200, 180))"
)

NEW = (
    "    shine_x0 = cx - head_r + 3\n"
    "    shine_y0 = head_cy - head_r + 3\n"
    "    shine_x1 = cx - 2\n"
    "    shine_y1 = head_cy - 2\n"
    "    if shine_x1 > shine_x0 and shine_y1 > shine_y0:\n"
    "        d.ellipse([shine_x0, shine_y0, shine_x1, shine_y1], fill=(255, 200, 200, 180))"
)

try:
    with open(FILENAME, "r", encoding="utf-8") as f:
        src = f.read()
except FileNotFoundError:
    print(f"ERRO: {FILENAME} nao encontrado na pasta atual.")
    sys.exit(1)

if OLD in src:
    patched = src.replace(OLD, NEW)
    with open(FILENAME, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"  Correcao aplicada com sucesso em {FILENAME}.")
elif NEW in src:
    print(f"  {FILENAME} ja estava corrigido. Nada a fazer.")
else:
    print(f"  AVISO: trecho esperado nao encontrado. Verifique se o arquivo e o correto.")

sys.exit(0)