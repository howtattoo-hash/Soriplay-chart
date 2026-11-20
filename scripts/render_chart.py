#!/usr/bin/env python3
"""9:16 (1080x1920) 세로 바 차트 레이스 영상을 만든다.

- matplotlib으로 프레임을 그려 ffmpeg 파이프로 바로 인코딩한다(.mp4).
- 각 막대 왼쪽에 **원형 앨범 커버 썸네일**이 붙어 순위를 따라 함께 이동한다.
- 곡마다 다른 속도 곡선(chart_data.ease_vector)으로 자라므로 영상 안에서
  막대가 서로를 **추월했다가 다시 따라잡는** 장면이 계속 나온다.
- 순위가 바뀔 때: 스프링 이동(살짝 튀어 오름) · ▲/▼/NEW 배지 · 금색 번쩍임.
- 1위가 바뀌면 상단에 **NEW #1 왕관 배너**가 잠깐 뜨고 그 막대가 금색으로 빛난다.
- 스트림 숫자는 매 프레임 갱신되는 **롤링 카운터**다.
- 렌더링이 끝나면 output/<이름>.json 에 타임라인(1위 곡 구간 포함)을 남겨
  build_audio.py 가 배경 음악을 갈아끼울 수 있게 한다.

사용 예
  python scripts/render_chart.py --country kr --period weekly --out output/kr.mp4
  python scripts/render_chart.py --country kr --period weekly --frames-dir .preview --preview 0,675,1349
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

import numpy as np

import chart_config
import chart_data
import locales
import media

W, H = 1080, 1920

BG_TOP = (0x0A, 0x0A, 0x12)
BG_BOTTOM = (0x18, 0x12, 0x2E)
TEXT = "#FFFFFF"
SUB = "#F3F3FB"
DIM = "#C8C8DE"
FAINT = "#9A9AB6"
ACCENT = "#A855F7"
UP_COLOR = "#4ADE80"
DOWN_COLOR = "#F87171"
GOLD = (1.0, 0.80, 0.20, 1.0)
GOLD_HEX = "#F5B301"

BAR_H = 0.62          # 막대 두께(행 단위)
THUMB_PX = 86         # 썸네일 지름(픽셀)
THUMB_X = 0.185       # 썸네일 중심 x (figure 비율)
RANK_X = 0.106        # 순위 숫자 x
LABEL_PT = 16.0       # 곡 제목
SUBLABEL_PT = 12.0    # 아티스트
VALUE_PT = 15.5       # 스트림 숫자
RANK_PT = 25.0        # 순위 숫자
BADGE_PT = 12.5       # ▲▼/NEW 배지
TICK_PT = 21.0        # 날짜 티커
MIN_LABEL_PX = 230    # 짧은 막대에서도 제목이 보이도록 보장하는 최소 폭(픽셀)
WIDTH_SCALE = 1.04    # 굵은 글꼴은 폭이 조금 더 넓다(자르기 계산 보정)

FLASH_SEC = 0.85      # 추월 번쩍임 지속
CROWN_SEC = 2.6       # NEW #1 배너 노출
CROWN_GAP = 1.0       # 배너 최소 간격(1위가 요동칠 때 깜빡임 방지)
SPRING_K = 95.0       # 스프링 강성(클수록 빠르게 이동)
SPRING_D = 15.0       # 감쇠(작을수록 더 튐)
MAX_VEL = 60.0

BUNDLED_FONTS = ["SoriSans-Black.otf", "SoriSans-Bold.otf"]
HEAVY_FAMILY = "SoriSans Black"
BOLD_FAMILY = "SoriSans Bold"
FAMILIES: list[str] = []      # ensure_fonts() 가 채운다(맨 앞이 가장 굵은 글꼴)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansKR-Regular.otf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/pickle-hwp/NotoSansCJKkr-Regular.otf",
]
# 앞에서부터 우선. matplotlib 3.6+ 는 목록을 글자별 대체(fallback) 순서로 쓴다.
FONT_NAMES = ["Noto Sans CJK KR", "Noto Sans KR", "Noto Sans CJK JP",
              "Noto Sans", "Noto Sans Thai", "Noto Sans Arabic", "Noto Sans Devanagari",
              "NanumGothic", "Malgun Gothic", "Noto Sans CJK SC", "DejaVu Sans"]


def ensure_fonts() -> list[str]:
    """쓸 수 있는 글꼴을 대체 순서 목록으로 돌려준다(한글·태국·아랍·데바나가리 포함)."""
    from matplotlib import font_manager

    seen: set[str] = set()
    extra: list[str] = []
    # 저장소에 함께 넣은 굵은 글꼴(fonts/)을 가장 먼저 쓴다.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = [os.path.join(root, "fonts", name) for name in BUNDLED_FONTS]
    bundled += [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", name)
                for name in BUNDLED_FONTS]
    candidates = [os.path.normpath(p) for p in bundled] + list(FONT_CANDIDATES)
    for root in ("/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                low = f.lower()
                if low.endswith((".ttc", ".otf", ".ttf")) and (
                        "notosans" in low or "nanumgothic" in low
                        or "tlwg" in dirpath.lower() or "noto" in low):
                    candidates.append(os.path.join(dirpath, f))
    for path in candidates:
        if not (os.path.exists(path) and path not in seen):
            continue
        seen.add(path)
        try:
            font_manager.fontManager.addfont(path)
            name = font_manager.FontProperties(fname=path).get_name()
            if name and name not in extra:
                extra.append(name)
        except Exception:  # noqa: BLE001
            pass
    available = {f.name for f in font_manager.fontManager.ttflist}
    families = [name for name in (HEAVY_FAMILY, BOLD_FAMILY) if name in available]
    families += [name for name in FONT_NAMES if name in available]
    # 남은 글꼴(태국·아랍 등)은 뒤에 붙여 글자 단위 대체가 되게 한다.
    families += [name for name in extra if name not in families]
    return (families or ["DejaVu Sans"])[:8]


def fam(heavy: bool = True) -> list[str]:
    """굵기별 글꼴 가족 목록(뒤에 대체 글꼴을 붙여 글자 단위 대체가 되게)."""
    if not FAMILIES:
        return []
    if heavy and FAMILIES[0] == HEAVY_FAMILY:
        return FAMILIES
    if BOLD_FAMILY in FAMILIES:
        return [BOLD_FAMILY] + [f for f in FAMILIES if f != BOLD_FAMILY]
    return FAMILIES


_METRICS: dict[int, float] | None = None


def _load_metrics() -> dict[int, float]:
    """번들 글꼴의 글자별 진행 폭(em) 표. 없으면 빈 표."""
    global _METRICS
    if _METRICS is not None:
        return _METRICS
    table: dict[int, float] = {}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("SoriSans-Black.otf", "SoriSans-Bold.otf"):
        path = os.path.join(root, "fonts", name)
        if not os.path.exists(path):
            continue
        try:
            from fontTools.ttLib import TTFont
            ft = TTFont(path, lazy=True)
            upem = ft["head"].unitsPerEm
            cmap = ft.getBestCmap()
            hmtx = ft["hmtx"]
            for code, gname in cmap.items():
                if code in table:
                    continue
                try:
                    table[code] = hmtx[gname][0] / upem
                except KeyError:
                    pass
        except Exception:  # noqa: BLE001
            continue
    _METRICS = table
    return table


def find_ffmpeg() -> str:
    for cand in (os.environ.get("FFMPEG"), shutil.which("ffmpeg")):
        if cand and os.path.exists(cand):
            return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit("ffmpeg를 찾을 수 없습니다. (apt install ffmpeg 또는 pip install imageio-ffmpeg)")


def rgb_gradient(c1: tuple[int, int, int], c2: tuple[int, int, int], n: int) -> np.ndarray:
    t = np.linspace(0, 1, n)
    return np.column_stack([c1[i] + (c2[i] - c1[i]) * t for i in range(3)]) / 255.0


def bar_palette(n: int) -> list[tuple[float, float, float, float]]:
    cols = rgb_gradient((0x7C, 0x3A, 0xED), (0xF4, 0x3F, 0x5E), max(n, 2))
    return [(float(r), float(g), float(b), 0.96 - 0.045 * i)
            for i, (r, g, b) in enumerate(cols[:n])]


def blend(color, target, amount: float):
    amount = max(0.0, min(1.0, amount))
    return (color[0] + (target[0] - color[0]) * amount,
            color[1] + (target[1] - color[1]) * amount,
            color[2] + (target[2] - color[2]) * amount,
            color[3] if len(color) > 3 else 1.0)


def fmt(v: float) -> str:
    return f"{v:,.0f}"


def _fmt_date(iso: str, pattern: str) -> str:
    """'2026-11-12' → cfg의 date_fmt(예: 11/12 · 12/11)."""
    try:
        return dt.date.fromisoformat(str(iso)).strftime(pattern)
    except ValueError:
        return str(iso)


def text_px(s: str, fontsize_pt: float, dpi: float = 100.0) -> float:
    """렌더링 폭(픽셀). 번들 글꼴의 실제 글자 폭을 쓰고, 없으면 근사값."""
    em = fontsize_pt * dpi / 72.0
    table = _load_metrics()
    if table:
        total = 0.0
        for ch in s:
            a = table.get(ord(ch))
            if a is None:
                o = ord(ch)
                if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x2E80 <= o <= 0xA4CF:
                    a = 0.90
                elif ch == " ":
                    a = 0.25
                else:
                    a = 0.62
            total += a
        return total * em * WIDTH_SCALE
    width = 0.0
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x2E80 <= o <= 0xA4CF:
            width += em
        elif ch == " ":
            width += em * 0.30
        else:
            width += em * 0.55
    return width


def fit_text(s: str, avail_px: float, fontsize_pt: float) -> str:
    """막대 폭 안에 들어가도록 자르고 말줄임표를 붙인다."""
    if avail_px <= 0:
        return ""
    if text_px(s, fontsize_pt) <= avail_px:
        return s
    out = s
    while out and text_px(out + "…", fontsize_pt) > avail_px:
        out = out[:-1]
    return (out + "…") if out else ""


def _badges(tl, first_rank: dict, last_rank: dict) -> dict[str, tuple[str, str]]:
    """곡별 순위 변화 배지(문구, 색). 공식 P+ 가 있으면 그걸 우선한다."""
    out: dict[str, tuple[str, str]] = {}
    top_n = tl.top_n
    for key in tl.keys:
        lr = last_rank.get(key, 10 ** 6)
        if lr > top_n:
            continue
        off = (tl.official_change or {}).get(key, "")
        if off.upper().startswith("NEW"):
            out[key] = ("NEW", ACCENT)
            continue
        if off[:1] in {"+", "-"} and off[1:].isdigit():
            n = int(off)
            if n > 0:
                out[key] = (f"▲{n}", UP_COLOR)
            elif n < 0:
                out[key] = (f"▼{-n}", DOWN_COLOR)
            continue
        fr = first_rank.get(key, 10 ** 6)
        if fr > top_n:
            out[key] = ("NEW", ACCENT)
            continue
        d = fr - lr
        if d > 0:
            out[key] = (f"▲{d}", UP_COLOR)
        elif d < 0:
            out[key] = (f"▼{-d}", DOWN_COLOR)
    return out


def render(args) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import patheffects as pe
    from matplotlib.patches import FancyBboxPatch

    global FAMILIES
    FAMILIES = ensure_fonts()
    font = FAMILIES
    if font and font[0] != "DejaVu Sans":
        matplotlib.rcParams["font.family"] = font
        print(f"[render] 글꼴: {', '.join(font[:3])}")
    else:
        print("[render] 경고: 한글 폰트를 찾지 못했습니다. 글자가 깨질 수 있습니다.", file=sys.stderr)
    matplotlib.rcParams["axes.unicode_minus"] = False
    # 막대·배경 위에서도 글자가 또렷하게: 살짝 두꺼운 어두운 테두리(외곽선).
    OUTLINE_HEAVY = [pe.withStroke(linewidth=2.8, foreground=(0.02, 0.01, 0.05, 0.9))]
    OUTLINE_SOFT = [pe.withStroke(linewidth=2.2, foreground=(0.02, 0.01, 0.05, 0.75))]

    country = args.country
    period = getattr(args, "period", "weekly") or "weekly"
    cfg = chart_config.country(country)
    vloc = locales.get(cfg["video_lang"])
    pw, pw_cap = locales.period_words(cfg["video_lang"], period)
    vtext = {k: v.format(market=cfg["market"], pw=pw, pw_cap=pw_cap)
             for k, v in vloc["video"].items()}

    csv_path = chart_config.csv_path(args.data_dir, country, period)
    df = chart_data.load_history(csv_path, max_days=args.days)
    tl = chart_data.build_timeline(df, country, top_n=args.top, duration=args.duration,
                                   fps=args.fps, period=period)
    max_val = tl.max_value()
    n_rows = tl.top_n
    is_score = (getattr(tl, "metric", "streams") == "score")
    score_badge = locales.score_badge(cfg["video_lang"]) if is_score else ""
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    # ---- 커버 아트 준비 -----------------------------------------------------
    print(f"[render] 커버 조회 {len(tl.keys)}곡 ...")
    circ: dict[str, np.ndarray | None] = {}
    for key in tl.keys:
        artist, title = tl.labels[key]
        meta = media.lookup(artist, title, cache_dir=args.cache_dir, want_preview=False)
        path = meta.get("art_path")
        # figimage는 픽셀 1:1로 그리므로 영상에 들어갈 크기 그대로 만든다.
        circ[key] = media.circular_image(path, size=THUMB_PX)
        print(f"   {'OK ' if path else '-- '} {artist} - {title}"
              f"{'' if path else ' (기본 커버)'}")

    # ---- 캔버스 -------------------------------------------------------------
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor="#0A0A12")
    bg = fig.add_axes([0, 0, 1, 1], zorder=-10)
    grad = np.zeros((256, 1, 3))
    gt = np.linspace(0, 1, 256)
    for i in range(3):
        grad[:, 0, i] = (BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * gt) / 255.0
    bg.imshow(grad, aspect="auto", extent=(0, 1, 0, 1), origin="upper", zorder=-10)
    bg.axis("off")

    # 헤더 (차트 기간은 항상 7일 범위로 보여준다)
    fig.text(0.070, 0.962, "Sori Play", color=TEXT, fontsize=28, fontweight="bold",
             fontfamily=fam(True), va="center")
    fig.text(0.292, 0.962, f"· {vtext['chart']}", color=DIM, fontsize=16.5, fontweight="bold",
             fontfamily=fam(False), va="center")
    fig.text(0.070, 0.928, f"TOP {n_rows}  ·  {cfg['label']}", color=ACCENT,
             fontsize=16, fontweight="bold", fontfamily=fam(True), va="center")
    if is_score:
        fig.text(0.400, 0.928, f"·  {score_badge}", color="#FBBF24",
                 fontsize=14, fontweight="bold", fontfamily=fam(True), va="center")
    week_start, week_end = tl.dates[0], tl.dates[-1]
    fig.text(0.930, 0.928,
             f"{week_start.strftime(cfg['date_fmt'])} – {week_end.strftime(cfg['date_fmt'])}",
             color=DIM, fontsize=15.5, fontweight="bold", fontfamily=fam(False),
             va="center", ha="right")

    # 날짜 티커: 차트가 다음 날로 넘어갈 때마다 크게 튄다.
    tick_halo = FancyBboxPatch((0.335, 0.868), 0.330, 0.050,
                               boxstyle="round,pad=0.004,rounding_size=0.024",
                               transform=fig.transFigure, facecolor=GOLD_HEX,
                               edgecolor="none", alpha=0.0, zorder=11)
    fig.patches.append(tick_halo)
    tick_bg = FancyBboxPatch((0.345, 0.874), 0.310, 0.038,
                             boxstyle="round,pad=0.004,rounding_size=0.019",
                             transform=fig.transFigure, facecolor="#241B3A",
                             edgecolor="#4C3A7A", linewidth=1.2, alpha=1.0, zorder=12)
    fig.patches.append(tick_bg)
    tick_txt = fig.text(0.5, 0.893, "", color="#FFFFFF", fontsize=TICK_PT,
                        fontweight="bold", fontfamily=fam(True),
                        ha="center", va="center", zorder=13)

    # NEW #1 왕관 배너 (날짜 티커와 같은 줄 · 왕관이 뜨는 동안 티커는 잠시 숨김)
    crown_bg = FancyBboxPatch((0.058, 0.874), 0.884, 0.038,
                              boxstyle="round,pad=0.004,rounding_size=0.019",
                              transform=fig.transFigure, facecolor=GOLD_HEX,
                              edgecolor="none", alpha=0.0, zorder=30)
    fig.patches.append(crown_bg)
    crown_txt = fig.text(0.5, 0.893, "", color="#1A1207", fontsize=17,
                         fontweight="bold", fontfamily=fam(True),
                         ha="center", va="center", alpha=0.0, zorder=31)

    # 차트 영역 (왼쪽 거터: 순위 + 원형 커버)
    ax = fig.add_axes([0.245, 0.150, 0.700, 0.700])
    ax.set_xlim(0, max_val * 1.03)
    ax.set_ylim(-0.7, n_rows - 1 + 0.7)
    ax.axis("off")
    for frac in (0.25, 0.5, 0.75, 1.0):
        ax.axvline(max_val * frac, color="#FFFFFF", alpha=0.05, lw=1, zorder=0)

    pal = bar_palette(n_rows)
    px_per_row = (0.700 * H) / (n_rows + 0.4)
    bar_lw = BAR_H * px_per_row * 72.0 / fig.dpi   # 포인트 단위 막대 두께
    bar_px_full = 0.700 * W                        # x축 1.03*max_val 이 차지하는 픽셀

    def val_to_px(v: float) -> float:
        return v / (max_val * 1.03) * bar_px_full

    bars, glows, titles, subs, values, thumbs, ranks, badges = {}, {}, {}, {}, {}, {}, {}, {}
    y_cur: dict[str, float] = {}
    y_vel: dict[str, float] = {}
    alpha_cur: dict[str, float] = {}

    first_rank = tl.rank_map(0)
    last_rank = tl.rank_map(tl.frames - 1)
    badge_spec = _badges(tl, first_rank, last_rank)

    for i, key in enumerate(tl.keys):
        r0 = first_rank.get(key, n_rows + 6)
        y0 = max(-1.2, n_rows - r0)          # 화면 밖에서 멀리 시작하지 않게
        base = pal[min(i, n_rows - 1)]
        glow, = ax.plot([0, 0], [y0, y0], lw=bar_lw * 1.45, color=GOLD,
                        solid_capstyle="round", zorder=2, alpha=0)
        glows[key] = glow
        line, = ax.plot([0, 0], [y0, y0], lw=bar_lw, color=base,
                        solid_capstyle="round", zorder=3, alpha=0)
        bars[key] = line
        titles[key] = ax.text(max_val * 0.012, y0 + 0.075, "", color=TEXT,
                              fontsize=LABEL_PT, fontweight="bold", fontfamily=fam(True),
                              va="center", ha="left", zorder=4, alpha=0,
                              path_effects=OUTLINE_HEAVY)
        subs[key] = ax.text(max_val * 0.012, y0 - 0.130, "", color=SUB,
                            fontsize=SUBLABEL_PT, fontweight="bold", fontfamily=fam(False),
                            va="center", ha="left", zorder=4, alpha=0,
                            path_effects=OUTLINE_SOFT)
        values[key] = ax.text(0, y0, "", color="#FFFFFF", fontsize=VALUE_PT,
                              va="center", ha="left", zorder=4, alpha=0,
                              fontweight="bold", fontfamily=fam(True),
                              path_effects=OUTLINE_HEAVY)
        ranks[key] = fig.text(RANK_X, 0.5, "", color="#DEDEF2", fontsize=RANK_PT,
                              fontweight="bold", fontfamily=fam(True),
                              ha="center", va="center", alpha=0)
        btxt, bcol = badge_spec.get(key, ("", UP_COLOR))
        badges[key] = fig.text(RANK_X, 0.5, btxt, color=bcol, fontsize=BADGE_PT,
                               fontweight="bold", fontfamily=fam(True),
                               ha="center", va="center", alpha=0,
                               path_effects=OUTLINE_SOFT)
        art = circ.get(key)
        thumbs[key] = (fig.figimage(art, 0, 0, zorder=20, origin="upper")
                       if art is not None else None)
        y_cur[key] = y0
        y_vel[key] = 0.0
        alpha_cur[key] = 1.0 if key in first_rank and first_rank[key] <= n_rows else 0.0

    # 진행 바 + 날짜
    pax = fig.add_axes([0.070, 0.108, 0.860, 0.012])
    pax.set_xlim(0, 1)
    pax.set_ylim(-1, 1)
    pax.axis("off")
    pax.plot([0, 1], [0, 0], color="#2A2A3E", lw=3.5, solid_capstyle="round", zorder=1)
    prog_fill, = pax.plot([0, 0], [0, 0], color=ACCENT, lw=3.5,
                          solid_capstyle="round", zorder=2)
    prog_dot, = pax.plot([0], [0], marker="o", ms=7, color="#FFFFFF", zorder=3)
    fig.text(0.070, 0.088, tl.dates[0].strftime(cfg["date_fmt"]), color=FAINT,
             fontsize=12, fontweight="bold", fontfamily=fam(False))
    fig.text(0.930, 0.088, tl.dates[-1].strftime(cfg["date_fmt"]), color=FAINT,
             fontsize=12, fontweight="bold", fontfamily=fam(False), ha="right")
    cur_date_txt = fig.text(0.5, 0.088, "", color=DIM, fontsize=12, fontweight="bold",
                            fontfamily=fam(False), ha="center")

    # 하단 CTA
    cta = FancyBboxPatch((0.255, 0.034), 0.49, 0.042,
                         boxstyle="round,pad=0.004,rounding_size=0.021",
                         transform=fig.transFigure, facecolor=ACCENT, edgecolor="none",
                         alpha=0.95, zorder=5)
    fig.patches.append(cta)
    fig.text(0.5, 0.0552, vtext["cta"], color="#FFFFFF",
             fontsize=17.5, fontweight="bold", fontfamily=fam(True),
             ha="center", va="center", zorder=6)
    fig.text(0.5, 0.017, vtext["footer"] + (f" · {score_badge}" if is_score else ""),
             color=FAINT, fontsize=11, fontweight="bold", fontfamily=fam(False), ha="center")

    # ---- 인코더 -------------------------------------------------------------
    ffmpeg = find_ffmpeg()
    writing_pngs = bool(args.frames_dir)
    proc = None
    if writing_pngs:
        os.makedirs(args.frames_dir, exist_ok=True)
    else:
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(tl.fps), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    preview_at: set[int] = set()
    if args.preview:
        for tok in str(args.preview).split(","):
            tok = tok.strip()
            if tok:
                preview_at.add(int(tok) % tl.frames)

    dt_frame = 1.0 / tl.fps
    prev_rank: dict[str, int] = {}
    flash_until: dict[str, float] = {}
    crown_until = -99.0
    last_crown = -99.0
    prev_top1 = None
    tick_day = -1
    tick_pulse_until = -99.0
    base_color = {k: pal[min(i, n_rows - 1)] for i, k in enumerate(tl.keys)}

    # 프레임을 나눠 렌더할 때(--from-frame/--to-frame): 앞 구간은 상태만 진행하고 그리지 않는다.
    render_from = max(0, int(getattr(args, "from_frame", 0) or 0))
    render_to = int(getattr(args, "to_frame", 0) or 0) or tl.frames
    render_to = min(render_to, tl.frames)

    # ---- 프레임 루프 --------------------------------------------------------
    for i in range(render_to):
        t = i * dt_frame
        vals = tl.values_at(i)
        vmap = {k: float(vals[j]) for j, k in enumerate(tl.keys)}
        order = tl.order_at(i)
        rank_of = {k: r + 1 for r, k in enumerate(order)}
        top1 = order[0]

        # 1위 교체 → 왕관 배너
        if prev_top1 is not None and top1 != prev_top1 and (t - last_crown) >= CROWN_GAP:
            crown_until = t + CROWN_SEC
            last_crown = t
            artist, title = tl.labels[top1]
            crown_txt.set_text(fit_text(f"★ NEW #1  {artist} — {title}", 900, 17))
        prev_top1 = top1

        # 추월 감지 → 번쩍임
        for key, r in rank_of.items():
            before = prev_rank.get(key)
            if before is not None and r < before:
                flash_until[key] = t + FLASH_SEC
        prev_rank = dict(rank_of)

        crown_p = 0.0
        if t < crown_until:
            left = crown_until - t
            crown_p = min(1.0, left / 0.25, (CROWN_SEC - left) / 0.2 + 0.2)
            crown_p = max(0.0, min(1.0, crown_p))
        crown_bg.set_alpha(1.0 * crown_p)
        crown_txt.set_alpha(crown_p)
        # 왕관 배너가 뜨는 동안은 날짜 티커를 잠시 가린다.
        tick_bg.set_alpha(1.0 - crown_p)
        tick_txt.set_alpha(1.0 - crown_p)
        tick_halo.set_alpha(tick_halo.get_alpha() * (1.0 - crown_p))

        # 스프링으로 y 이동(살짝 튀어 오르는 느낌)
        for key in tl.keys:
            r = rank_of.get(key)
            target = (n_rows - r) if r else -1.2
            acc = (target - y_cur[key]) * SPRING_K - y_vel[key] * SPRING_D
            y_vel[key] = max(-MAX_VEL, min(MAX_VEL, y_vel[key] + acc * dt_frame))
            y_cur[key] = y_cur[key] + y_vel[key] * dt_frame
            if abs(target - y_cur[key]) < 0.0015 and abs(y_vel[key]) < 0.02:
                y_cur[key], y_vel[key] = target, 0.0

        for key in tl.keys:
            y = y_cur[key]
            v = vmap[key]
            artist, title = tl.labels[key]
            is_vis = key in rank_of and v > 0

            # 페이드 (등장/퇴장이 툭 끊기지 않게)
            target_a = 1.0 if is_vis else 0.0
            step = dt_frame / 0.22
            alpha_cur[key] += max(-step, min(step, target_a - alpha_cur[key]))
            a = alpha_cur[key]

            flash = max(0.0, min(1.0, (flash_until.get(key, -99.0) - t) / FLASH_SEC))
            if t > crown_until - CROWN_SEC + 0.35 and top1 == key:
                flash = max(flash, crown_p)
            # 막대 자체는 색을 유지하고(글자가 읽히게) 뒤에 금색 빛무리를 띄운다.
            color = blend(base_color[key], GOLD, 0.20 * flash)

            bars[key].set_data([0, max(v, 0.0)], [y, y])
            bars[key].set_color(color)
            bars[key].set_linewidth(bar_lw * (1.0 + 0.22 * flash))
            bars[key].set_alpha(a)
            glows[key].set_data([0, max(v, 0.0)], [y, y])
            glows[key].set_alpha(0.55 * flash * a)

            bar_px = val_to_px(v)
            px_to_val = (max_val * 1.03) / bar_px_full
            num_px = text_px(fmt(v), VALUE_PT) if v > 0 else 0.0
            inset_px = text_px("  ", LABEL_PT)
            # 짧은 막대에서도 제목이 잘리지 않게 막대 밖으로 조금 넘어가도록 최소 폭을 준다.
            out_avail = max(bar_px - inset_px - 16, MIN_LABEL_PX)
            title_out = fit_text(title, out_avail, LABEL_PT)
            title_end = max_val * 0.010 + text_px(title_out, LABEL_PT) * px_to_val
            # 막대 끝은 둥근 캡 때문에 데이터 위치보다 반 두께만큼 더 나간다.
            half_cap = bar_lw * fig.dpi / 72.0 / 2.0 * px_to_val
            val_left = max(v + half_cap, title_end) + max_val * 0.050
            inside = (v > max_val * 0.78) or (val_left + num_px * px_to_val > max_val * 1.01)
            # 막대 안에 숫자를 넣는 경우엔 그만큼 글자 자리를 빼서 겹치지 않게 한다.
            avail = (bar_px - inset_px - 16 - (num_px + 46)) if inside else out_avail
            titles[key].set_position((max_val * 0.010, y + 0.075))
            titles[key].set_text(fit_text(title, avail, LABEL_PT))
            titles[key].set_alpha(a)
            subs[key].set_position((max_val * 0.010, y - 0.130))
            subs[key].set_text(fit_text(artist, avail, SUBLABEL_PT))
            subs[key].set_alpha(a)
            # 글자 색은 항상 밝게 유지(금색 빛무리 위에서도 읽히게)
            titles[key].set_color(TEXT)
            subs[key].set_color(SUB)

            val_x = (v - max_val * 0.045) if inside else val_left
            values[key].set_position((val_x, y))
            values[key].set_horizontalalignment("right" if inside else "left")
            values[key].set_text(fmt(v) if (v > 0 and a > 0.4) else "")
            values[key].set_alpha(a)
            values[key].set_color("#FFE9A8" if (flash > 0.12 and not inside) else "#FFFFFF")

            _x, y_px = ax.transData.transform((0, y))
            fi = thumbs.get(key)
            if fi is not None:
                if is_vis:
                    fi.ox = int(THUMB_X * W - THUMB_PX / 2)
                    fi.oy = int(y_px - THUMB_PX / 2)
                    fi.set_visible(True)
                else:
                    fi.set_visible(False)

            rk = ranks[key]
            rk.set_text(str(rank_of[key]) if key in rank_of else "")
            rk.set_alpha(a)
            rk.set_position((RANK_X, y_px / H))
            bd = badges[key]
            bd.set_alpha(a * (0.95 if bd.get_text() else 0.0))
            bd.set_position((RANK_X, y_px / H - 0.0235))

        u = tl.progress(i)
        prog_fill.set_data([0, u], [0, 0])
        prog_dot.set_data([u], [0])
        day_idx = tl.day_index(i)
        cur_date_txt.set_text(_fmt_date(tl.date_label(i), cfg["date_fmt"]))

        # 날짜 티커: 날이 바뀌면 큰 글씨가 튀면서 금색으로 번쩍인다.
        if day_idx != tick_day:
            if tick_day >= 0:
                tick_pulse_until = t + 0.75
            tick_day = day_idx
            tick_txt.set_text(_fmt_date(tl.dates[day_idx].isoformat(), cfg['date_fmt']))
        pulse_p = max(0.0, min(1.0, (tick_pulse_until - t) / 0.75))
        tick_halo.set_alpha(0.55 * pulse_p)
        tick_bg.set_edgecolor(blend((0.298, 0.227, 0.478, 1.0), (1.0, 0.85, 0.40, 1.0), pulse_p))
        tick_bg.set_linewidth(1.2 + 2.0 * pulse_p)
        tick_txt.set_fontsize(TICK_PT + 4.0 * pulse_p)
        tick_txt.set_color(blend((1.0, 1.0, 1.0, 1.0), (1.0, 0.92, 0.62, 1.0), pulse_p))

        if i < render_from:
            continue

        fig.canvas.draw()
        if writing_pngs:
            if not preview_at or i in preview_at:
                fig.savefig(os.path.join(args.frames_dir, f"frame_{i:05d}.png"),
                            facecolor=fig.get_facecolor())
        else:
            buf = np.asarray(fig.canvas.buffer_rgba())
            proc.stdin.write(buf[:, :, :3].tobytes())
        if i % 90 == 0:
            print(f"[render] {i}/{tl.frames} 프레임", flush=True)

    if proc:
        proc.stdin.close()
        rc = proc.wait()
        if rc != 0:
            raise SystemExit(f"ffmpeg 인코딩 실패 (exit {rc})")
        print(f"[render] 영상 저장: {args.out} "
              f"({os.path.getsize(args.out) / 1e6:.1f}MB)")
    plt.close(fig)

    # ---- 후속 단계용 타임라인 ----------------------------------------------
    info = tl.to_dict()
    info.update({"video": args.out, "max_value": max_val, "period": period,
                 "country_label": cfg["label"],
                 "top1": tl.order_at(tl.frames - 1, 1)[0]})
    meta_path = os.path.splitext(args.out)[0] + ".json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    print(f"[render] 타임라인 저장: {meta_path} (1위 구간 {len(info['segments'])}개)")
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="9:16 바 차트 레이스 렌더러")
    ap.add_argument("--country", default="kr", help="시장 코드(예: kr, global, br …)")
    ap.add_argument("--period", default="weekly", choices=["weekly", "daily"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out", default="output/short.mp4")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--duration", type=float, default=45.0,
                    help="영상 길이(초) · 기본 45초(쇼츠 60초 제한 안)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--days", type=int, default=4, help="애니메이션에 쓸 최근 시점 수(주간이면 주)")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--frames-dir", default="", help="PNG로 저장(인코딩 생략)")
    ap.add_argument("--preview", default="", help="PNG 저장 시 뽑을 프레임 번호(쉼표)")
    ap.add_argument("--from-frame", type=int, default=0,
                    help="이 프레임부터 그린다(앞 구간은 상태만 진행 · 구간 렌더용)")
    ap.add_argument("--to-frame", type=int, default=0,
                    help="이 프레임에서 멈춘다(0이면 끝까지 · 구간 렌더용)")
    args = ap.parse_args()
    render(args)


if __name__ == "__main__":
    main()
