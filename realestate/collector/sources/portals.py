"""주요 일본 부동산 포털 어댑터 (SUUMO / LIFULL HOME'S / at home / 不動産ジャパン).

■ 먼저 알아야 할 사실
   이 네 곳 중 **제3자에게 물건 목록을 공개 API로 내주는 곳은 없다.**
   그래서 여기 있는 어댑터들은 '접근 수단'을 스스로 만들어내지 않는다.
   대신, 이용자가 아래 중 하나의 **정당한 접근 경로**를 확보했을 때
   그것을 꽂아 넣는 자리를 제공한다.

     access_mode = "api"   파트너/제휴 계약으로 받은 API 엔드포인트 + 키
     access_mode = "feed"  掲載企業·加盟店으로서 받는 물건 데이터 파일(CSV/JSON)
     access_mode = "off"   (기본값) 비활성

   access_mode 를 설정하지 않으면 어댑터는 그냥 건너뛴다. 무단 크롤링
   코드는 여기 없다 — 각 포털 이용약관이 자동수집을 금지하고 있고,
   그건 어댑터를 잘 짜서 피할 수 있는 문제가 아니다.

■ 그럼 실제로 어떻게 데이터를 얻나
   ① 宅建業免許 + REINS(ATBB) — 중고 유통물건의 원본. 업자만 접근 가능.
   ② 각 포털의 掲載企業 계약 — 자사 물건을 올리는 쪽. 데이터 반출 조건은 계약별.
   ③ 데이터 벤더(東京カンテイ, 不動産経済研究所 등) — 신축 분양가 시계열은
      사실상 여기가 유일한 상용 경로다.
   ④ 国土交通省 不動産情報ライブラリ — 성약가. 무료·공식. market.py 참조.

   ①~③ 중 무엇을 확보하든, 결과물은 결국 '행의 집합'이므로 이 어댑터
   (또는 feed.py)로 흘려보내면 나머지 파이프라인은 그대로 동작한다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..schema import (
    KIND_MANSION,
    STAGE_NEW,
    STAGE_USED,
    Listing,
    Station,
    parse_area_m2,
    parse_built,
    parse_price_to_yen,
    parse_walk_minutes,
)
from .base import Source, SourceError
from .feed import FeedSource

_TIMEOUT = 60


class PortalSource(Source):
    """포털 공통 뼈대. 하위 클래스는 메타데이터만 채운다."""

    home_url: str = ""
    operator: str = ""
    #: 이 포털에서 데이터를 받을 수 있는 현실적인 경로 설명
    access_note: str = ""

    # ------------------------------------------------------------------
    def available(self, config: dict[str, Any]) -> tuple[bool, str]:
        cfg = self._cfg(config)
        mode = str(cfg.get("access_mode", "off")).lower()

        if not cfg.get("enabled") or mode == "off":
            return False, f"{self.name}: 비활성 (access_mode=off)"

        if not cfg.get("basis"):
            # 어떤 근거로 이 데이터를 쓰는지 적지 않으면 돌리지 않는다.
            return False, f"{self.name}: sources.{self.key}.basis 에 이용 근거 필요"

        if mode == "api":
            if not cfg.get("endpoint"):
                return False, f"{self.name}: access_mode=api 인데 endpoint 없음"
            if not cfg.get("api_key_env"):
                return False, f"{self.name}: api_key_env 지정 필요"
            return True, ""

        if mode == "feed":
            if not cfg.get("location"):
                return False, f"{self.name}: access_mode=feed 인데 location 없음"
            return True, ""

        return False, f"{self.name}: 알 수 없는 access_mode={mode}"

    # ------------------------------------------------------------------
    def fetch(self, config: dict[str, Any]) -> list[Listing]:
        cfg = self._cfg(config)
        mode = str(cfg.get("access_mode", "off")).lower()

        if mode == "feed":
            # 포털 설정을 feed 어댑터가 이해하는 모양으로 넘겨 재사용한다.
            delegate = FeedSource()
            wrapped = {"sources": {"feed": {**cfg, "enabled": True}}}
            listings = delegate.fetch(wrapped)
            for item in listings:
                item.source = self.key
            return listings

        if mode == "api":
            return self._fetch_api(cfg)

        raise SourceError(f"{self.name}: 사용할 수 없는 access_mode={mode}")

    # ------------------------------------------------------------------
    def _fetch_api(self, cfg: dict[str, Any]) -> list[Listing]:
        import os

        api_key = os.environ.get(str(cfg["api_key_env"]), "").strip()
        if not api_key:
            raise SourceError(f"{self.name}: 환경변수 {cfg['api_key_env']} 가 비어 있음")

        params = dict(cfg.get("params", {}))
        url = f"{cfg['endpoint']}?{urllib.parse.urlencode(params)}" if params else str(cfg["endpoint"])

        headers = {"Accept": "application/json"}
        header_name = str(cfg.get("api_key_header", "Authorization"))
        template = str(cfg.get("api_key_format", "Bearer {key}"))
        headers[header_name] = template.format(key=api_key)
        headers.update(cfg.get("headers", {}))

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode(cfg.get("encoding", "utf-8")))
        except urllib.error.HTTPError as exc:
            raise SourceError(f"{self.name}: HTTP {exc.code} — {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"{self.name}: 요청 실패 — {exc}") from exc

        rows: Any = payload
        for part in filter(None, str(cfg.get("json_path", "")).split(".")):
            rows = rows.get(part, []) if isinstance(rows, dict) else []
        if not isinstance(rows, list):
            raise SourceError(f"{self.name}: json_path 가 배열을 가리키지 않음")

        field_map = cfg.get("field_map", {})
        out: list[Listing] = []
        for index, row in enumerate(rows):
            listing = self._normalize(row, field_map, index)
            if listing is not None:
                out.append(listing)
        return out

    # ------------------------------------------------------------------
    def _normalize(self, row: dict[str, Any], field_map: dict[str, str], index: int) -> Listing | None:
        def get(field: str) -> str:
            column = field_map.get(field, field)
            value = row.get(column, "")
            return "" if value is None else str(value).strip()

        price = parse_price_to_yen(get("price"))
        address = get("address")
        if price is None and not address:
            return None

        built_year, built_month = parse_built(get("built"))
        station = get("station")
        raw_stage = get("stage").lower()
        stage = STAGE_NEW if raw_stage in ("new", "新築", "新築分譲") else STAGE_USED

        return Listing(
            source=self.key,
            source_id=get("source_id") or f"row{index}",
            url=get("url"),
            title=get("title") or address,
            kind=get("kind") or KIND_MANSION,
            stage=stage,
            price_yen=price,
            prefecture=get("prefecture"),
            city=get("city"),
            address=address,
            stations=(
                [Station(line=get("line"), name=station, walk_minutes=parse_walk_minutes(get("walk") or station))]
                if station or get("line")
                else []
            ),
            area_m2=parse_area_m2(get("area_m2")),
            layout=get("layout"),
            built_year=built_year,
            built_month=built_month,
            floor=_int(get("floor")),
            total_floors=_int(get("total_floors")),
            total_units=_int(get("total_units")),
            structure=get("structure"),
            management_fee_yen=parse_price_to_yen(get("management_fee")),
            repair_reserve_yen=parse_price_to_yen(get("repair_reserve")),
            image_url=get("image_url"),
            agency=get("agency") or self.name,
            listed_on=get("listed_on"),
        )

    def _cfg(self, config: dict[str, Any]) -> dict[str, Any]:
        return config.get("sources", {}).get(self.key, {})

    def describe(self) -> dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "operator": self.operator,
            "home_url": self.home_url,
            "access_note": self.access_note,
        }


# ----------------------------------------------------------------------


class SuumoSource(PortalSource):
    key = "suumo"
    name = "SUUMO"
    operator = "株式会社リクルート"
    home_url = "https://suumo.jp/"
    basis = "掲載企業契約 또는 제휴 API 계약이 있는 경우에만."
    access_note = (
        "제3자용 공개 물건 API 없음. 利用規約이 자동수집을 금지한다. "
        "실무 경로: 掲載企業(불동산회사)로서 리쿠르트와 계약하고 물건 데이터를 "
        "주고받거나, 제휴 API 계약을 별도로 맺는 것."
    )


class HomesSource(PortalSource):
    key = "homes"
    name = "LIFULL HOME'S"
    operator = "株式会社LIFULL"
    home_url = "https://www.homes.co.jp/"
    basis = "LIFULL 과의 데이터 이용 계약이 있는 경우에만."
    access_note = (
        "과거 공개 API(HOME'S API)는 종료. 현재는 加盟店/파트너 계약 경로. "
        "연구 목적이라면 'LIFULL HOME'S データセット'(情報学研究データリポジトリ 경유) "
        "신청이 별도로 존재한다 — 다만 연구 한정이고 실시간이 아니다."
    )


class AtHomeSource(PortalSource):
    key = "athome"
    name = "アットホーム (at home)"
    operator = "アットホーム株式会社"
    home_url = "https://www.athome.co.jp/"
    basis = "アットホーム 加盟店 계약이 있는 경우에만."
    access_note = (
        "加盟店(부동산회사) 대상 물件データ 연携 서비스가 있다. "
        "일반 이용자용 공개 API는 없음."
    )


class FudousanJapanSource(PortalSource):
    key = "fudousan_japan"
    name = "不動産ジャパン"
    operator = "公益財団法人 不動産流通推進センター"
    home_url = "https://www.fudousan.or.jp/"
    basis = "센터가 정한 이용 조건 범위 내."
    access_note = (
        "REINS 등록 물건 중 공개 가능분을 일반에 보여주는 사이트. "
        "영리 목적 대량 취득은 별도 협의 대상이며, 공개 API는 제공하지 않는다."
    )


PORTALS: tuple[PortalSource, ...] = (
    SuumoSource(),
    HomesSource(),
    AtHomeSource(),
    FudousanJapanSource(),
)


def _int(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None
