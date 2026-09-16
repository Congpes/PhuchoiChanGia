from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(r"D:\Phuchochucnang\PhuchoiChanGia\work\mau-bieu-do-fsr-dung.png")
W, H = 2400, 1600

BG = "#FFFFFF"
TEXT = "#172033"
MUTED = "#5E6B7A"
GRID = "#D9E1EA"
FRAME = "#A9B6C5"
REF = "#8B97A5"
BLUE = "#2563EB"
TEAL = "#0F9D8A"
ORANGE = "#E76F1E"

FONT_REG = r"C:\Windows\Fonts\arial.ttf"
FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size=size)


F_TITLE = font(43, True)
F_SUBTITLE = font(24)
F_PANEL = font(29, True)
F_AXIS = font(21)
F_TICK = font(18)
F_LEGEND = font(20)
F_NOTE = font(18)
F_ANNOT = font(18, True)


def gaussian(x: float, center: float, width: float) -> float:
    return math.exp(-0.5 * ((x - center) / width) ** 2)


def contact_envelope(x: float) -> float:
    """Smoothly enter and leave the stance phase."""
    if x <= 0 or x >= 100:
        return 0.0
    if x < 12:
        t = x / 12.0
        return 3 * t * t - 2 * t * t * t
    if x <= 82:
        return 1.0
    return max(0.0, math.cos((x - 82.0) / 18.0 * math.pi / 2.0)) ** 1.4


def force_components(x: float, side: str) -> tuple[float, float, float]:
    """Heel, midfoot and forefoot. Their sum is the total force at every x."""
    scale = 0.975 if side == "left" else 1.0
    shifted = x + (0.7 if side == "left" else 0.0)
    total = scale * contact_envelope(x) * (
        490.0
        + 125.0 * gaussian(shifted, 18.0, 11.0)
        + 130.0 * gaussian(shifted, 80.0, 11.0)
    )

    heel_weight = 0.08 + 1.80 * gaussian(shifted, 14.0, 22.0)
    mid_weight = 0.10 + 1.00 * gaussian(shifted, 50.0, 22.0)
    fore_weight = 0.08 + 2.30 * gaussian(shifted, 82.0, 15.0)
    weight_sum = heel_weight + mid_weight + fore_weight
    return (
        total * heel_weight / weight_sum,
        total * mid_weight / weight_sum,
        total * fore_weight / weight_sum,
    )


XS = [i / 2 for i in range(201)]
LEFT = [force_components(x, "left") for x in XS]
RIGHT = [force_components(x, "right") for x in XS]
LEFT_TOTAL = [sum(v) for v in LEFT]
RIGHT_TOTAL = [sum(v) for v in RIGHT]


def sd_value(x: float, series_index: int, side: str) -> float:
    """A smooth 1--5 N reference band, tapered to zero at contact limits."""
    offset = (series_index + 1) * 1.7 + (0.9 if side == "left" else 0.0)
    wave = 0.5 + 0.5 * math.sin(x / 8.5 + offset)
    return (1.0 + 4.0 * wave) * math.sqrt(contact_envelope(x))


def text_center(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, fnt, fill=TEXT):
    box = draw.textbbox((0, 0), value, font=fnt)
    draw.text((xy[0] - (box[2] - box[0]) / 2, xy[1] - (box[3] - box[1]) / 2), value, font=fnt, fill=fill)


def text_right(draw: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, fnt, fill=TEXT):
    box = draw.textbbox((0, 0), value, font=fnt)
    draw.text((xy[0] - (box[2] - box[0]), xy[1]), value, font=fnt, fill=fill)


def dashed_line(draw: ImageDraw.ImageDraw, points, fill, width=4, dash=18, gap=12):
    remaining = dash
    drawing = True
    for a, b in zip(points[:-1], points[1:]):
        x1, y1 = a
        x2, y2 = b
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        used = 0.0
        while used < length:
            take = min(remaining, length - used)
            p1 = (x1 + dx * used / length, y1 + dy * used / length)
            p2 = (x1 + dx * (used + take) / length, y1 + dy * (used + take) / length)
            if drawing:
                draw.line([p1, p2], fill=fill, width=width)
            used += take
            remaining -= take
            if remaining <= 1e-9:
                drawing = not drawing
                remaining = dash if drawing else gap


def y_axis_label(base: Image.Image, text: str, center: tuple[int, int]):
    box = Image.new("RGBA", (260, 44), (255, 255, 255, 0))
    d = ImageDraw.Draw(box)
    text_center(d, (130, 22), text, F_AXIS, TEXT)
    rotated = box.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    base.alpha_composite(rotated, (int(center[0] - rotated.width / 2), int(center[1] - rotated.height / 2)))


def map_point(x: float, y: float, rect, ymax: float):
    x0, y0, x1, y1 = rect
    return (x0 + (x / 100.0) * (x1 - x0), y1 - (y / ymax) * (y1 - y0))


def draw_axes(base: Image.Image, rect, ymax: float, yticks: list[int], x_label: str):
    draw = ImageDraw.Draw(base)
    x0, y0, x1, y1 = rect
    for tick in [0, 20, 40, 60, 80, 100]:
        px, _ = map_point(tick, 0, rect, ymax)
        draw.line((px, y0, px, y1), fill=GRID, width=2)
        text_center(draw, (px, y1 + 27), str(tick), F_TICK, MUTED)
    for tick in yticks:
        _, py = map_point(0, tick, rect, ymax)
        draw.line((x0, py, x1, py), fill=GRID, width=2)
        text_right(draw, (x0 - 16, py - 10), str(tick), F_TICK, MUTED)
    draw.rectangle(rect, outline=FRAME, width=2)
    text_center(draw, ((x0 + x1) / 2, y1 + 67), x_label, F_AXIS, TEXT)
    y_axis_label(base, "Lực (N)", (x0 - 92, (y0 + y1) // 2))


def legend_item(draw, x, y, label, color, dashed=False, band=False):
    if band:
        draw.rounded_rectangle((x, y + 3, x + 42, y + 19), radius=3, fill=(37, 99, 235, 48), outline=color, width=1)
    elif dashed:
        dashed_line(draw, [(x, y + 11), (x + 46, y + 11)], color, width=4, dash=11, gap=7)
    else:
        draw.line((x, y + 11, x + 46, y + 11), fill=color, width=5)
    draw.text((x + 57, y), label, font=F_LEGEND, fill=TEXT)
    width = draw.textbbox((0, 0), label, font=F_LEGEND)[2]
    return x + 57 + width + 35


def draw_total_chart(base: Image.Image):
    draw = ImageDraw.Draw(base)
    rect = (155, 250, 2290, 695)
    ymax = 650.0
    text_center(draw, (W / 2, 180), "Tổng lực từng chân", F_PANEL)

    lx = 790
    lx = legend_item(draw, lx, 205, "Chân trái", BLUE)
    legend_item(draw, lx, 205, "Chân phải", ORANGE, dashed=True)

    draw_axes(base, rect, ymax, [0, 100, 200, 300, 400, 500, 600, 650], "Pha chống đỡ (%)")

    # Reference for quiet standing: body weight / two feet for a 60 kg person.
    standing = 60.0 * 9.81 / 2.0
    _, py = map_point(0, standing, rect, ymax)
    dashed_line(draw, [(rect[0], py), (rect[2], py)], REF, width=2, dash=9, gap=8)
    label = "Đứng đều hai chân: ≈294 N/chân"
    tw = draw.textbbox((0, 0), label, font=F_NOTE)[2]
    draw.rectangle((rect[2] - tw - 24, py - 30, rect[2] - 8, py - 5), fill=BG)
    draw.text((rect[2] - tw - 16, py - 29), label, font=F_NOTE, fill=MUTED)

    left_points = [map_point(x, y, rect, ymax) for x, y in zip(XS, LEFT_TOTAL)]
    right_points = [map_point(x, y, rect, ymax) for x, y in zip(XS, RIGHT_TOTAL)]
    draw.line(left_points, fill=BLUE, width=6, joint="curve")
    dashed_line(draw, right_points, ORANGE, width=6, dash=20, gap=12)

    # Three recognizable gait-force phases.
    phases = [(18, "Tiếp nhận tải"), (50, "Giữa thì trụ"), (80, "Đẩy chân")]
    for x, label in phases:
        px, _ = map_point(x, 0, rect, ymax)
        draw.line((px, rect[1], px, rect[3]), fill="#AAB5C2", width=2)
        text_center(draw, (px, rect[1] - 22), label, F_ANNOT, MUTED)

    peak_left = max(LEFT_TOTAL)
    peak_right = max(RIGHT_TOTAL)
    peak_text = f"Hai đỉnh khoảng {peak_left:.0f}–{peak_right:.0f} N"
    text_center(draw, (W / 2, rect[1] + 34), peak_text, F_ANNOT, TEXT)


def draw_regional_chart(base: Image.Image, rect, side: str, title: str):
    draw = ImageDraw.Draw(base)
    ymax = 550.0
    values = LEFT if side == "left" else RIGHT
    x0, y0, x1, _ = rect
    text_center(draw, ((x0 + x1) / 2, y0 - 112), title, F_PANEL)

    lx = x0 + 205
    for label, color in [("Gót", BLUE), ("Giữa", TEAL), ("Trước", ORANGE)]:
        lx = legend_item(draw, lx, y0 - 76, label, color)
    legend_item(draw, lx, y0 - 76, "±SD", BLUE, band=True)

    draw_axes(base, rect, ymax, [0, 100, 200, 300, 400, 500, 550], "Pha chống đỡ (%)")

    # SD envelopes first, then the mean curves on top.
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    odraw = ImageDraw.Draw(overlay)
    colors_rgba = [(37, 99, 235, 62), (15, 157, 138, 58), (231, 111, 30, 58)]
    for j in range(3):
        upper = []
        lower = []
        for x, triple in zip(XS, values):
            sd = sd_value(x, j, side)
            upper.append(map_point(x, min(ymax, triple[j] + sd), rect, ymax))
            lower.append(map_point(x, max(0.0, triple[j] - sd), rect, ymax))
        odraw.polygon(upper + list(reversed(lower)), fill=colors_rgba[j])
    base.alpha_composite(overlay)
    draw = ImageDraw.Draw(base)

    for j, color in enumerate((BLUE, TEAL, ORANGE)):
        pts = [map_point(x, triple[j], rect, ymax) for x, triple in zip(XS, values)]
        draw.line(pts, fill=color, width=6, joint="curve")

    for x, label in [(15, "Gót"), (50, "Giữa"), (82, "Trước")]:
        px, _ = map_point(x, 0, rect, ymax)
        draw.line((px, rect[1], px, rect[3]), fill="#BEC8D3", width=2)
        text_center(draw, (px, rect[1] + 24), label, F_ANNOT, MUTED)


def main():
    image = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(image)
    text_center(draw, (W / 2, 54), "MẪU THAM CHIẾU LỰC FSR TRONG PHA CHỐNG ĐỠ", F_TITLE)
    text_center(
        draw,
        (W / 2, 105),
        "Người 60 kg · hai chân lành · lực vùng gót, giữa và trước cộng đúng bằng tổng lực",
        F_SUBTITLE,
        MUTED,
    )

    draw_total_chart(image)
    draw_regional_chart(image, (155, 915, 1148, 1395), "left", "Phân bố lực — chân trái")
    draw_regional_chart(image, (1407, 915, 2290, 1395), "right", "Phân bố lực — chân phải")

    footer = "Dải ±SD hiển thị rõ ở ba vùng. Đây là đường cong tham chiếu hình dạng; số liệu báo cáo phải thay bằng dữ liệu đo thực tế."
    text_center(draw, (W / 2, 1547), footer, F_NOTE, MUTED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=96, dpi=(180, 180))
    print(OUT)


if __name__ == "__main__":
    main()
