#!/usr/bin/env python3
"""
Generates the megapack's cover/thumbnail image for the ETS2 Mod Manager listing
(src/cover.jpg). The megapack build copies it into every part archive, where
manifest.sii's `icon:` field references it. SCS requires a 276x162 JPEG.

Same style as the AI Traffic megapack (logo left, title block right, skyline,
road, light trails, amber version badge). Its cars are replaced by a convoy of
trucks with trailers: box trailers and a lowboy carrying machinery, outlined by
amber side-marker lights, receding in the right lane, oncoming headlights in the
left lane.

Composited at 4x (1104x648) then downscaled for anti-aliasing. The version
badge is read from megapack.yaml's package.version, so rerun this before every
build that bumps the version.
"""
import random
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = ROOT / "logo.png"
OUT_PATH = ROOT / "src" / "cover.jpg"
CONFIG_PATH = ROOT / "megapack.yaml"

SCALE = 4
FINAL_SIZE = (276, 162)
CANVAS_SIZE = (FINAL_SIZE[0] * SCALE, FINAL_SIZE[1] * SCALE)

FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
FONT_REG = r"C:\Windows\Fonts\arial.ttf"

BG_TOP = (10, 12, 16)
BG_BOTTOM = (24, 20, 14)
TITLE_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (255, 196, 84)
SKYLINE_COLOR = (5, 5, 9)
SKYLINE_RIM_COLOR = (255, 170, 70)
WINDOW_COLOR = (255, 196, 84)
HEADLIGHT_COLOR = (255, 238, 200)
TAILLIGHT_COLOR = (255, 48, 36)
MARKER_COLOR = (255, 150, 40)
BADGE_COLOR = (255, 196, 84)
BADGE_TEXT_COLOR = (20, 16, 10)

ROAD_TOP = 0.72  # fraction of height where the road meets the skyline
ROAD_BOTTOM_X = (0.30, 0.70)
ROAD_TOP_X = (0.44, 0.56)


def read_version():
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    version = (cfg.get("package") or {}).get("version")
    if not version:
        raise SystemExit(f"No package.version in {CONFIG_PATH}")
    return str(version)


def make_background(size):
    w, h = size
    img = Image.new("RGB", size, BG_BOTTOM)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def add_skyline(img):
    """City silhouette in the thin gap between the text block and the road,
    hidden behind the logo where they overlap (runs before paste_logo). No tall
    tower as in Economy: the longer subtitle reaches down into that spot."""
    w, h = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(7)  # fixed seed - stable output across regenerations

    baseline = int(h * (ROAD_TOP + 0.002))
    x = 0.0
    while x < w:
        bw = rng.uniform(w * 0.028, w * 0.06)
        top_frac = rng.uniform(0.685, 0.705)
        top = int(h * top_frac)
        draw.rectangle([x, top, x + bw, baseline], fill=(*SKYLINE_COLOR, 255))
        draw.line([(x, top), (x + bw, top)], fill=(*SKYLINE_RIM_COLOR, 90), width=max(1, int(h * 0.004)))

        rows = max(1, int((baseline - top) / (h * 0.02)))
        cols = max(1, int(bw / (w * 0.011)))
        for r in range(rows):
            for c in range(cols):
                if rng.random() < 0.3:
                    wx = x + (c + 0.5) * (bw / cols)
                    wy = top + (r + 0.7) * ((baseline - top) / rows)
                    draw.rectangle(
                        [wx - w * 0.0025, wy - h * 0.004, wx + w * 0.0025, wy + h * 0.004],
                        fill=(*WINDOW_COLOR, 200),
                    )
        x += bw + rng.uniform(w * 0.004, w * 0.012)
    return img


def road_point(img, lane, depth):
    """Point on the road. lane: -1 (left edge) .. 1 (right edge);
    depth: 0 (bottom of image) .. 1 (horizon). Returns (x, y, road_width)."""
    w, h = img.size
    y = h - (h - h * ROAD_TOP) * depth
    left = w * (ROAD_BOTTOM_X[0] + (ROAD_TOP_X[0] - ROAD_BOTTOM_X[0]) * depth)
    right = w * (ROAD_BOTTOM_X[1] + (ROAD_TOP_X[1] - ROAD_BOTTOM_X[1]) * depth)
    return (left + right) / 2 + lane * (right - left) / 2, y, right - left


def add_road(img):
    w, h = img.size
    draw = ImageDraw.Draw(img)
    road_top_y = int(h * ROAD_TOP)
    draw.polygon(
        [
            (w * ROAD_BOTTOM_X[0], h),
            (w * ROAD_BOTTOM_X[1], h),
            (w * ROAD_TOP_X[1], road_top_y),
            (w * ROAD_TOP_X[0], road_top_y),
        ],
        fill=(28, 30, 36),
    )
    dash_w = w * 0.01
    for i in range(4):
        t0 = i / 4
        t1 = (i + 0.5) / 4
        y0 = int(h - (h - road_top_y) * t0)
        y1 = int(h - (h - road_top_y) * t1)
        x0 = w * 0.50 - dash_w * (1 - t0) * 0.5
        x1 = w * 0.50 + dash_w * (1 - t0) * 0.5
        draw.rectangle([x0, y1, x1, y0], fill=(120, 110, 90))
    return img


def glow_composite(img, layer, radius):
    base = img.convert("RGBA")
    base = Image.alpha_composite(base, layer.filter(ImageFilter.GaussianBlur(radius=radius)))
    base = Image.alpha_composite(base, layer)
    return base.convert("RGB")


def add_light_trails(img):
    """Long-exposure streaks flanking the road, converging on the horizon:
    white/amber (oncoming) on the left, red (receding) on the right. They stay
    below the road's top edge, clear of the logo and the title block."""
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    horizon_y = h * ROAD_TOP
    trails = [
        # (bottom x, top x, color, alpha, width)
        (0.02, 0.405, HEADLIGHT_COLOR, 230, 0.010),
        (0.09, 0.415, SUBTITLE_COLOR, 210, 0.008),
        (0.16, 0.425, HEADLIGHT_COLOR, 180, 0.007),
        (0.98, 0.595, TAILLIGHT_COLOR, 240, 0.010),
        (0.91, 0.585, TAILLIGHT_COLOR, 215, 0.008),
        (0.84, 0.575, (255, 110, 60), 180, 0.007),
    ]
    for bx, tx, color, alpha, width in trails:
        # fade toward the horizon by drawing short segments with decreasing alpha
        steps = 24
        for i in range(steps):
            t0, t1 = i / steps, (i + 1) / steps
            p0 = (w * (bx + (tx - bx) * t0), h - (h - horizon_y) * t0)
            p1 = (w * (bx + (tx - bx) * t1), h - (h - horizon_y) * t1)
            a = int(alpha * (1 - t0 * 0.6))
            lw = max(1, int(h * width * (1 - t0 * 0.7)))
            draw.line([p0, p1], fill=(*color, a), width=lw)
    return glow_composite(img, layer, radius=h * 0.012)


def add_vehicles(img):
    """Trailers seen from behind in the right lane (dark body, amber marker
    lights on the top corners, red tail lights), headlights oncoming on the left.
    A box trailer is tall; a lowboy is flat with a block of machinery on it."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    body = (8, 8, 12, 240)
    trailers = [
        # (lane center, depth, kind), drawn far to near so nearer trailers cover farther ones
        (0.5, 0.78, "box"),
        (0.5, 0.45, "box"),
        (0.5, 0.10, "lowboy"),
    ]
    for lane, depth, kind in trailers:
        x, y, road_w = road_point(img, lane, depth)
        tw = road_w * 0.32
        r = max(2.0, road_w * 0.02)
        if kind == "box":
            th = tw * 1.05
            draw.rectangle([x - tw / 2, y - th, x + tw / 2, y], fill=body)
            for sx in (-1, 1):
                mx = x + sx * (tw / 2 - r)
                draw.ellipse([mx - r, y - th - r * 0.2, mx + r, y - th + r * 1.8], fill=(*MARKER_COLOR, 255))
        else:
            deck_h = tw * 0.14
            draw.rectangle([x - tw / 2, y - deck_h, x + tw / 2, y], fill=body)
            # machinery: cab block + boom
            draw.rectangle([x - tw * 0.30, y - deck_h - tw * 0.40, x + tw * 0.08, y - deck_h], fill=body)
            draw.polygon([(x + tw * 0.08, y - deck_h - tw * 0.30), (x + tw * 0.42, y - deck_h - tw * 0.62),
                          (x + tw * 0.46, y - deck_h - tw * 0.55), (x + tw * 0.12, y - deck_h - tw * 0.20)],
                         fill=body)
            for sx in (-1, 1):
                mx = x + sx * (tw / 2 - r)
                draw.ellipse([mx - r, y - deck_h - r, mx + r, y - deck_h + r], fill=(*MARKER_COLOR, 255))
        for sx in (-1, 1):
            cx = x + sx * (tw / 2 - r * 1.6)
            draw.ellipse([cx - r * 1.4, y - r * 1.6, cx + r * 1.4, y - r * 0.2], fill=(*TAILLIGHT_COLOR, 255))
    for depth in (0.36, 0.70):
        x, y, road_w = road_point(img, -0.5, depth)
        r = max(2.0, road_w * 0.022)
        for sx in (-1, 1):
            cx = x + sx * road_w * 0.08
            draw.ellipse([cx - r * 1.4, y - r * 0.8, cx + r * 1.4, y + r * 0.8], fill=(*HEADLIGHT_COLOR, 255))
    return glow_composite(img, layer, radius=img.height * 0.01)


def paste_logo(img):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    target_h = int(img.height * 0.62)
    ratio = target_h / logo.height
    target_w = int(logo.width * ratio)
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    pad = int(img.height * 0.06)
    pos = (pad, pad)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_logo = Image.new("RGBA", logo.size, (0, 0, 0, 255))
    shadow_logo.putalpha(logo.split()[3].point(lambda a: a * 160 // 255))
    shadow.paste(shadow_logo, (pos[0] + 6, pos[1] + 6), shadow_logo)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))

    base = img.convert("RGBA")
    base = Image.alpha_composite(base, shadow)
    base.paste(logo, pos, logo)
    return base.convert("RGB")


def fit_font(draw, text, font_path, max_width, start_size, min_size=10):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, min_size)


def draw_with_outline(draw, pos, text, font, fill, outline=(0, 0, 0), width=2):
    x, y = pos
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def add_text(img):
    draw = ImageDraw.Draw(img)
    w, h = img.size

    x_start = w * 0.40
    max_width = w * 0.97 - x_start

    title_lines = ["Trailers & Cargo", "MegaPack"]
    subtitle = "Jazzycat · Military · Railway"

    title_size = int(h * 0.135)
    for line in title_lines:
        f = fit_font(draw, line, FONT_BOLD, max_width, title_size)
        title_size = min(title_size, f.size)
    title_font = ImageFont.truetype(FONT_BOLD, title_size)

    subtitle_font = fit_font(draw, subtitle, FONT_REG, max_width, int(h * 0.06))

    line_bbox = draw.textbbox((0, 0), "Ag", font=title_font)
    line_h = (line_bbox[3] - line_bbox[1]) * 1.15

    total_h = line_h * len(title_lines) + line_h * 0.9
    y = h * 0.50 - total_h / 2

    for line in title_lines:
        draw_with_outline(draw, (x_start, y), line, title_font, TITLE_COLOR, width=3)
        y += line_h

    y += line_h * 0.15
    draw_with_outline(draw, (x_start, y), subtitle, subtitle_font, SUBTITLE_COLOR, width=2)
    return img


def add_version_badge(img, version):
    """Amber pill in the empty top-right corner, legible at 276x162."""
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    text = f"v{version}"
    font = ImageFont.truetype(FONT_BOLD, int(h * 0.06))
    bbox = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = h * 0.02, h * 0.015
    x1, y0 = w - h * 0.03, h * 0.03
    x0 = x1 - (bbox[2] - bbox[0]) - 2 * pad_x
    y1 = y0 + (bbox[3] - bbox[1]) + 2 * pad_y
    draw.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) / 2, fill=(*BADGE_COLOR, 235))
    draw.text((x0 + pad_x - bbox[0], y0 + pad_y - bbox[1]), text, font=font, fill=BADGE_TEXT_COLOR)
    return img


def main():
    version = read_version()
    img = make_background(CANVAS_SIZE)
    img = add_skyline(img)
    img = add_road(img)
    img = add_light_trails(img)
    img = add_vehicles(img)
    img = paste_logo(img)
    img = add_text(img)
    img = add_version_badge(img, version)
    img = img.resize(FINAL_SIZE, Image.LANCZOS)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, "JPEG", quality=92)
    print(f"Wrote {OUT_PATH} ({img.size[0]}x{img.size[1]}, v{version})")


if __name__ == "__main__":
    main()
