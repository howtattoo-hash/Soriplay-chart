"""13개국 주간 차트를 어떤 날 어떤 나라로 올릴지 계산한다.

운영 규칙 (사용자 확정)
  · 월~토: 하루 2개국 (09:00 KST · 19:00 KST)
  · 일요일: 1개국 (09:00 KST)
  → 한 주에 정확히 13개국이 한 번씩 돌아간다.

순서는 config/countries.json 의 order 배열을 따른다(기본: global → kr → us → gb → br →
mx → id → vn → th → ph → my → sa → in). 첫 칸(월 09:00)이 가장 중요한 자리이므로
가장 먼저 보고 싶은 시장(글로벌, 한국)이 앞에 온다.

명령줄
  python scripts/rotation.py                 # 지금 시각 기준 국가 코드 출력 (없으면 빈 줄)
  python scripts/rotation.py --table         # 한 주 전체 시간표
  python scripts/rotation.py --now 2026-11-20T19:00 --code
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import chart_config

KST = dt.timezone(dt.timedelta(hours=9), "KST")
MORNING_CUTOFF_HOUR = 14   # 14시 이전 실행 = 오전 칸, 이후 = 오후 칸
PER_WEEK = 13


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def slot_index(when: dt.datetime) -> int | None:
    """그 시각에 올릴 칸 번호(0~12). 일요일 저녁처럼 올릴 칸이 없으면 None."""
    when = when.astimezone(KST)
    wd = when.weekday()               # 월=0 ... 일=6
    afternoon = when.hour >= MORNING_CUTOFF_HOUR
    if wd == 6:                       # 일요일은 오전 한 칸뿐
        return None if afternoon else 12
    return wd * 2 + (1 if afternoon else 0)


def country_for(when: dt.datetime, order: list[str] | None = None) -> str | None:
    order = order or chart_config.order()
    idx = slot_index(when)
    if idx is None or idx >= len(order):
        return None
    return order[idx]


def time_label(when: dt.datetime) -> str:
    when = when.astimezone(KST)
    return "19:00" if when.hour >= MORNING_CUTOFF_HOUR else "09:00"


def table(order: list[str] | None = None) -> list[dict]:
    """다음 한 주(월~일)의 업로드 시간표."""
    order = order or chart_config.order()
    days = ["월", "화", "수", "목", "금", "토", "일"]
    rows: list[dict] = []
    for wd in range(7):
        times = ["09:00"] if wd == 6 else ["09:00", "19:00"]
        for t in times:
            idx = len(rows)
            rows.append({"day": days[wd], "weekday": wd, "time": t,
                         "slot": idx, "country": order[idx] if idx < len(order) else None})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="13개국 순번 계산")
    ap.add_argument("--now", default="", help="기준 시각 (KST, 예: 2026-11-20T09:00)")
    ap.add_argument("--table", action="store_true", help="한 주 시간표 출력")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--slot", action="store_true", help="칸 번호만 출력")
    args = ap.parse_args()

    when = dt.datetime.fromisoformat(args.now).replace(tzinfo=KST) if args.now else now_kst()

    if args.table:
        if args.json:
            print(json.dumps(table(), ensure_ascii=False, indent=1))
            return
        print(f"{'요일':<3}{'시각':<7}{'칸':<4}국가")
        for row in table():
            print(f"{row['day']:<4}{row['time']:<8}{row['slot']:<4}{row['country'] or '-'}")
        return

    idx = slot_index(when)
    code = country_for(when)
    if args.json:
        print(json.dumps({"now_kst": when.isoformat(), "slot": idx, "country": code},
                         ensure_ascii=False))
        return
    if args.slot:
        print("" if idx is None else idx)
        return
    if code is None:
        print(f"[rotation] {when:%Y-%m-%d %H:%M} KST · 이 시간대에는 올릴 칸이 없습니다(일요일 저녁).",
              file=sys.stderr, flush=True)
        print("")
        return
    print(code)


if __name__ == "__main__":
    main()
