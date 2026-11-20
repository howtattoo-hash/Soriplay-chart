"""차트 히스토리 CSV 로딩 + 프레임 타임라인 계산.

render_chart.py(영상)와 build_audio.py(오디오)가 같은 타임라인을 공유하도록
계산 로직을 한 곳에 모아둔다.

타임라인 규칙
  - CSV에 쌓인 날짜들을 왼쪽(과거) → 오른쪽(최신) 순서로 균등 배치한다.
  - 각 구간은 smoothstep(ease-in-out)으로 보간해서 막대가 부드럽게 자란다.
  - 어떤 날짜에 차트에 없던 곡은 스트림 0으로 본다(막대가 새로 등장).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["chart_date", "country", "rank", "artist", "title", "streams", "source"]


def track_key(artist: str, title: str) -> str:
    return f"{artist.strip()} - {title.strip()}"


def smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def load_history(path: str, max_days: int = 7) -> pd.DataFrame:
    """CSV를 읽어 최근 max_days일치만 남기고 정리한다."""
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
    duration: float = 18.0
    fps: int = 30
    top_n: int = 10
    frames: int = field(init=False)

    def __post_init__(self):
        self.frames = max(2, int(round(self.duration * self.fps)))
        self.n_dates = len(self.dates)

    # --- 시간 → 날짜 인덱스 ---------------------------------------------------
    def progress(self, i_frame: int) -> float:
        """0.0(첫 날짜) → 1.0(마지막 날짜) 진행도."""
        if self.frames <= 1:
            return 1.0
        return i_frame / (self.frames - 1)

    def _pos(self, i_frame: int) -> float:
        u = self.progress(i_frame)
        if self.n_dates <= 1:
            return 0.0
        p = u * (self.n_dates - 1)
        k = min(int(math.floor(p)), self.n_dates - 2)
        return k + smoothstep(p - k)

    def date_label(self, i_frame: int) -> str:
        """보간된 날짜 라벨 (진행 바 표시용)."""
        u = self.progress(i_frame)
        if self.n_dates == 1:
            return self.dates[0].isoformat()
        i = min(int(round(u * (self.n_dates - 1))), self.n_dates - 1)
        return self.dates[i].isoformat()

    # --- 프레임별 값 ---------------------------------------------------------
    def values_at(self, i_frame: int) -> np.ndarray:
        pos = self._pos(i_frame)
        k = min(int(math.floor(pos)), max(self.n_dates - 2, 0))
        frac = pos - k
        if self.n_dates == 1:
            return self.values[0].astype(float)
        a = self.values[k].astype(float)
        b = self.values[k + 1].astype(float)
        return a + (b - a) * frac

    def order_at(self, i_frame: int, n: int | None = None) -> list[str]:
        n = n or self.top_n
        vals = self.values_at(i_frame)
        idx = np.argsort(-vals, kind="stable")[:n]
        return [self.keys[i] for i in idx]

    def max_value(self) -> float:
        return float(max(1.0, self.values.max()))

    # --- 오디오 전환용: 1위 곡 구간 ------------------------------------------
    def top1_segments(self, min_len: float = 0.8) -> list[dict]:
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
            "duration": self.duration,
            "fps": self.fps,
            "top_n": self.top_n,
            "keys": self.keys,
            "labels": {k: list(v) for k, v in self.labels.items()},
            "series": {k: [int(x) for x in self.values[:, i]] for i, k in enumerate(self.keys)},
            "segments": self.top1_segments(),
        }


def build_timeline(df: pd.DataFrame, country: str, top_n: int = 10,
                   duration: float = 18.0, fps: int = 30,
                   extra_keys: int = 4) -> Timeline:
    """정리된 히스토리로 Timeline을 만든다."""
    if df.empty:
        raise SystemExit("차트 데이터가 비어 있습니다. fetch_spotify.py를 먼저 실행하세요.")
    dates = sorted(df["chart_date"].unique())
    # 각 날짜의 상위권에 한 번이라도 들어온 곡만 무대에 올린다.
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

    # 값이 큰 곡 위주로 최대 16곡까지만 유지(프레임 렌더링 비용 상한)
    if len(keys) > 16:
        order = np.argsort(-values.max(axis=0))[:16]
        keys = [keys[i] for i in order]
        values = values[:, order]
        ranks = ranks[:, order]

    return Timeline(country=country, dates=dates, keys=keys, labels=labels,
                    values=values, ranks=ranks, duration=duration,
                    fps=fps, top_n=top_n)
