"""도쿄 23구 경계를 지도용으로 가볍게 줄인다.

원본: https://github.com/dataofjapan/land (tokyo.geojson)
      국토교통성 국토수치정보(행정구역)를 가공한 공개 데이터.

원본은 6MB가 넘어 그대로 웹에 실을 수 없다. 화면에서는 폭 1000px 안에
23개 구를 다 그리므로 수 미터 단위 정밀도는 의미가 없다. 그래서
Douglas–Peucker 로 단순화하고 좌표를 반올림해 100KB 안쪽으로 줄인다.

    python3 realestate/build_geo.py            # 없으면 내려받아서 생성
    python3 realestate/build_geo.py --refresh  # 원본을 다시 내려받기
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_URL = "https://raw.githubusercontent.com/dataofjapan/land/master/tokyo.geojson"
CACHE = ROOT / "data" / "tokyo.geojson"
OUT = ROOT / "web" / "data" / "tokyo-wards.json"

#: 이 사이트가 다루는 7개 구. 나머지 구는 형태를 알아보게 하는 배경으로만 그린다.
TARGET_WARDS = {"千代田区", "中央区", "港区", "新宿区", "文京区", "江東区", "渋谷区"}

TOLERANCE = 0.00035   # 도 단위. 위도 1도 ≈ 111km → 약 39m
DECIMALS = 4          # 약 11m 격자로 반올림
MIN_RING_POINTS = 5   # 이보다 적게 남는 조각(작은 섬 등)은 버린다


def download(force: bool = False) -> Path:
    if CACHE.exists() and not force:
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"내려받는 중: {SOURCE_URL}")
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as resp:
        CACHE.write_bytes(resp.read())
    return CACHE


def perpendicular_distance(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    tt = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    tt = max(0.0, min(1.0, tt))
    return math.hypot(px - (ax + tt * dx), py - (ay + tt * dy))


def simplify(points: list, tolerance: float) -> list:
    """Douglas–Peucker. 재귀 대신 스택을 써서 긴 링에서도 안전하게."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        start, end = stack.pop()
        worst, worst_index = 0.0, -1
        for i in range(start + 1, end):
            d = perpendicular_distance(points[i], points[start], points[end])
            if d > worst:
                worst, worst_index = d, i
        if worst > tolerance and worst_index > 0:
            keep[worst_index] = True
            stack.append((start, worst_index))
            stack.append((worst_index, end))

    return [p for p, k in zip(points, keep) if k]


def round_ring(ring: list) -> list:
    out = []
    for x, y in ring:
        pt = [round(x, DECIMALS), round(y, DECIMALS)]
        if not out or out[-1] != pt:      # 반올림으로 겹친 점 제거
            out.append(pt)
    return out


def rings_of(geometry: dict) -> list[list]:
    """Polygon / MultiPolygon 의 바깥 링만 모은다 (구멍은 쓰지 않는다)."""
    kind = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if kind == "Polygon":
        return [coords[0]] if coords else []
    if kind == "MultiPolygon":
        return [poly[0] for poly in coords if poly]
    return []


def build(force: bool = False) -> Path:
    path = download(force)
    data = json.loads(path.read_text(encoding="utf-8"))

    wards = []
    kept_points = raw_points = 0

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        name = props.get("ward_ja")
        if not name or props.get("area_ja") != "都区部":
            continue      # 23구만. 시부·군부는 지도 범위 밖이다.

        parts = []
        for ring in rings_of(feature.get("geometry", {})):
            raw_points += len(ring)
            simplified = round_ring(simplify([tuple(p) for p in ring], TOLERANCE))
            if len(simplified) >= MIN_RING_POINTS:
                parts.append(simplified)
                kept_points += len(simplified)

        if not parts:
            continue

        code = str(props.get("code", ""))[:5]
        wards.append({
            "name": name,
            "code": code,
            "target": name in TARGET_WARDS,
            "rings": parts,
        })

    if len(wards) != 23:
        print(f"경고: 23구를 기대했는데 {len(wards)}개만 나왔습니다", file=sys.stderr)

    missing = TARGET_WARDS - {w["name"] for w in wards}
    if missing:
        raise SystemExit(f"대상 구가 빠졌습니다: {missing}")

    payload = {
        "source": "dataofjapan/land (国土交通省 国土数値情報 行政区域データ 由来)",
        "source_url": "https://github.com/dataofjapan/land",
        "note": f"表示用に簡略化（許容誤差 約{round(TOLERANCE * 111000)}m）",
        "tolerance_deg": TOLERANCE,
        "wards": wards,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    print(
        f"{OUT}  {OUT.stat().st_size / 1024:.0f} KB  "
        f"({len(wards)}구, 점 {raw_points:,} → {kept_points:,})"
    )
    return OUT


if __name__ == "__main__":
    build(force="--refresh" in sys.argv)
