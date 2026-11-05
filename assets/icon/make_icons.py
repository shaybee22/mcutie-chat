"""Generate every Mcutie Chat icon asset from assets/icon/mcutie-icon-source.png.

    python assets/icon/make_icons.py [--fit-dp 33] [--preview DIR]

Needs Pillow and numpy. Writes:
  AndroidApp/icon/icon.png          legacy launcher icon (512, rounded square, transparent corners)
  AndroidApp/icon/icon_fg.png       adaptive icon foreground (432 = 108dp, artwork on transparent)
  AndroidApp/icon/icon_bg.png       adaptive icon background (432, solid colour)
  AndroidApp/icon/presplash.jpg     presplash (1024, icon centred on the solid colour)
  AndroidApp/icon/mcutie-icon.png   Kivy desktop window icon (256)
  mcutie-icon.ico, mcutie-icon.png  desktop client window/taskbar/.exe icon (repo root)
  Linux/mcutie-icon.png             desktop client icon for the Linux build
and prints the background colour to use for android.presplash_color.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SOURCE = os.path.join(HERE, "mcutie-icon-source.png")

ADAPTIVE_PX = 432          # 108 dp at xxxhdpi (4 px/dp)
PX_PER_DP = ADAPTIVE_PX / 108
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def crop_square(img):
    """Centred square around the opaque rounded square (drops the transparent margin + shadow)."""
    alpha = np.asarray(img)[..., 3]
    ys, xs = np.nonzero(alpha > 200)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    return img.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side))


def split_layers(square):
    """Split the flattened artwork into (background colour, per-pixel background, foreground RGBA)."""
    arr = np.asarray(square).astype(np.float64)
    rgb, alpha = arr[..., :3], arr[..., 3] / 255.0
    lum = luminance(rgb)
    inside = alpha > 0.8
    # Shrink "inside" so the rounded square's lighter rim never counts as foreground artwork
    # (pad with zeros first: MinFilter repeats edge pixels, so the outermost row/column of the
    # crop - the square's edge itself - would otherwise never be trimmed)
    rim = int(square.width * 0.025) | 1
    pad = rim
    padded = Image.new("L", (square.width + 2 * pad, square.height + 2 * pad), 0)
    padded.paste(Image.fromarray((inside * 255).astype(np.uint8)), (pad, pad))
    inside_img = padded.filter(ImageFilter.MinFilter(rim)).crop((pad, pad, pad + square.width, pad + square.height))
    inside = np.asarray(inside_img) > 127
    dark = inside & (lum < 60)
    bg_colour = np.median(rgb[dark], axis=0)

    # Per-pixel background estimate: blur only the dark (background) pixels (normalised convolution)
    radius = square.width / 25
    weight = Image.fromarray((dark * 255).astype(np.uint8))
    w_blur = np.asarray(weight.filter(ImageFilter.GaussianBlur(radius))).astype(np.float64) / 255.0
    bg_est = np.empty_like(rgb)
    for c in range(3):
        chan = Image.fromarray(np.clip(rgb[..., c] * dark, 0, 255).astype(np.uint8))
        c_blur = np.asarray(chan.filter(ImageFilter.GaussianBlur(radius))).astype(np.float64)
        bg_est[..., c] = np.where(w_blur > 1e-3, c_blur / np.maximum(w_blur, 1e-3), bg_colour[c])

    # Foreground alpha from how much brighter than the background each pixel is
    lum_bg = luminance(bg_est)
    # Reference brightness of the solid line cores (not the near-white highlights), so solid
    # lines get alpha 1 and keep their exact colour; only the glow is reconstructed
    lum_line = np.median(lum[inside & (lum > 150)])
    fg_a = np.clip((lum - lum_bg) / np.maximum(lum_line - lum_bg, 1), 0, 1)
    fg_a = np.where(fg_a < 0.03, 0, fg_a) * inside
    # Un-premultiply against the local background so the glow stays soft over a solid colour
    safe_a = np.maximum(fg_a, 1e-3)[..., None]
    fg_rgb = np.clip((rgb - (1 - fg_a[..., None]) * bg_est) / safe_a, 0, 255)
    fg = np.dstack([fg_rgb, fg_a * 255]).astype(np.uint8)
    return tuple(int(round(v)) for v in bg_colour), Image.fromarray(fg, "RGBA")


def adaptive_foreground(fg, fit_dp):
    """Scale the artwork so every clearly visible pixel lies inside a circle of radius fit_dp."""
    a = np.asarray(fg)[..., 3]
    ys, xs = np.nonzero(a > 64)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    r_src = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2).max()
    scale = fit_dp * PX_PER_DP / r_src
    new = fg.resize((round(fg.width * scale), round(fg.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGBA", (ADAPTIVE_PX, ADAPTIVE_PX), (0, 0, 0, 0))
    canvas.alpha_composite(new, (round(ADAPTIVE_PX / 2 - cx * scale), round(ADAPTIVE_PX / 2 - cy * scale)))
    return canvas


def mask(shape, size):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    if shape == "circle":
        d.ellipse((0, 0, size - 1, size - 1), fill=255)
    elif shape == "rounded":
        d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=255)
    else:  # squircle (superellipse n=4)
        yy, xx = np.mgrid[0:size, 0:size]
        u, v = (xx - (size - 1) / 2) / (size / 2), (yy - (size - 1) / 2) / (size / 2)
        m = Image.fromarray(((np.abs(u) ** 4 + np.abs(v) ** 4) <= 1).astype(np.uint8) * 255)
    return m


def previews(out_dir, square, fg432, bg_colour, presplash):
    os.makedirs(out_dir, exist_ok=True)
    # The launcher shows the central 72 dp of the 108 dp adaptive canvas, clipped by its mask
    full = Image.new("RGBA", (ADAPTIVE_PX, ADAPTIVE_PX), bg_colour + (255,))
    full.alpha_composite(fg432)
    view = full.crop((int(18 * PX_PER_DP), int(18 * PX_PER_DP), int(90 * PX_PER_DP), int(90 * PX_PER_DP)))
    sizes = [192, 96, 48, 32]
    rows = [("legacy", None), ("circle", "circle"), ("squircle", "squircle"), ("rounded", "rounded")]
    sheet = Image.new("RGB", (sum(sizes) + 20 * (len(sizes) + 1), (192 + 20) * len(rows) + 20), (235, 235, 235))
    y = 20
    for name, shape in rows:
        x = 20
        for s in sizes:
            src = square if shape is None else view
            img = src.resize((s, s), Image.LANCZOS)
            sheet.paste(img, (x, y), img if shape is None else mask(shape, s))
            x += s + 20
        y += 192 + 20
    sheet.save(os.path.join(out_dir, "icon-sheet.png"))
    sheet48 = sheet.crop((20 + 192 + 20 + 96 + 20 - 4, 16, 20 + 192 + 20 + 96 + 20 + 48 + 4, sheet.height - 16))
    sheet48.resize((sheet48.width * 4, sheet48.height * 4), Image.NEAREST).save(os.path.join(out_dir, "icon-48px-zoom.png"))
    safe = full.copy()
    ImageDraw.Draw(safe).ellipse((ADAPTIVE_PX / 2 - 33 * PX_PER_DP,) * 2 + (ADAPTIVE_PX / 2 + 33 * PX_PER_DP,) * 2,
                                 outline=(255, 80, 80, 255), width=2)
    ImageDraw.Draw(safe).rectangle((18 * PX_PER_DP,) * 2 + (90 * PX_PER_DP,) * 2, outline=(80, 200, 255, 255), width=2)
    safe.save(os.path.join(out_dir, "adaptive-safe-zone.png"))
    phone = Image.new("RGB", (540, 1170), bg_colour)
    p = presplash.resize((540, 540))
    phone.paste(p, (0, (1170 - 540) // 2))
    phone.save(os.path.join(out_dir, "presplash-on-phone.png"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fit-dp", type=float, default=33, help="artwork radius in dp (33 = Android safe zone)")
    ap.add_argument("--preview", help="also write preview sheets to this directory")
    args = ap.parse_args()

    square = crop_square(Image.open(SOURCE).convert("RGBA"))
    bg_colour, fg = split_layers(square)
    hex_colour = "#%02X%02X%02X" % bg_colour

    out = os.path.join(ROOT, "AndroidApp", "icon")
    os.makedirs(out, exist_ok=True)
    square.resize((512, 512), Image.LANCZOS).save(os.path.join(out, "icon.png"), optimize=True)
    fg432 = adaptive_foreground(fg, args.fit_dp)
    fg432.save(os.path.join(out, "icon_fg.png"), optimize=True)
    Image.new("RGB", (ADAPTIVE_PX, ADAPTIVE_PX), bg_colour).save(os.path.join(out, "icon_bg.png"), optimize=True)

    presplash = Image.new("RGBA", (1024, 1024), bg_colour + (255,))
    logo = square.resize((390, 390), Image.LANCZOS)
    presplash.alpha_composite(logo, ((1024 - 390) // 2, (1024 - 390) // 2))
    presplash.convert("RGB").save(os.path.join(out, "presplash.jpg"), quality=92)

    icon256 = square.resize((256, 256), Image.LANCZOS)
    icon256.save(os.path.join(out, "mcutie-icon.png"), optimize=True)
    icon256.save(os.path.join(ROOT, "mcutie-icon.png"), optimize=True)
    icon256.save(os.path.join(ROOT, "Linux", "mcutie-icon.png"), optimize=True)
    square.save(os.path.join(ROOT, "mcutie-icon.ico"), sizes=[(s, s) for s in ICO_SIZES])

    if args.preview:
        previews(args.preview, square, fg432, bg_colour, presplash)
    print(f"crop {square.size[0]}px, background {hex_colour}, adaptive fit {args.fit_dp} dp")
    print(f"android.presplash_color = {hex_colour}")


if __name__ == "__main__":
    main()
