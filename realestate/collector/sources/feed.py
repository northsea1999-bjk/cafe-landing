"""라이선스된 물건 피드 어댑터 (CSV / JSON).

일본에서 중고 매물 원본을 합법적으로 받는 경로는 사실상 "피드"다 —
宅建業者가 REINS/ATBB 에서 내보낸 CSV, 物件流通システム 벤더가 주는 JSON,
제휴 계약으로 받는 파트너 API 응답 등. 형태는 달라도 전부 '표 형태의 행'
이므로, 이 어댑터 하나로 받고 field_map 으로 컬럼만 맞춰주면 된다.

config 예시 (config.json 의 sources.feed):

    {
      "enabled": true,
      "basis": "○○流通システム 데이터 이용계약 2026-01",
      "location": "data/incoming/listings.csv",   // 또는 https URL
      "format": "csv",                            // csv | json
      "json_path": "data.items",                  // format=json 일 때 배열 위치
      "encoding": "cp932",                        // 일본 업계 CSV는 Shift_JIS가 흔하다
      "field_map": {
        "source_id": "物件番号",
        "title": "物件名",
        "price": "価格",
        "address": "所在地",
        "area_m2": "専有面積",
        "layout": "間取り",
        "built": "築年月",
        "floor": "所在階",
        "url": "詳細URL"
      }
    }
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path
from typing import Any

from ..schema import (
    KIND_MANSION,
    Listing,
    Station,
    parse_area_m2,
    parse_built,
    parse_price_to_yen,
    parse_stage,
    parse_walk_minutes,
    split_address,
)
from .base import Source, SourceError

_TIMEOUT = 60


class FeedSource(Source):
    key = "feed"
    name = "ライセンス済み物件フィード"
    basis = "이용 계약이 있는 피드만. config 의 basis 필드에 근거를 적어야 동작한다."

    def available(self, config: dict[str, Any]) -> tuple[bool, str]:
        cfg = config.get("sources", {}).get(self.key, {})
        if not cfg.get("enabled"):
            return False, "sources.feed.enabled = false"
        if not cfg.get("location"):
            return False, "sources.feed.location 이 비어 있음"
        if not cfg.get("basis"):
            # 출처 근거 없는 데이터가 조용히 섞여 들어가는 걸 막는다.
            return False, "sources.feed.basis 에 데이터 이용 근거를 적어야 함"
        return True, ""

    def fetch(self, config: dict[str, Any]) -> list[Listing]:
        cfg = config.get("sources", {}).get(self.key, {})
        rows = self._load_rows(cfg)
        field_map = cfg.get("field_map", {})
        default_kind = cfg.get("kind", KIND_MANSION)

        listings: list[Listing] = []
        for index, row in enumerate(rows):
            listing = self._to_listing(row, field_map, default_kind, index)
            if listing is not None:
                listings.append(listing)
        return listings

    # ------------------------------------------------------------------
    def _load_rows(self, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        location = str(cfg["location"])
        encoding = cfg.get("encoding", "utf-8")

        if location.startswith(("http://", "https://")):
            req = urllib.request.Request(
                location,
                headers={"User-Agent": cfg.get("user_agent", "realestate-collector/1.0")},
            )
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    raw = resp.read()
            except Exception as exc:  # noqa: BLE001 - 원인 그대로 올려준다
                raise SourceError(f"피드를 가져오지 못했습니다: {location} ({exc})") from exc
        else:
            path = Path(location)
            if not path.is_absolute():
                path = Path(cfg.get("base_dir", ".")) / path
            if not path.exists():
                raise SourceError(f"피드 파일이 없습니다: {path}")
            raw = path.read_bytes()

        text = raw.decode(encoding, errors="replace")
        fmt = cfg.get("format", "csv").lower()

        if fmt == "json":
            data: Any = json.loads(text)
            for part in filter(None, str(cfg.get("json_path", "")).split(".")):
                data = data[part]
            if not isinstance(data, list):
                raise SourceError("json_path 가 배열을 가리키지 않습니다")
            return data

        if fmt == "csv":
            return list(csv.DictReader(io.StringIO(text)))

        raise SourceError(f"지원하지 않는 format: {fmt}")

    # ------------------------------------------------------------------
    def _to_listing(
        self,
        row: dict[str, Any],
        field_map: dict[str, str],
        default_kind: str,
        index: int,
    ) -> Listing | None:
        def get(field: str) -> str:
            # 칸 이름은 하나여도 되고 여러 후보를 줘도 된다.
            # (한국어 표·일본어 표를 같은 설정으로 받기 위해)
            column = field_map.get(field)
            if not column:
                return ""
            for name in ([column] if isinstance(column, str) else column):
                value = row.get(name)
                if value not in (None, ""):
                    return str(value).strip()
            return ""

        price = parse_price_to_yen(get("price"))
        address = get("address")
        if price is None and not address:
            return None  # 가격도 주소도 없으면 매물로 볼 수 없다

        built_year, built_month = parse_built(get("built"))
        station_text = get("station")

        # 都道府県·市区町村 컬럼이 없는 피드가 흔하다. 추이는 구 이름으로 묶으므로
        # 없으면 주소에서 뽑아낸다 — 여기서 비면 그 물건은 추이에 안 잡힌다.
        prefecture, city = get("prefecture"), get("city")
        if not city:
            derived_pref, derived_city = split_address(address)
            prefecture = prefecture or derived_pref
            city = derived_city

        return Listing(
            source=self.key,
            source_id=get("source_id") or f"row{index}",
            url=get("url"),
            title=get("title") or address,
            kind=get("kind") or default_kind,
            stage=parse_stage(get("stage")),
            price_yen=price,
            prefecture=prefecture,
            city=city,
            sub_area=get("sub_area"),
            address=address,
            stations=(
                [
                    Station(
                        line=get("line"),
                        name=station_text,
                        walk_minutes=parse_walk_minutes(get("walk") or station_text),
                    )
                ]
                if station_text or get("line")
                else []
            ),
            area_m2=parse_area_m2(get("area_m2")),
            land_area_m2=parse_area_m2(get("land_area_m2")),
            building_area_m2=parse_area_m2(get("building_area_m2")),
            layout=get("layout"),
            built_year=built_year,
            built_month=built_month,
            floor=_to_int(get("floor")),
            total_floors=_to_int(get("total_floors")),
            total_units=_to_int(get("total_units")),   # 200세대 필터가 이 값을 본다
            structure=get("structure"),
            management_fee_yen=parse_price_to_yen(get("management_fee")),
            repair_reserve_yen=parse_price_to_yen(get("repair_reserve")),
            image_url=get("image_url"),
            agency=get("agency"),
            listed_on=get("listed_on"),
        )


def _to_int(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None
