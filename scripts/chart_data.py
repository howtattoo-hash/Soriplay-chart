"""차트 히스토리 CSV 로딩 + 프레임 타임라인 계산.

render_chart.py(영상)와 build_audio.py(오디오)가 같은 타임라인을 공유하도록
계산 로직을 한 곳에 모아둔다.

타임라인 규칙
  - CSV에 쌓인 시점(주간이면 주 단위)을 왼쪽(과거) → 오른쪽(최신) 순서로 균등 배치한다.
  - 시점과 시점 사이는 **곡마다 다른 속도 곡선**으로 보간한다. 어떤 곡은 초반에 몰아서
    오르고 어떤 곡은 막판에 치고 올라오므로, 영상 안에서 막대가 서로를 추월했다가
    다시 따라잡는 장면이 계속 생긴다.
  - 곡별 곡선은 제목 해시로 정해지므로 같은 데이터를 다시 렌더해도 결과가 똑같다.
  - 곡별 P+(직전 기간 대비 순위 변화)가 CSV 에 있으면 배지(▲2 / ▼1 / NEW)에 그대로 쓴다.
  - 어떤 시점에 차트에 없던 곡은 스트림 0으로 본다(막대가 새로 등장).
"""
from __future__ import annotations

import hashlib
import math
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["chart_date", "country", "rank", "artist", "title", "streams", "source"]

# 곡별 보간 곡선 파라미터 범위
K_RANGE = (0.55, 1.90)      # 작을수록 초반에 몰아 오름, 클수록 막판에 치고 올라옴
AMP_RANGE = (0.015, 0.075)  # 구간 중간의 출렁임(추월을 여러 번 만들기 위한 작은 진폭)
HOLD_FRAC = 0.62            # 한 칸 안에서 이 비율까지 값이 차고, 남은 구간은 버틴다(비트감)
WEEK_DAYS = 7               # 주간 차트를 요일 7칸으로 펼친다


def track_key(artist: str, title: str) -> str:
    return f"{artist.strip()} - {title.strip()}"


def smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def curve_params(key: str) -> tuple[float, float, float]:
    """곡 키 하나로 (속도 지수 k, 출렁임 진폭, 위상)을 만든다. 해시라 항상 같은 값."""
    h = hashlib.sha1(key.encode("utf-8")).digest()
    k = K_RANGE[0] + (K_RANGE[1] - K_RANGE[0]) * (h[0] / 255.0)
    amp = AMP_RANGE[0] + (AMP_RANGE[1] - AMP_RANGE[0]) * (h[1] / 255.0)
    phase = (h[2] / 255.0) * 2.0 * math.pi
    return k, amp, phase


def week_shape(key: str) -> np.ndarray:
    """곡별 7일 누적 비중(첫날…마지막날). 그 주 합계를 요일별로 쌓는 모양이다.

    곡마다 정점 요일이 달라서, 어떤 곡은 초반에 치고 나가고 어떤 곡은 막판에
    몰아치면서 영상 중간에 1위가 여러 번 바뀐다. 마지막 값은 정확히 1.0.
    """
    h = hashlib.sha1(key.encode("utf-8")).digest()
    peak = 1 + (h[3] % WEEK_DAYS)              # 1~7일쨤 정점
    sharp = 1.05 + (h[4] / 255.0) * 1.45       # 정점 폭
    days = np.arange(1, WEEK_DAYS + 1, dtype=float)
    w = np.exp(-((days - peak) ** 2) / (2.0 * sharp ** 2))
    total = w.sum()
    if total <= 0:
        w = np.ones_like(w)
        total = w.sum()
    return np.cumsum(w / total)


def ease_vector(u: np.ndarray, k: np.ndarray, amp: np.ndarray,
                phase: np.ndarray) -> np.ndarray:
    """구간 진행도 u(0~1)에서 곡별로 다른 성장 곡선. u=0 → 0, u=1 → 1 보장.

    앞 62%에서 값이 차고 나머지는 버티는 리듬(hold-and-surge)을 준다.
    """
    u = np.clip(u, 0.0, 1.0)
    q = np.clip(u / HOLD_FRAC, 0.0, 1.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.power(q, k)
        b = np.power(1.0 - q, k)
        s = np.where((a + b) > 0, a / (a + b), q)
    s = np.where(q <= 0.0, 0.0, np.where(q >= 1.0, 1.0, s))
    wave = amp * np.sin(np.pi * u) * np.sin(2.0 * np.pi * u + phase)
    wave = np.where((u <= 0.0) | (u >= 1.0), 0.0, wave)
    return np.clip(s + wave, 0.0, 1.08)


def load_history(path: str, max_days: int = 7) -> pd.DataFrame:
    """CSV를 읽어 최근 max_days개 시점만 남기고 정리한다."""
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"{path}: 필수 컬럼 누락 {missing}")
    df = df.copy()
    df["chart_date"] = pd.to_datetime(df["chart_date"], errors="coerce").dt.date
    df = df.dropna(subset=["chart_date"])
    df["streams"] = pd.to_numeric(df["streams"], errors="coerce").fillna(0).astype("int64")
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["artist"] = df["artist"].astype(str).str.strip()
    df["title"] = df["title"].astype(str).str.strip()
    df["key"] = [track_key(a, t) for a, t in zip(df["artist"], df["title"])]

    dates = sorted(df["chart_date"].unique())[-max_days:]
    df = df[df["chart_date"].isin(dates)]
    # 같은 날짜에 같은 곡이 두 번 들어오면 순위가 좋은(숫자가 작은) 행만 남긴다.
    df = df.sort_values(["chart_date", "rank"])
    df = df.drop_duplicates(["chart_date", "key"], keep="first")
    return df.reset_index(drop=True)


@dataclass
class Timeline:
    country: str
    dates: list                      # [datetime.date, ...] 오래된 → 최신
    keys: list                       # 화면에 등장할 곡 키 목록
    labels: dict                     # key -> (artist, title)
    values: np.ndarray               # shape (n_dates, n_keys)
    ranks: np.ndarray                # shape (n_dates, n_keys), 없는 곡은 큰 값
    duration: float = 45.0
    fps: int = 30
    top_n: int = 10
    metric: str = "streams"          # streams / score (스트림 비공개 차트)
    official_change: dict = field(default_factory=dict)   # key -> '+7' / '-1' / 'NEW' …
    frames: int = field(init=False)

    def __post_init__(self):
        self.frames = max(2, int(round(self.duration * self.fps)))
        self.n_dates = len(self.dates)
        params = np.array([curve_params(k) for k in self.keys], dtype=float)
        self.curve_k = params[:, 0]
        self.curve_amp = params[:, 1]
        self.curve_phase = params[:, 2]

    # --- 시간 → 날짜 인덱스 ---------------------------------------------------
    def progress(self, i_frame: int) -> float:
        """0.0(첫 시점) → 1.0(마지막 시점) 진행도."""
        if self.frames <= 1:
            return 1.0
        return i_frame / (self.frames - 1)

    def _pos(self, i_frame: int) -> float:
        """시점 사이의 연속 위치(0 ~ n_dates-1). 곡선은 values_at 에서 곡별로 적용한다."""
        u = self.progress(i_frame)
        if self.n_dates <= 1:
            return 0.0
        return u * (self.n_dates - 1)

    def date_label(self, i_frame: int) -> str:
        """지금 화면이 보여주는 차트 시점(요일/주). 막대가 그 칸의 값을 다 채우면 넘어간다."""
        if self.n_dates == 1:
            return self.dates[0].isoformat()
        pos = self._pos(i_frame)
        idx = int(math.floor(pos - HOLD_FRAC)) + 1
        idx = min(max(idx, 0), self.n_dates - 1)
        return self.dates[idx].isoformat()

    def day_index(self, i_frame: int) -> int:
        """지금 몇 번째 시점을 보여주는지(0부터). 날짜 표시가 바뀌는 순간을 잡는 데 쓴다."""
        if self.n_dates == 1:
            return 0
        pos = self._pos(i_frame)
        idx = int(math.floor(pos - HOLD_FRAC)) + 1
        return min(max(idx, 0), self.n_dates - 1)

    # --- 프레임별 값 ---------------------------------------------------------
    def values_at(self, i_frame: int) -> np.ndarray:
        pos = self._pos(i_frame)
        if self.n_dates == 1:
            # 시점이 하나뿐이면(예: 인도 주간) 0에서 최종값까지 곡별 곡선으로 차오르게 한다.
            u = self.progress(i_frame)
            ease = ease_vector(np.full(len(self.keys), u), self.curve_k,
                               self.curve_amp, self.curve_phase)
            return self.values[0].astype(float) * ease
        k = min(int(math.floor(pos)), self.n_dates - 2)
        frac = pos - k
        a = self.values[k].astype(float)
        b = self.values[k + 1].astype(float)
        if frac <= 0.0:
            return a
        if frac >= 1.0:
            return b
        ease = ease_vector(np.full(len(self.keys), frac), self.curve_k,
                           self.curve_amp, self.curve_phase)
        return a + (b - a) * ease

    def order_at(self, i_frame: int, n: int | None = None) -> list[str]:
        n = n or self.top_n
        vals = self.values_at(i_frame)
        idx = np.argsort(-vals, kind="stable")[:n]
        return [self.keys[i] for i in idx]

    def rank_map(self, i_frame: int) -> dict[str, int]:
        """곡별 현재 순위(1부터). top_n 밖은 큰 값."""
        vals = self.values_at(i_frame)
        order = np.argsort(-vals, kind="stable")
        return {self.keys[i]: r + 1 for r, i in enumerate(order)}

    def rank_swing(self) -> dict[str, int]:
        """영상 처음 순위 - 마지막 순위. 양수면 올라간 곡."""
        def ranks_at(i: int) -> dict[str, int]:
            vals = self.values_at(i)
            order = np.argsort(-vals, kind="stable")
            return {self.keys[j]: r + 1 for r, j in enumerate(order)}
        first, last = ranks_at(0), ranks_at(self.frames - 1)
        return {k: first.get(k, 10 ** 6) - last.get(k, 10 ** 6) for k in self.keys}

    def max_value(self) -> float:
        return float(max(1.0, self.values.max()))

    # --- 오디오 전환용: 1위 곡 구간 ------------------------------------------
    def top1_segments(self, min_len: float = 2.0) -> list[dict]:
        """프레임별 1위 곡을 묶어 (시작초, 종료초, 곡) 구간 목록을 만든다."""
        raw: list[dict] = []
        for i in range(self.frames):
            key = self.order_at(i, 1)[0]
            if raw and raw[-1]["key"] == key:
                raw[-1]["end"] = (i + 1) / self.fps
            else:
                raw.append({"key": key, "start": i / self.fps, "end": (i + 1) / self.fps})
        # 짧게 스쳐가는 구간은 앞 구간에 흡수해 오디오가 자르듯 끊기지 않게 한다.
        merged: list[dict] = []
        for seg in raw:
            if merged and (seg["end"] - seg["start"]) < min_len:
                merged[-1]["end"] = seg["end"]
            else:
                merged.append(dict(seg))
        for seg in merged:
            artist, title = self.labels.get(seg["key"], ("", seg["key"]))
            seg["artist"] = artist
            seg["title"] = title
        return merged

    def to_dict(self) -> dict:
        return {
            "country": self.country,
            "dates": [d.isoformat() for d in self.dates],
            "week_start": self.dates[0].isoformat(),
            "week_end": self.dates[-1].isoformat(),
            "duration": self.duration,
            "fps": self.fps,
            "top_n": self.top_n,
            "metric": self.metric,
            "keys": self.keys,
            "labels": {k: list(v) for k, v in self.labels.items()},
            "series": {k: [int(x) for x in self.values[:, i]] for i, k in enumerate(self.keys)},
            "segments": self.top1_segments(),
        }


def build_timeline(df: pd.DataFrame, country: str, top_n: int = 10,
                   duration: float = 45.0, fps: int = 30,
                   extra_keys: int = 6, period: str = "weekly") -> Timeline:
    """정리된 히스토리로 Timeline을 만든다."""
    if df.empty:
        raise SystemExit("차트 데이터가 비어 있습니다. fetch_spotify.py를 먼저 실행하세요.")
    dates = sorted(df["chart_date"].unique())
    # 각 시점의 상위권에 한 번이라도 들어온 곡만 무대에 올린다(추월 장면이 많도록 여유를 둔다).
    keys: list[str] = []
    for d in dates:
        day = df[df["chart_date"] == d].sort_values("rank")
        for k in day["key"].head(top_n + extra_keys):
            if k not in keys:
                keys.append(k)

    labels = {}
    for k in keys:
        row = df[df["key"] == k].iloc[0]
        labels[k] = (row["artist"], row["title"])

    values = np.zeros((len(dates), len(keys)), dtype=np.int64)
    ranks = np.full((len(dates), len(keys)), 10 ** 6, dtype=np.int64)
    for j, d in enumerate(dates):
        day = df[df["chart_date"] == d]
        rank_map = dict(zip(day["key"], day["rank"].fillna(10 ** 6).astype(int)))
        val_map = dict(zip(day["key"], day["streams"]))
        for i, k in enumerate(keys):
            values[j, i] = val_map.get(k, 0)
            ranks[j, i] = rank_map.get(k, 10 ** 6)

    # 값이 큰 곡 위주로 최대 18곡까지만 유지(프레임 렌더링 비용 상한)
    if len(keys) > 18:
        order = np.argsort(-values.max(axis=0))[:18]
        keys = [keys[i] for i in order]
        values = values[:, order]
        ranks = ranks[:, order]
        labels = {k: labels[k] for k in keys}

    # 최신 시점의 공식 순위 변화(P+) — 있으면 배지에 그대로 쓴다
    official: dict[str, str] = {}
    if "rank_change" in df.columns:
        last = df[df["chart_date"] == dates[-1]]
        for _i, row in last.iterrows():
            raw = row.get("rank_change")
            if pd.isna(raw):
                continue
            if isinstance(raw, str):
                val = raw.strip()
                if not val:
                    continue
            else:
                try:
                    num = int(raw)
                except (TypeError, ValueError):
                    continue
                if num == 0:
                    continue
                val = f"+{num}" if num > 0 else str(num)
            official[row["key"]] = val

    # 스트림 수치가 전혀 없는 차트(예: 인도)는 순위 점수로 바를 만든다.
    metric = "streams"
    if values.max() <= 0:
        metric = "score"
        scored = np.zeros(values.shape, dtype=float)
        for j in range(values.shape[0]):
            row = ranks[j]
            known = row < 10 ** 6
            n_chart = int(known.sum())
            if n_chart:
                # 1위 = 100점 … 꼴등 = 100/N 점
                scored[j, known] = (n_chart - row[known] + 1) / n_chart * 100.0
        values = np.round(scored).astype(np.int64)

    # 주간 차트: 최신 주의 합계를 7일치로 펼처서 날짜가 하루씩 흐르는 레이스를 만든다.
    if period == "weekly" and len(dates) >= 1:
        last_date = dates[-1]
        totals = values[-1].astype(float)
        week_values = np.zeros((WEEK_DAYS, len(keys)), dtype=np.int64)
        for i, k in enumerate(keys):
            shape = week_shape(k)
            week_values[:, i] = np.round(totals[i] * shape).astype(np.int64)
        week_values[-1, :] = values[-1]          # 마지막 날 = 그 주 합계 그대로
        week_ranks = np.full(week_values.shape, 10 ** 6, dtype=np.int64)
        for j in range(WEEK_DAYS):
            for r, idx in enumerate(np.argsort(-week_values[j], kind="stable"), start=1):
                week_ranks[j, idx] = r
        dates = [last_date + dt.timedelta(days=k) for k in range(WEEK_DAYS)]
        values, ranks = week_values, week_ranks

    return Timeline(country=country, dates=dates, keys=keys, labels=labels,
                    values=values, ranks=ranks, duration=duration,
                    fps=fps, top_n=top_n, metric=metric, official_change=official)
