#!/usr/bin/env python3
"""產生 PWA / 加到主畫面用的 App 圖示（純 PIL，無外部字型依賴）。

風格對齊籌碼儀表板：深藍底 + 三大法人配色的上升長條（外資藍 / 投信橘 / 自營綠）
+ 一條收盤價折線。輸出 512 / 192 / 180(apple) 三個尺寸與 favicon。
"""
from PIL import Image, ImageDraw


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def vgrad(size, top, bot):
    base = Image.new("RGB", (1, size))
    px = base.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return base.resize((size, size))


def draw_icon(size):
    S = size
    img = vgrad(S, (0x1c, 0x3a, 0x6b), (0x0c, 0x10, 0x18))  # 深藍 → 近黑
    d = ImageDraw.Draw(img)

    # 三大法人上升長條
    cols = [(0x2f, 0x6d, 0xf0), (0xe8, 0x91, 0x2b), (0x1f, 0xaf, 0x7a)]  # 外資/投信/自營
    n = 3
    gap = S * 0.09
    left = S * 0.20
    bw = (S * 0.60 - gap * (n - 1)) / n
    heights = [0.30, 0.46, 0.64]  # 上升
    base_y = S * 0.74
    r = max(2, int(bw * 0.18))
    for i in range(n):
        x0 = left + i * (bw + gap)
        h = S * heights[i]
        d.rounded_rectangle([x0, base_y - h, x0 + bw, base_y], radius=r, fill=cols[i])

    # 收盤價折線（台股紅），略過長條頂端
    pts = [
        (S * 0.16, S * 0.52),
        (S * 0.35, S * 0.40),
        (S * 0.54, S * 0.46),
        (S * 0.73, S * 0.26),
        (S * 0.86, S * 0.32),
    ]
    d.line(pts, fill=(0xff, 0x4d, 0x45), width=max(3, int(S * 0.028)), joint="curve")
    rr = max(3, int(S * 0.022))
    for (x, y) in pts:
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(0xff, 0x6b, 0x63))

    # 圓角裁切
    mask = rounded_mask(S, int(S * 0.22))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


for sz, name in [(512, "icon-512.png"), (192, "icon-192.png"), (180, "icon-180.png")]:
    draw_icon(sz).save(name)
    print("wrote", name)

# favicon（多尺寸 .ico）
ico = draw_icon(64)
ico.save("favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print("wrote favicon.ico")
