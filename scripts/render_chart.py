#!/usr/bin/env python3
"""9:16 (1080x1920) 세로 바 차트 레이스 영상을 만든다.

- matplotlib으로 프레임을 그려 ffmpeg 파이프로 바로 인코딩한다(.mp4).
- 각 막대 왼쪽에 **원형 앨범 커버 썸네일**이 붙어 순위를 따라 함께 이동한다.
- 막대/숫자는 날짜 사이를 ease-in-out으로 보간해 부드럽게 자란다.
- 렌더링이 끝나면 output/<이름>.json 에 타임라인(1위 곡 구간 포함)을 남겨
  build_audio.py 가 배경 음악을 갈아끼울 수 있게 한다.

사용 예
  python scripts/render_chart.py --country kr --out output/kr.mp4
  python scripts/render_chart.py --country kr --frames-dir .preview --preview 0,120,269
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np

import chart_data
import media

W, H = 1080, 1920

BG_TOP = (0x0A, 0x0A, 0x12)
BG_BOTTOM = (0x18, 0x12, 0x2E)
TEXT = "#F6F6FB"
SUB = "#DCDCEA"
DIM = "#9C9CB4"
FAINT = "#5C5C74"
ACCENT = "#A855F7"

BAR_H = 0.62          # 막대 두께(행 단위)
THUMB_PX = 86         # 썸네일 지름(픽셀)
THUMB_X = 0.185       # 썸네일 중심 x (figure 비율)
RANK_X = 0.108        # 순위 숫자 x
LABEL_PT = 15.5
SUBLABEL_PT = 10.5
VALUE_PT = 12.0

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansKR-Regular.otf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/pickle-hwp/NotoSansCJKkr-Regular.otf",
]
FONT_NAMES = ["Noto Sans CJK KR", "Noto Sans KR", "Noto Sans CJK JP",
              "NanumGothic", "Malgun Gothic", "Noto Sans CJK SC"]


def ensure_font() -> str | None:
    """한글 폰트를 matplotlib에 등록하고 이름을 돌려준다."""
    from matplotlib import font_manager

    seen: set[str] = set()
    candidates = list(FONT_CANDIDATES)
    for root in ("/usr/share/fonts", "/usr/local/share/fonts"):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                low = f.lower()
                if low.endswith((".ttc", ".otf", ".ttf")) and (
                        "notosanscjk" in low or "notosanskr" in low or "nanumgothic" in low):
                    candidates.append(os.path.join(dirpath, f))
    for path in candidates:
        if os.path.exists(path) and path not in seen:
            seen.add(path)
            try:
                font_manager.fontManager.addfont(path)
            except Exception:  # noqa: BLE001
                pass
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in FONT_NAMES:
        if name in available:
            return name
    return None


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


def fmt(v: float) -> str:
    return f"{v:,.0f}"


def text_px(s: str, fontsize_pt: float, dpi: float = 100.0) -> float:
    """대략적인 렌더링 폭(픽셀). 한글은 1em, 라틴은 0.55em로 본다."""
    em = fontsize_pt * dpi / 72.0
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


def render(args) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    font = ensure_font()
    if font:
        matplotlib.rcParams["font.family"] = font
        print(f"[render] 한글 폰트: {font}")
    else:
        print("[render] 경고: 한글 폰트를 찾지 못했습니다. 글자가 깨질 수 있습니다.", file=sys.stderr)
    matplotlib.rcParams["axes.unicode_minus"] = False

    country = args.country
    csv_path = os.path.join(args.data_dir, f"{country}_daily.csv")
    df = chart_data.load_history(csv_path, max_days=args.days)
    tl = chart_data.build_timeline(df, country, top_n=args.top,
                                   duration=args.duration, fps=args.fps)
    max_val = tl.max_value()
    n_rows = tl.top_n
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

    # 헤더
    fig.text(0.070, 0.945, "Sori Play", color=TEXT, fontsize=27, fontweight="bold", va="center")
    fig.text(0.250, 0.945, "· 스포티파이 일간 차트", color=DIM, fontsize=16, va="center")
    label = "KOREA" if country == "kr" else "GLOBAL"
    fig.text(0.070, 0.906, f"TOP {n_rows}  ·  {label}", color=ACCENT,
             fontsize=14, fontweight="bold", va="center")
    last_date = tl.dates[-1]
    fig.text(0.930, 0.906, last_date.strftime("%Y.%m.%d"), color=DIM,
             fontsize=14, va="center", ha="right")

    # 차트 영역 (왼쪽 거터: 순위 + 원형 커버)
    ax = fig.add_axes([0.245, 0.150, 0.700, 0.720])
    ax.set_xlim(0, max_val * 1.16)
    ax.set_ylim(-0.7, n_rows - 1 + 0.7)
    ax.axis("off")
    for frac in (0.25, 0.5, 0.75, 1.0):
        ax.axvline(max_val * frac, color="#FFFFFF", alpha=0.05, lw=1, zorder=0)

    pal = bar_palette(n_rows)
    px_per_row = (0.720 * H) / (n_rows + 0.4)
    bar_lw = BAR_H * px_per_row * 72.0 / fig.dpi   # 포인트 단위 막대 두께
    bar_px_full = 0.700 * W                        # x축 1.16*max_val 이 차지하는 픽셀

    def val_to_px(v: float) -> float:
        return v / (max_val * 1.16) * bar_px_full

    bars, titles, subs, values, thumbs, ranks = {}, {}, {}, {}, {}, {}
    y_cur: dict[str, float] = {}

    for i, key in enumerate(tl.keys):
        y0 = n_rows - 1 - min(i, n_rows - 1)
        line, = ax.plot([0, 0], [y0, y0], lw=bar_lw, color=pal[min(i, n_rows - 1)],
                        solid_capstyle="round", zorder=3, alpha=0)
        bars[key] = line
        titles[key] = ax.text(max_val * 0.012, y0 + 0.085, "", color=TEXT,
                              fontsize=LABEL_PT, fontweight="bold", va="center",
                              ha="left", zorder=4, alpha=0)
        subs[key] = ax.text(max_val * 0.012, y0 - 0.115, "", color=SUB,
                            fontsize=SUBLABEL_PT, va="center", ha="left",
                            zorder=4, alpha=0)
        values[key] = ax.text(0, y0, "", color="#FFFFFF", fontsize=VALUE_PT,
                              va="center", ha="left", zorder=4, alpha=0,
                              fontweight="bold")
        ranks[key] = fig.text(RANK_X, 0.5, "", color="#7C7C96", fontsize=19,
                              fontweight="bold", ha="center", va="center", alpha=0)
        art = circ.get(key)
        thumbs[key] = (fig.figimage(art, 0, 0, zorder=20, origin="upper")
                       if art is not None else None)
        y_cur[key] = y0

    # 진행 바 + 날짜
    pax = fig.add_axes([0.070, 0.108, 0.860, 0.012])
    pax.set_xlim(0, 1)
    pax.set_ylim(-1, 1)
    pax.axis("off")
    pax.plot([0, 1], [0, 0], color="#2A2A3E", lw=3.5, solid_capstyle="round", zorder=1)
    prog_fill, = pax.plot([0, 0], [0, 0], color=ACCENT, lw=3.5,
                          solid_capstyle="round", zorder=2)
    prog_dot, = pax.plot([0], [0], marker="o", ms=7, color="#FFFFFF", zorder=3)
    fig.text(0.070, 0.088, tl.dates[0].strftime("%m/%d"), color=FAINT, fontsize=10.5)
    fig.text(0.930, 0.088, tl.dates[-1].strftime("%m/%d"), color=FAINT,
             fontsize=10.5, ha="right")
    cur_date_txt = fig.text(0.5, 0.088, "", color=DIM, fontsize=10.5, ha="center")

    # 하단 CTA
    cta = FancyBboxPatch((0.255, 0.034), 0.49, 0.042,
                         boxstyle="round,pad=0.004,rounding_size=0.021",
                         transform=fig.transFigure, facecolor=ACCENT, edgecolor="none",
                         alpha=0.95, zorder=5)
    fig.patches.append(cta)
    fig.text(0.5, 0.0552, "▶   지금 무료 감상 · Sori Play", color="#FFFFFF",
             fontsize=15, fontweight="bold", ha="center", va="center", zorder=6)
    fig.text(0.5, 0.017, "데이터 Spotify 일간 차트 · 매일 자동 업데이트", color=FAINT,
             fontsize=9.5, ha="center")

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

    # ---- 프레임 루프 --------------------------------------------------------
    for i in range(tl.frames):
        vals = tl.values_at(i)
        vmap = {k: float(vals[j]) for j, k in enumerate(tl.keys)}
        order = tl.order_at(i)
        visible = set(order)

        for rank, key in enumerate(order):
            target = n_rows - 1 - rank
            y_cur[key] += (target - y_cur[key]) * 0.34
            if abs(target - y_cur[key]) < 0.004:
                y_cur[key] = target

        for key in tl.keys:
            y = y_cur[key]
            v = vmap[key]
            is_vis = key in visible
            artist, title = tl.labels[key]
            bars[key].set_data([0, max(v, 0.0)], [y, y])
            bars[key].set_alpha(1.0 if is_vis else 0.0)

            bar_px = val_to_px(v)
            avail = bar_px - text_px("  ", LABEL_PT) - 8
            titles[key].set_position((max_val * 0.010, y + 0.085))
            titles[key].set_text(fit_text(title, avail, LABEL_PT))
            titles[key].set_alpha(1.0 if is_vis else 0.0)
            subs[key].set_position((max_val * 0.010, y - 0.120))
            subs[key].set_text(fit_text(artist, avail, SUBLABEL_PT))
            subs[key].set_alpha((1.0 if is_vis else 0.0) * 0.85)

            inside = v > max_val * 0.74
            val_x = (v - max_val * 0.030) if inside else (v + max_val * 0.095)
            values[key].set_position((val_x, y))
            values[key].set_horizontalalignment("right" if inside else "left")
            values[key].set_text(fmt(v) if v > 0 else "")
            values[key].set_alpha(1.0 if is_vis else 0.0)

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
            if is_vis:
                rk.set_text(str(order.index(key) + 1))
                rk.set_alpha(1.0)
            else:
                rk.set_alpha(0.0)
            rk.set_position((RANK_X, y_px / H))

        u = tl.progress(i)
        prog_fill.set_data([0, u], [0, 0])
        prog_dot.set_data([u], [0])
        cur_date_txt.set_text(tl.date_label(i))

        fig.canvas.draw()
        if writing_pngs:
            if not preview_at or i in preview_at:
                fig.savefig(os.path.join(args.frames_dir, f"frame_{i:05d}.png"),
                            facecolor=fig.get_facecolor())
        else:
            buf = np.asarray(fig.canvas.buffer_rgba())
            proc.stdin.write(buf[:, :, :3].tobytes())
        if i % 60 == 0:
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
    info.update({"video": args.out, "max_value": max_val,
                 "top1": tl.order_at(tl.frames - 1, 1)[0]})
    meta_path = os.path.splitext(args.out)[0] + ".json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    print(f"[render] 타임라인 저장: {meta_path} (1위 구간 {len(info['segments'])}개)")
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="9:16 바 차트 레이스 렌더러")
    ap.add_argument("--country", default="kr", choices=["kr", "global"])
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--out", default="output/short.mp4")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--duration", type=float, default=18.0, help="영상 길이(초)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--days", type=int, default=5, help="애니메이션에 쓸 최근 날짜 수")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--frames-dir", default="", help="PNG로 저장(인코딩 생략)")
    ap.add_argument("--preview", default="", help="PNG 저장 시 뽑을 프레임 번호(쉼표)")
    args = ap.parse_args()
    render(args)


if __name__ == "__main__":
    main()
