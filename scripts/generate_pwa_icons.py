"""Generate PWA icons (run once): python scripts/generate_pwa_icons.py"""
import os

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Install Pillow: pip install pillow")
    raise

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "icons")
os.makedirs(OUT, exist_ok=True)


def draw_icon(size):
    img = Image.new("RGBA", (size, size), (2, 6, 23, 255))
    d = ImageDraw.Draw(img)
    margin = size // 8
    d.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 6,
        fill=(34, 211, 238, 255),
    )
    inner = size // 3
    d.ellipse(
        [size // 2 - inner // 2, size // 2 - inner // 2, size // 2 + inner // 2, size // 2 + inner // 2],
        fill=(2, 6, 23, 255),
    )
    return img


for s in (192, 512):
    path = os.path.join(OUT, f"icon-{s}.png")
    draw_icon(s).save(path, "PNG")
    print("Wrote", path)
