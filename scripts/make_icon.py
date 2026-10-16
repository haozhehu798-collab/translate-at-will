# -*- coding: utf-8 -*-
"""生成应用图标 app.ico"""
from PIL import Image, ImageDraw, ImageFont
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# 脚本位于 scripts/，生成的图标输出到同级的 src/app.ico
SRC_DIR = os.path.join(os.path.dirname(HERE), "src")
os.makedirs(SRC_DIR, exist_ok=True)


def make_icon(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    # 圆角方形底
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=(64, 128, 245, 255))
    # 顶部高光
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.rounded_rectangle(
        [int(size * 0.08), int(size * 0.06), int(size * 0.92), int(size * 0.48)],
        radius=int(size * 0.18),
        fill=(255, 255, 255, 38),
    )
    img = Image.alpha_composite(img, highlight)
    d = ImageDraw.Draw(img)
    # 白色“译”字
    font = None
    for fp in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, int(size * 0.62))
                break
            except Exception:
                pass
    text = "译"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - size * 0.02),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )
    return img


if __name__ == "__main__":
    base = make_icon(256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icons = [base.resize(s, Image.LANCZOS) for s in sizes]
    out = os.path.join(SRC_DIR, "app.ico")
    icons[0].save(out, format="ICO", sizes=sizes, append_images=icons[1:])
    print("saved:", out)
