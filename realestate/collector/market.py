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
    observations: Iterable[dict[str, Any]],
    config: dict[str, Any],
    min_units: int | None = None,
) -> dict[str, Any] | None:
    """관측 로그(observations.jsonl)에서 구별·단계별 坪単価 중앙값 추이를 만든다.

    스냅샷이 아니라 관측 로그를 쓰는 이유: 스냅샷에는 '지금 팔리고 있는 것'만
    남아서, 掲載終了된 과거 물건이 사라지고 추이가 왜곡된다. 관측 로그는
    한 번 본 가격을 지우지 않는다.
    """
    cfg = config.get("trends", {})
    if min_units is None:
        min_units = int(cfg.get("min_total_units", 500))
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
                granularity,
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
    station_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    station_hits = 0

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
                if unit is None:
                    continue
                buckets[(ward, f"{year}Q{quarter}")].append(unit)

                # 성약가에도 最寄駅이 들어 있으면 역 단위로도 쌓아 둔다.
                # 이 데이터에는 総戸数가 없으므로 세대수 필터는 여전히 못 건다.
                station = _record_station(record)
                if station in STATION_AREAS:
                    station_hits += 1
                    station_buckets[(station, f"{year}Q{quarter}")].append(unit)

    periods = [f"{y}Q{q}" for y, q in reversed(quarters)]
    series: list[dict[str, Any]] = []
    for ward in wards:
        points = _points({p: buckets.get((ward, p), []) for p in periods}, periods, min_samples, "quarter")
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

    official_stations = [
        {
            "station": station,
            "label_ja": f"{station}駅",
            "label_ko": STATION_AREAS[station][3],
            "ward_code": STATION_AREAS[station][0],
            "lat": STATION_AREAS[station][1],
            "lon": STATION_AREAS[station][2],
            "median": round(statistics.median(values), 1),
            "samples": len(values),
        }
        for (station, _period), values in _merge_by_station(station_buckets).items()
        if len(values) >= min_samples
    ]

    return {
        "generated_at": _now_iso(),
        "synthetic": False,
        "source": "国土交通省 不動産情報ライブラリ (XIT001)",
        "source_url": "https://www.reinfolib.mlit.go.jp/",
        "stations": official_stations,
        "station_records_matched": station_hits,
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


#: 성약가 레코드에서 最寄駅 이름이 담길 수 있는 필드 후보.
#: reinfolib 응답을 이 환경에서 직접 열어보지 못해, 알려진 표기를 모두 시도한다.
_STATION_FIELDS = ("NearestStation", "MinTimeToNearestStation", "Station", "最寄駅：名称")


def _merge_by_station(buckets: dict[tuple[str, str], list[float]]) -> dict[tuple[str, str], list[float]]:
    """분기별로 쪼갠 역 버킷을 역 단위로 합친다 (역별 표본이 적어 기간을 합쳐야 값이 선다)."""
    merged: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (station, _period), values in buckets.items():
        merged[(station, "all")].extend(values)
    return merged


def _record_station(record: dict[str, Any]) -> str:
    for field_name in _STATION_FIELDS:
        value = str(record.get(field_name, "") or "").strip()
        if value and not value.isdigit():
            return value
    return ""


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
    by_period: dict[str, list[float]],
    periods: list[str],
    min_samples: int,
    granularity: str = "quarter",
) -> list[dict[str, Any]]:
    ongoing = current_period(granularity)
    out: list[dict[str, Any]] = []
    for period in periods:
        values = by_period.get(period, [])
        # 아직 안 끝난 구간은 표본이 덜 모여 늘 낮게 나온다. 값은 보여주되
        # '진행 중'이라고 표시해서, 대표 숫자와 변동률에서는 빼도록 한다.
        partial = period == ongoing
        if len(values) < min_samples:
            # 표본이 부족한 구간은 0으로 눕히지 않고 결측(None)으로 둔다.
            out.append({"period": period, "value": None, "samples": len(values), "partial": partial})
            continue
        out.append(
            {
                "period": period,
                "value": round(statistics.median(values), 1),
                "samples": len(values),
                "p25": round(_quantile(values, 0.25), 1),
                "p75": round(_quantile(values, 0.75), 1),
                "partial": partial,
            }
        )
    return out


def _summarize(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    observed = [p for p in points if p["value"] is not None]
    if len(observed) < 2:
        return None
    # 진행 중 구간은 제외하고 요약한다 — 넣으면 늘 '최근 하락'처럼 보인다
    settled = [p for p in observed if not p.get("partial")]
    if len(settled) < 2:
        settled = observed
    first, last = settled[0], settled[-1]
    return {
        "latest": last["value"],
        "latest_period": last["period"],
        "first_value": first["value"],
        "first_period": first["period"],
        "change_pct": round((last["value"] / first["value"] - 1) * 100, 1)
        if first["value"]
        else None,
        "total_samples": sum(p.get("samples", 0) for p in points),
        "has_partial": any(p.get("partial") and p["value"] is not None for p in points),
    }


def current_period(granularity: str) -> str:
    """오늘이 속한 구간. 이 구간은 아직 안 끝났으므로 값이 낮게 잡힌다."""
    today = date.today()
    if granularity == "month":
        return f"{today.year}-{today.month:02d}"
    if granularity == "half":
        return f"{today.year}H{1 if today.month <= 6 else 2}"
    if granularity == "year":
        return str(today.year)
    return f"{today.year}Q{(today.month - 1) // 3 + 1}"


def _period_of(value: str, granularity: str) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if granularity == "month":
        return f"{moment.year}-{moment.month:02d}"
    if granularity == "half":
        return f"{moment.year}H{1 if moment.month <= 6 else 2}"
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

# ======================================================================
# 역세권 단위 세분화 — 지도용
#
# 일본 맨션은 사실상 '가장 가까운 역'을 기준으로 값이 매겨진다. 같은 구
# 안에서도 新宿駅 주변과 四ツ谷駅 주변은 완전히 다른 시장이다. 그래서
# 구를 다시 역세권으로 쪼갠다.
#
# 좌표는 역 위치의 **개략값**이다 (수백 m 오차 가능). 지도에 점을 찍는
# 용도로는 충분하지만 측량값이 아니다. 정밀한 값이 필요하면
# 国土数値情報「鉄道」 데이터로 교체할 것.

#: 역 → (구 코드, 위도, 경도, 한국어 표기)
STATION_AREAS: dict[str, tuple[str, float, float, str]] = {
    # 千代田区
    "東京":       ("13101", 35.6812, 139.7671, "도쿄역"),
    "大手町":     ("13101", 35.6866, 139.7663, "오테마치역"),
    "秋葉原":     ("13101", 35.6984, 139.7731, "아키하바라역"),
    "九段下":     ("13101", 35.6960, 139.7514, "구단시타역"),
    "麹町":       ("13101", 35.6840, 139.7390, "고지마치역"),
    "市ヶ谷":     ("13101", 35.6917, 139.7355, "이치가야역"),
    # 中央区
    "銀座":       ("13102", 35.6717, 139.7650, "긴자역"),
    "日本橋":     ("13102", 35.6822, 139.7745, "니혼바시역"),
    "月島":       ("13102", 35.6644, 139.7840, "쓰키시마역"),
    "勝どき":     ("13102", 35.6588, 139.7770, "가치도키역"),
    "八丁堀":     ("13102", 35.6752, 139.7776, "핫초보리역"),
    "人形町":     ("13102", 35.6862, 139.7827, "닌교초역"),
    "水天宮前":   ("13102", 35.6829, 139.7869, "스이텐구마에역"),
    "馬喰町":     ("13102", 35.6947, 139.7823, "바쿠로초역"),
    # 港区
    "六本木":     ("13103", 35.6628, 139.7315, "롯폰기역"),
    "麻布十番":   ("13103", 35.6556, 139.7360, "아자부주반역"),
    "白金高輪":   ("13103", 35.6431, 139.7343, "시로카네타카나와역"),
    "品川":       ("13103", 35.6285, 139.7387, "시나가와역"),
    "田町":       ("13103", 35.6457, 139.7476, "다마치역"),
    "表参道":     ("13103", 35.6652, 139.7124, "오모테산도역"),
    "赤坂":       ("13103", 35.6725, 139.7365, "아카사카역"),
    # 新宿区
    "新宿":       ("13104", 35.6896, 139.7006, "신주쿠역"),
    "四ツ谷":     ("13104", 35.6862, 139.7301, "요쓰야역"),
    "高田馬場":   ("13104", 35.7126, 139.7038, "다카다노바바역"),
    "神楽坂":     ("13104", 35.7040, 139.7405, "가구라자카역"),
    "西早稲田":   ("13104", 35.7085, 139.7156, "니시와세다역"),
    "曙橋":       ("13104", 35.6930, 139.7245, "아케보노바시역"),
    # 文京区
    "後楽園":     ("13105", 35.7075, 139.7517, "고라쿠엔역"),
    "本郷三丁目": ("13105", 35.7073, 139.7590, "혼고산초메역"),
    "茗荷谷":     ("13105", 35.7170, 139.7382, "묘가다니역"),
    "千駄木":     ("13105", 35.7263, 139.7616, "센다기역"),
    "護国寺":     ("13105", 35.7180, 139.7263, "고코쿠지역"),
    # 江東区
    "豊洲":       ("13108", 35.6547, 139.7967, "도요스역"),
    "東雲":       ("13108", 35.6417, 139.8003, "시노노메역"),
    "門前仲町":   ("13108", 35.6717, 139.7960, "몬젠나카초역"),
    "清澄白河":   ("13108", 35.6817, 139.8003, "기요스미시라카와역"),
    "亀戸":       ("13108", 35.6975, 139.8266, "가메이도역"),
    "木場":       ("13108", 35.6697, 139.8073, "기바역"),
    "有明":       ("13108", 35.6350, 139.7930, "아리아케역"),
    # 渋谷区
    "渋谷":       ("13113", 35.6580, 139.7016, "시부야역"),
    "恵比寿":     ("13113", 35.6467, 139.7100, "에비스역"),
    "代々木":     ("13113", 35.6830, 139.7020, "요요기역"),
    "原宿":       ("13113", 35.6702, 139.7027, "하라주쿠역"),
    "代官山":     ("13113", 35.6484, 139.7031, "다이칸야마역"),
    "初台":       ("13113", 35.6800, 139.6870, "하쓰다이역"),
    "広尾":       ("13113", 35.6520, 139.7220, "히로오역"),
}

#: 한국어 역 이름 → 일본어. 크롬 번역본을 붙여넣어도 역을 알아보게 한다.
STATION_KO_TO_JA: dict[str, str] = {}

STATIONS_BY_WARD: dict[str, list[str]] = defaultdict(list)
for _station, (_ward_code, _lat, _lon, _ko) in STATION_AREAS.items():
    STATIONS_BY_WARD[_ward_code].append(_station)
    STATION_KO_TO_JA[_ko] = _station                 # 「롯폰기역」
    STATION_KO_TO_JA[_ko.removesuffix("역")] = _station  # 「롯폰기」


def normalize_station(name: str) -> str:
    """「스이텐구마에」「水天宮前」「水天宮前駅」 → 「水天宮前」."""
    if not name:
        return ""
    cleaned = name.strip().removesuffix("駅").removesuffix("역").strip()
    if cleaned in STATION_AREAS:
        return cleaned
    return STATION_KO_TO_JA.get(cleaned, cleaned)


def build_area_map(
    observations: Iterable[dict[str, Any]],
    config: dict[str, Any],
    min_units: int | None = None,
) -> dict[str, Any] | None:
    """역세권 단위 坪単価 — 지도에 점으로 찍기 위한 집계.

    분기별 추이와 달리 여기서는 **최근 N분기를 하나로 합쳐** 지역 수준을 낸다.
    역 × 분기까지 쪼개면 표본이 남지 않는다.
    """
    cfg = config.get("area_map", {})
    if cfg.get("enabled") is False:
        return None

    trend_cfg = config.get("trends", {})
    if min_units is None:
        min_units = int(trend_cfg.get("min_total_units", 500))
    min_samples = int(cfg.get("min_samples", 3))
    recent_quarters = int(cfg.get("recent_quarters", 8))
    wards = [str(w) for w in trend_cfg.get("wards", [c for c, _ in TARGET_WARDS])]
    ward_names = {WARD_NAME_BY_CODE.get(c, c) for c in wards}

    rows = [r for r in observations if isinstance(r, dict)]
    all_periods = sorted({
        p for p in (
            _period_of(str(r.get("listed_on") or r.get("date") or ""), "quarter") for r in rows
        ) if p
    })
    if not all_periods:
        return None
    keep = set(all_periods[-recent_quarters:])

    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if str(row.get("ward", "")) not in ward_names:
            continue
        station = str(row.get("sub_area") or "")
        if station not in STATION_AREAS:
            continue
        units = row.get("total_units")
        if units is None or int(units) < min_units:
            continue
        period = _period_of(str(row.get("listed_on") or row.get("date") or ""), "quarter")
        if period not in keep:
            continue
        unit_price = row.get("unit")
        if unit_price is None:
            continue
        buckets[(station, str(row.get("stage") or STAGE_USED))].append(float(unit_price))

    points: list[dict[str, Any]] = []
    for (station, stage), values in buckets.items():
        if len(values) < min_samples:
            continue
        ward_code, lat, lon, ko = STATION_AREAS[station]
        points.append({
            "id": f"{station}|{stage}",
            "station": station,
            "label_ja": f"{station}駅",
            "label_ko": ko,
            "ward_code": ward_code,
            "ward": WARD_NAME_BY_CODE.get(ward_code, ward_code),
            "stage": stage,
            "lat": lat,
            "lon": lon,
            "median": round(statistics.median(values), 1),
            "samples": len(values),
        })

    if not points:
        return None

    points.sort(key=lambda p: -p["median"])
    return {
        "generated_at": _now_iso(),
        "measure_label": "坪単価 中央値（万円/坪）",
        "min_total_units": min_units,
        "periods": sorted(keep),
        "coord_note": "駅の座標は概略値（測量値ではない）",
        "points": points,
    }


def build_station_trends(
    observations: Iterable[dict[str, Any]],
    config: dict[str, Any],
    min_units: int | None = None,
) -> dict[str, Any] | None:
    """역세권 × 단계별 坪単価 추이.

    구 단위보다 표본이 훨씬 적으므로 기본 구간을 반기(half)로 잡는다.
    분기로 쪼개면 대부분의 칸이 결측이 되어 선이 점선처럼 끊긴다.
    """
    cfg = config.get("station_trends", {})
    trend_cfg = config.get("trends", {})
    if min_units is None:
        min_units = int(trend_cfg.get("min_total_units", 500))
    min_samples = int(cfg.get("min_samples", 2))
    granularity = str(cfg.get("granularity", "half"))
    wards = [str(w) for w in trend_cfg.get("wards", [c for c, _ in TARGET_WARDS])]
    ward_names = {WARD_NAME_BY_CODE.get(c, c) for c in wards}

    buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in observations:
        if str(row.get("ward", "")) not in ward_names:
            continue
        station = str(row.get("sub_area") or "")
        if station not in STATION_AREAS:
            continue
        units = row.get("total_units")
        if units is None or int(units) < min_units:
            continue
        period = _period_of(str(row.get("listed_on") or row.get("date") or ""), granularity)
        unit_price = row.get("unit")
        if period is None or unit_price is None:
            continue
        buckets[(station, str(row.get("stage") or STAGE_USED), period)].append(float(unit_price))

    if not buckets:
        return None
    periods = sorted({p for _, _, p in buckets})
    if len(periods) < 2:
        return None

    series: list[dict[str, Any]] = []
    for station, (ward_code, lat, lon, ko) in STATION_AREAS.items():
        if ward_code not in wards:
            continue
        for stage in (STAGE_USED, STAGE_NEW):
            points = _points(
                {p: buckets.get((station, stage, p), []) for p in periods}, periods, min_samples, granularity
            )
            built = _summarize(points)
            if built is None:
                continue
            series.append({
                "id": f"{station}|{stage}",
                "station": station,
                "label_ja": f"{station}駅",
                "label_ko": ko,
                "ward_code": ward_code,
                "ward": WARD_NAME_BY_CODE.get(ward_code, ward_code),
                "stage": stage,
                "stage_label": STAGE_LABELS_JA[stage],
                "lat": lat,
                "lon": lon,
                "points": points,
                **built,
            })

    if not series:
        return None
    return {
        "generated_at": _now_iso(),
        "measure_label": "坪単価 中央値（万円/坪）",
        "min_total_units": min_units,
        "granularity": granularity,
        "periods": periods,
        "series": series,
    }
