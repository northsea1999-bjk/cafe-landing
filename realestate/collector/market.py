"""가격추이 집계.

두 갈래가 있고, 둘은 성격이 완전히 다르다. 절대 한 선으로 합치지 않는다.

1) 公式・成約価格  — 国土交通省「不動産情報ライブラリ」 API
   실제로 팔린 가격. 무료 공식 데이터라 근거로 가장 강하다.
   ⚠ 한계: 이 데이터에는 **総戸数(세대수)도 물건명도 없다.** 따라서
     "200세대 이상만" 필터를 걸 수 없고, 구 단위 전체 집계만 가능하다.
     이 사이트에서는 '구 전체 시세'라는 배경선으로만 쓴다.

2) 自前・売出価格  — 수집한 매물(中古 / 新築分譲)의 호가
   총세대수가 붙어 오므로 **200세대 이상 大規模マンション만** 걸러서
   구별·단계별로 집계할 수 있다. 사용자가 원한 축이 이쪽이다.
   ⚠ 한계: 호가는 성약가보다 늘 높다. 그리고 과거 데이터는 살 수 없으므로,
     수집을 시작한 시점부터 축적된 만큼만 추이가 나온다.
"""

from __future__ import annotations

import json
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable

from .schema import KIND_MANSION, STAGE_LABELS_JA, STAGE_NEW, STAGE_USED, Listing

API_BASE = "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001"
API_KEY_ENV = "REINFOLIB_API_KEY"
_TIMEOUT = 60
_TSUBO = 3.30578

_TYPE_TO_KIND = {
    "中古マンション等": KIND_MANSION,
    "宅地(土地と建物)": "house",
    "宅地(土地)": "land",
}

#: 대상 7개 구 — 코드와 표기. 순서가 곧 색 슬롯 순서다(색은 구에 고정).
TARGET_WARDS: list[tuple[str, str]] = [
    ("13101", "千代田区"),
    ("13102", "中央区"),
    ("13103", "港区"),
    ("13104", "新宿区"),
    ("13105", "文京区"),
    ("13108", "江東区"),
    ("13113", "渋谷区"),
]

WARD_CODE_BY_NAME = {name: code for code, name in TARGET_WARDS}
WARD_NAME_BY_CODE = {code: name for code, name in TARGET_WARDS}


class MarketUnavailable(RuntimeError):
    """공식 시세 API를 쓸 수 없는 상태 (키 없음 / 네트워크 차단 등)."""


# ======================================================================
# 2) 자체 수집 매물 기반 — 200세대 이상, 구별 × 단계별


def build_listing_trends(
    observations: Iterable[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any] | None:
    """관측 로그(observations.jsonl)에서 구별·단계별 坪単価 중앙값 추이를 만든다.

    스냅샷이 아니라 관측 로그를 쓰는 이유: 스냅샷에는 '지금 팔리고 있는 것'만
    남아서, 掲載終了된 과거 물건이 사라지고 추이가 왜곡된다. 관측 로그는
    한 번 본 가격을 지우지 않는다.
    """
    cfg = config.get("trends", {})
    min_units = int(cfg.get("min_total_units", 200))
    min_samples = int(cfg.get("min_samples", 3))
    granularity = str(cfg.get("granularity", "quarter"))
    synthetic = bool(cfg.get("synthetic", False))

    wards = [str(w) for w in cfg.get("wards", [c for c, _ in TARGET_WARDS])]
    ward_names = {WARD_NAME_BY_CODE.get(code, code) for code in wards}

    # (ward_name, stage, period) -> [坪単価]
    buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    dropped_no_units = 0
    sources_seen: set[str] = set()

    for row in observations:
        ward = str(row.get("ward", ""))
        if ward not in ward_names:
            continue
        units = row.get("total_units")
        if units is None:
            dropped_no_units += 1
            continue
        if int(units) < min_units:
            continue
        unit_price = row.get("unit")
        period = _period_of(str(row.get("listed_on") or row.get("date") or ""), granularity)
        if unit_price is None or period is None:
            continue
        stage = str(row.get("stage") or STAGE_USED)
        buckets[(ward, stage, period)].append(float(unit_price))
        if row.get("source"):
            sources_seen.add(str(row["source"]))

    if not buckets:
        return None

    periods = sorted({p for _, _, p in buckets})
    if len(periods) < 2:
        return None

    series: list[dict[str, Any]] = []
    for code in wards:
        name = WARD_NAME_BY_CODE.get(code, code)
        for stage in (STAGE_USED, STAGE_NEW):
            points = _points(
                {p: buckets.get((name, stage, p), []) for p in periods},
                periods,
                min_samples,
            )
            built = _summarize(points)
            if built is None:
                continue
            series.append(
                {
                    "id": f"{code}|{stage}",
                    "ward_code": code,
                    "ward": name,
                    "stage": stage,
                    "stage_label": STAGE_LABELS_JA[stage],
                    "label": f"{name}・{STAGE_LABELS_JA[stage]}",
                    "points": points,
                    **built,
                }
            )

    if not series:
        return None

    return {
        "generated_at": _now_iso(),
        "synthetic": synthetic,
        "source": "収集した売出物件（中古・新築分譲）の坪単価中央値",
        "measure": "median_man_per_tsubo",
        "measure_label": "売出 坪単価 中央値（万円/坪）",
        "min_total_units": min_units,
        "granularity": granularity,
        "ward_order": [code for code, _ in TARGET_WARDS if code in wards],
        "ward_names": {code: WARD_NAME_BY_CODE.get(code, code) for code in wards},
        "periods": periods,
        "series": series,
        "sources": sorted(sources_seen),
        "notes": {
            "dropped_no_total_units": dropped_no_units,
        },
    }


# ======================================================================
# 1) 공식 성약가 API — 구 단위 배경선


def build_official_trends(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config.get("official_market", {})
    if not cfg.get("enabled"):
        raise MarketUnavailable("official_market.enabled = false")

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise MarketUnavailable(f"환경변수 {API_KEY_ENV} 가 비어 있음")

    wards = [str(w) for w in cfg.get("wards", [c for c, _ in TARGET_WARDS])]
    quarters = _recent_quarters(int(cfg.get("quarters", 20)))
    min_samples = int(cfg.get("min_samples", 5))

    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for ward in wards:
        for year, quarter in quarters:
            params = {
                "year": str(year),
                "quarter": str(quarter),
                "area": ward[:2],
                "city": ward,
            }
            for record in _request(params, api_key):
                if _TYPE_TO_KIND.get(str(record.get("Type", ""))) != KIND_MANSION:
                    continue
                unit = _unit_price(record)
                if unit is not None:
                    buckets[(ward, f"{year}Q{quarter}")].append(unit)

    periods = [f"{y}Q{q}" for y, q in reversed(quarters)]
    series: list[dict[str, Any]] = []
    for ward in wards:
        points = _points({p: buckets.get((ward, p), []) for p in periods}, periods, min_samples)
        built = _summarize(points)
        if built is None:
            continue
        name = WARD_NAME_BY_CODE.get(ward, ward)
        series.append(
            {
                "id": f"{ward}|official",
                "ward_code": ward,
                "ward": name,
                "stage": "official",
                "stage_label": "成約",
                "label": f"{name}・成約",
                "points": points,
                **built,
            }
        )

    if not series:
        raise MarketUnavailable("조건에 맞는 성약 사례가 없음")

    return {
        "generated_at": _now_iso(),
        "synthetic": False,
        "source": "国土交通省 不動産情報ライブラリ (XIT001)",
        "source_url": "https://www.reinfolib.mlit.go.jp/",
        "measure": "median_man_per_tsubo",
        "measure_label": "成約 坪単価 中央値（万円/坪）",
        "min_total_units": None,  # 이 데이터로는 세대수 필터 불가
        "granularity": "quarter",
        "ward_order": [code for code, _ in TARGET_WARDS if code in wards],
        "ward_names": {code: WARD_NAME_BY_CODE.get(code, code) for code in wards},
        "periods": periods,
        "series": series,
        "caveat": "成約価格データには総戸数が含まれないため、200戸以上の絞り込みは適用されていません。",
    }


def _request(params: dict[str, str], api_key: str) -> list[dict[str, Any]]:
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise MarketUnavailable(f"API 키가 거부되었습니다 (HTTP {exc.code})") from exc
        return []
    except Exception:  # noqa: BLE001 - 개별 분기 실패는 결측으로 처리
        return []

    if payload.get("status") != "OK":
        return []
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _unit_price(record: dict[str, Any]) -> float | None:
    price = _to_float(record.get("TradePrice"))
    area = _to_float(record.get("TotalFloorArea")) or _to_float(record.get("Area"))
    if not price or not area or area <= 0:
        return None
    unit = price / 10_000 / (area / _TSUBO)
    return round(unit, 2) if 5 <= unit <= 5_000 else None


# ======================================================================
# 공통


def _points(
    by_period: dict[str, list[float]], periods: list[str], min_samples: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for period in periods:
        values = by_period.get(period, [])
        if len(values) < min_samples:
            # 표본이 부족한 분기는 0으로 눕히지 않고 결측(None)으로 둔다.
            out.append({"period": period, "value": None, "samples": len(values)})
            continue
        out.append(
            {
                "period": period,
                "value": round(statistics.median(values), 1),
                "samples": len(values),
                "p25": round(_quantile(values, 0.25), 1),
                "p75": round(_quantile(values, 0.75), 1),
            }
        )
    return out


def _summarize(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    observed = [p for p in points if p["value"] is not None]
    if len(observed) < 2:
        return None
    first, last = observed[0], observed[-1]
    return {
        "latest": last["value"],
        "latest_period": last["period"],
        "first_value": first["value"],
        "first_period": first["period"],
        "change_pct": round((last["value"] / first["value"] - 1) * 100, 1)
        if first["value"]
        else None,
        "total_samples": sum(p.get("samples", 0) for p in points),
    }


def _period_of(value: str, granularity: str) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if granularity == "month":
        return f"{moment.year}-{moment.month:02d}"
    if granularity == "year":
        return str(moment.year)
    return f"{moment.year}Q{(moment.month - 1) // 3 + 1}"


def _recent_quarters(count: int) -> list[tuple[int, int]]:
    """최근 분기부터 역순으로. 직전 분기는 미공개일 수 있어 한 칸 띄운다."""
    today = date.today()
    year, quarter = today.year, (today.month - 1) // 3 + 1
    quarter -= 1
    if quarter == 0:
        year, quarter = year - 1, 4

    out: list[tuple[int, int]] = []
    for _ in range(max(2, count)):
        out.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return out


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
