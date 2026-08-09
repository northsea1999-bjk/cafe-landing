"""숫자 검증기.

집계 코드(market.py)를 신뢰하지 않고, 원본 관측 로그에서 **독립적으로 다시 계산해서**
web/data/*.json 의 값과 대조한다. 같은 함수를 재사용하면 같은 버그를 함께 통과하므로
여기서는 표준 라이브러리 statistics 만 쓰고 직접 계산한다.

    python3 realestate/audit.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "web" / "data"
TSUBO = 3.30578

problems: list[str] = []
checks = 0


def check(ok: bool, message: str) -> None:
    global checks
    checks += 1
    if not ok:
        problems.append(message)


def load_json(name: str):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_observations() -> list[dict]:
    path = DATA / "observations.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def period_of(value: str, granularity: str) -> str | None:
    if not value or len(value) < 7:
        return None
    year, month = int(value[:4]), int(value[5:7])
    if granularity == "quarter":
        return f"{year}Q{(month - 1) // 3 + 1}"
    if granularity == "half":
        return f"{year}H{1 if month <= 6 else 2}"
    if granularity == "year":
        return str(year)
    return f"{year}-{month:02d}"


def main() -> int:
    market = load_json("market.json")
    if market is None:
        print("market.json 이 없습니다. 먼저 수집기를 실행하세요.", file=sys.stderr)
        return 1

    obs = load_observations()
    print(f"관측 로그 {len(obs):,}행")

    # ---------------------------------------------------------------
    # 1. 관측 행 자체의 산술: 坪単価 = 가격 ÷ (면적 ÷ 3.30578)
    bad_unit = 0
    for row in obs:
        price, area, unit = row.get("price_yen"), row.get("area_m2"), row.get("unit")
        if not price or not area or unit is None:
            continue
        expected = price / 10_000 / (area / TSUBO)
        if abs(expected - unit) > 0.15:            # 반올림 오차 허용
            bad_unit += 1
    check(bad_unit == 0, f"坪単価 계산이 어긋난 관측 {bad_unit}건")

    # ---------------------------------------------------------------
    # 2. 구별 추이: 임계값별로 중앙값을 직접 다시 계산해 대조
    for units_key, trends in (market.get("listing_trends") or {}).items():
        units = int(units_key)
        gran = trends.get("granularity", "quarter")

        buckets = defaultdict(list)
        for row in obs:
            if row.get("total_units") is None or int(row["total_units"]) < units:
                continue
            period = period_of(str(row.get("listed_on") or row.get("date") or ""), gran)
            if period and row.get("unit") is not None:
                buckets[(row["ward"], row["stage"], period)].append(float(row["unit"]))

        mismatches = 0
        threshold_violations = 0
        checked_points = 0

        for series in trends["series"]:
            for point in series["points"]:
                mine = buckets.get((series["ward"], series["stage"], point["period"]), [])
                if point["value"] is None:
                    # 결측이면 표본이 기준 미만이어야 한다
                    if len(mine) >= trends.get("min_samples", 5) and len(mine) >= 5:
                        threshold_violations += 1
                    continue
                checked_points += 1
                if point["samples"] != len(mine):
                    mismatches += 1
                elif abs(statistics.median(mine) - point["value"]) > 0.15:
                    mismatches += 1

        check(mismatches == 0, f"[{units}세대] 구별 추이 값이 재계산과 다름: {mismatches}개 지점")
        check(threshold_violations == 0,
              f"[{units}세대] 표본이 충분한데 결측 처리된 지점: {threshold_violations}개")
        print(f"  {units:>4}세대 구별 추이: {checked_points}개 지점 재계산 대조")

        # 임계값 아래 물건이 섞여 들어가지 않았는지 (필터가 실제로 작동하는지)
        below = [r for r in obs if r.get("total_units") is not None and int(r["total_units"]) < units]
        leaked = 0
        for series in trends["series"]:
            total_declared = sum(p.get("samples", 0) for p in series["points"])
            mine_total = sum(
                len(v) for (w, st, _), v in buckets.items()
                if w == series["ward"] and st == series["stage"]
            )
            if total_declared != mine_total:
                leaked += 1
        check(leaked == 0, f"[{units}세대] 표본 수가 재계산과 다른 계열: {leaked}개")
        check(trends["min_total_units"] == units,
              f"[{units}세대] min_total_units 표기가 {trends['min_total_units']}")

        # 변동률 = 마지막/처음 - 1
        pct_bad = 0
        for series in trends["series"]:
            seen = [p for p in series["points"] if p["value"] is not None]
            if len(seen) < 2 or series.get("change_pct") is None:
                continue
            expected = (seen[-1]["value"] / seen[0]["value"] - 1) * 100
            if abs(expected - series["change_pct"]) > 0.15:
                pct_bad += 1
        check(pct_bad == 0, f"[{units}세대] 변동률이 어긋난 계열 {pct_bad}개")

    # ---------------------------------------------------------------
    # 3. 지도: 최근 N분기 합산 중앙값
    for units_key, area in (market.get("area_map") or {}).items():
        units = int(units_key)
        keep = set(area["periods"])
        buckets = defaultdict(list)
        for row in obs:
            if row.get("total_units") is None or int(row["total_units"]) < units:
                continue
            if not row.get("sub_area"):
                continue
            period = period_of(str(row.get("listed_on") or row.get("date") or ""), "quarter")
            if period in keep and row.get("unit") is not None:
                buckets[(row["sub_area"], row["stage"])].append(float(row["unit"]))

        bad = 0
        for point in area["points"]:
            mine = buckets.get((point["station"], point["stage"]), [])
            if point["samples"] != len(mine) or abs(statistics.median(mine) - point["median"]) > 0.15:
                bad += 1
        check(bad == 0, f"[{units}세대] 지도 지점 값이 재계산과 다름: {bad}개")
        print(f"  {units:>4}세대 지도: {len(area['points'])}개 지점 대조")

    # ---------------------------------------------------------------
    # 4. 역세권 추이
    for units_key, st in (market.get("station_trends") or {}).items():
        units = int(units_key)
        gran = st.get("granularity", "half")
        buckets = defaultdict(list)
        for row in obs:
            if row.get("total_units") is None or int(row["total_units"]) < units:
                continue
            if not row.get("sub_area"):
                continue
            period = period_of(str(row.get("listed_on") or row.get("date") or ""), gran)
            if period and row.get("unit") is not None:
                buckets[(row["sub_area"], row["stage"], period)].append(float(row["unit"]))

        bad = 0
        for series in st["series"]:
            for point in series["points"]:
                mine = buckets.get((series["station"], series["stage"], point["period"]), [])
                if point["value"] is None:
                    continue
                if point["samples"] != len(mine) or abs(statistics.median(mine) - point["value"]) > 0.15:
                    bad += 1
        check(bad == 0, f"[{units}세대] 역세권 추이 값이 재계산과 다름: {bad}개")
        print(f"  {units:>4}세대 역세권: {len(st['series'])}개 계열 대조")

    # ---------------------------------------------------------------
    # 5. 신규 매물 목록의 파생값
    recent = load_json("recent-new.json") or {}
    bad_price = bad_unit2 = 0
    for item in recent.get("items", []):
        if item.get("price_yen") and item.get("price_man"):
            if abs(item["price_yen"] / 10_000 - item["price_man"]) > 0.5:
                bad_price += 1
        if item.get("price_yen") and item.get("area_m2") and item.get("unit_price_man_per_tsubo"):
            expected = item["price_yen"] / 10_000 / (item["area_m2"] / TSUBO)
            if abs(expected - item["unit_price_man_per_tsubo"]) > 0.15:
                bad_unit2 += 1
    check(bad_price == 0, f"万円 환산이 어긋난 매물 {bad_price}건")
    check(bad_unit2 == 0, f"坪単価가 어긋난 매물 {bad_unit2}건")

    # 세대수 조건: 목록은 화면에서 걸러지므로 여기서는 값이 있는지만 본다
    missing_units = sum(1 for x in recent.get("items", []) if x.get("total_units") is None)
    check(missing_units == 0, f"총세대수가 비어 화면 필터에서 탈락할 매물 {missing_units}건")
    print(f"  신규 매물 {len(recent.get('items', []))}건 파생값 대조")

    # ---------------------------------------------------------------
    # 6. 경계 데이터
    geo = load_json("tokyo-wards.json")
    if geo:
        targets = {"13101", "13102", "13103", "13104", "13105", "13108", "13113"}
        codes = {w["code"] for w in geo["wards"]}
        check(targets <= codes, f"경계 데이터에 없는 대상 구: {targets - codes}")
        flat = [pt for w in geo["wards"] for ring in w["rings"] for pt in ring]
        out_of_range = [p for p in flat if not (138.8 < p[0] < 140.0 and 35.4 < p[1] < 36.0)]
        check(not out_of_range, f"도쿄 범위를 벗어난 좌표 {len(out_of_range)}개")
        print(f"  경계 {len(geo['wards'])}구 / 좌표 {len(flat):,}개 범위 확인")

    # ---------------------------------------------------------------
    print()
    if problems:
        print(f"❌ 검사 {checks}건 중 {len(problems)}건 실패")
        for p in problems:
            print(f"   - {p}")
        return 1
    print(f"✅ 검사 {checks}건 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
