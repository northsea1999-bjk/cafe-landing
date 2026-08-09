"""중고 매물 통합 스키마.

포털마다 필드 이름과 단위가 전부 다르기 때문에, 각 소스 어댑터는 원본을
이 Listing 하나로 정규화해서 돌려준다. 수집기·비교기·웹 뷰어는 오직
이 스키마만 안다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

# 물건 종별. 포털 표기가 제각각이라 여기로 모은다.
KIND_MANSION = "mansion"  # 中古マンション
KIND_HOUSE = "house"      # 中古一戸建て
KIND_LAND = "land"        # 土地

KINDS = (KIND_MANSION, KIND_HOUSE, KIND_LAND)

KIND_LABELS_JA = {
    KIND_MANSION: "マンション",
    KIND_HOUSE: "一戸建て",
    KIND_LAND: "土地",
}

# 유통 단계. 중고 호가와 신축 분양가는 가격 수준이 구조적으로 다르므로
# 절대 같은 계열로 섞지 않고, 추이도 따로 집계한다.
STAGE_USED = "used"   # 中古（売出）
STAGE_NEW = "new"     # 新築分譲

STAGES = (STAGE_USED, STAGE_NEW)

STAGE_LABELS_JA = {
    STAGE_USED: "中古",
    STAGE_NEW: "新築分譲",
}

_MAN_YEN = 10_000


@dataclass
class Station:
    """最寄り駅. 도보 분은 포털 표기(徒歩N分)를 그대로 정수로."""

    line: str = ""
    name: str = ""
    walk_minutes: int | None = None

    def label(self) -> str:
        parts = [p for p in (self.line, self.name) if p]
        base = " ".join(parts)
        if self.walk_minutes is not None:
            return f"{base} 徒歩{self.walk_minutes}分"
        return base


@dataclass
class Listing:
    """정규화된 매물 1건."""

    # --- 식별 ---
    source: str                      # 어댑터 키 (예: "sample", "reinfolib")
    source_id: str                   # 소스 내부의 물건 ID
    url: str = ""                    # 원본 상세 페이지

    # --- 기본 ---
    title: str = ""
    kind: str = KIND_MANSION
    stage: str = STAGE_USED          # 中古 / 新築分譲
    price_yen: int | None = None     # 엔 단위 정수. 万円 표기는 여기서 환산해 저장

    # --- 위치 ---
    prefecture: str = ""
    city: str = ""
    address: str = ""
    stations: list[Station] = field(default_factory=list)

    # --- 규모 ---
    area_m2: float | None = None           # 専有面積 (마ンション)
    land_area_m2: float | None = None      # 土地面積 (一戸建て・土地)
    building_area_m2: float | None = None  # 建物面積 (一戸建て)
    layout: str = ""                       # 間取り (3LDK 등)

    # --- 건물 ---
    built_year: int | None = None
    built_month: int | None = None
    floor: int | None = None
    total_floors: int | None = None
    total_units: int | None = None         # 総戸数. 大規模マンション 판별의 기준
    structure: str = ""                    # RC造 등

    # --- 비용 ---
    management_fee_yen: int | None = None      # 管理費 (월)
    repair_reserve_yen: int | None = None      # 修繕積立金 (월)

    # --- 부가 ---
    image_url: str = ""
    features: list[str] = field(default_factory=list)
    agency: str = ""
    listed_on: str = ""   # 情報公開日 (YYYY-MM-DD). 피드가 주면 그대로, 없으면 빈 값

    # --- 수집 메타 (store가 채운다) ---
    first_seen: str = ""
    last_seen: str = ""
    price_history: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def key(self) -> str:
        """스냅샷 비교용 안정 키. 소스가 ID를 안 주면 내용으로 해시한다."""
        if self.source_id:
            return f"{self.source}:{self.source_id}"
        seed = "|".join(
            str(x) for x in (self.title, self.address, self.area_m2, self.layout, self.built_year)
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
        return f"{self.source}:h{digest}"

    @property
    def price_man(self) -> float | None:
        """万円 환산. 표시용."""
        if self.price_yen is None:
            return None
        return round(self.price_yen / _MAN_YEN, 1)

    @property
    def unit_price_man_per_tsubo(self) -> float | None:
        """坪単価(万円). 면적이 없으면 None."""
        area = self.area_m2 or self.building_area_m2 or self.land_area_m2
        if not area or self.price_yen is None:
            return None
        tsubo = area / 3.30578
        if tsubo <= 0:
            return None
        return round(self.price_yen / _MAN_YEN / tsubo, 1)

    @property
    def building_age(self) -> int | None:
        """築年数. 기준은 수집 연도가 아니라 호출 시점의 연도."""
        if self.built_year is None:
            return None
        from datetime import date

        return max(0, date.today().year - self.built_year)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # 뷰어가 계산하지 않아도 되도록 파생값을 함께 굽는다.
        data["key"] = self.key
        data["price_man"] = self.price_man
        data["unit_price_man_per_tsubo"] = self.unit_price_man_per_tsubo
        data["building_age"] = self.building_age
        data["kind_label"] = KIND_LABELS_JA.get(self.kind, self.kind)
        data["stage_label"] = STAGE_LABELS_JA.get(self.stage, self.stage)
        data["station_labels"] = [s.label() for s in self.stations if s.label()]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Listing":
        """to_dict() 결과에서 되살린다. 파생 필드는 무시."""
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["stations"] = [
            Station(**s) if isinstance(s, dict) else s for s in data.get("stations", [])
        ]
        return cls(**kwargs)


# ----------------------------------------------------------------------
# 파싱 헬퍼 — 포털 텍스트를 스키마 값으로


def parse_price_to_yen(text: str) -> int | None:
    """「4,980万円」「1億2000万円」→ 엔 정수."""
    if not text:
        return None
    s = text.replace(",", "").replace(" ", "")
    total = 0
    matched = False

    oku = re.search(r"([\d.]+)億", s)
    if oku:
        total += int(float(oku.group(1)) * 100_000_000)
        matched = True

    man = re.search(r"([\d.]+)万", s)
    if man:
        total += int(float(man.group(1)) * _MAN_YEN)
        matched = True

    if not matched:
        bare = re.search(r"(\d+)", s)
        if not bare:
            return None
        total = int(bare.group(1))

    return total or None


def parse_area_m2(text: str) -> float | None:
    """「72.45m2」「72.45㎡」→ float."""
    if not text:
        return None
    m = re.search(r"([\d.]+)\s*(?:m2|㎡|m²)", text.replace(",", ""))
    if not m:
        m = re.search(r"([\d.]+)", text.replace(",", ""))
    return float(m.group(1)) if m else None


def parse_built(text: str) -> tuple[int | None, int | None]:
    """「1998年3月」「築1998年」→ (연, 월)."""
    if not text:
        return None, None
    year = re.search(r"(\d{4})\s*年", text)
    month = re.search(r"年\s*(\d{1,2})\s*月", text)
    return (
        int(year.group(1)) if year else None,
        int(month.group(1)) if month else None,
    )


def parse_walk_minutes(text: str) -> int | None:
    """「徒歩8分」→ 8."""
    if not text:
        return None
    m = re.search(r"徒歩\s*(\d+)\s*分", text)
    return int(m.group(1)) if m else None


_PREF_RE = re.compile(r"^\s*(東京都|北海道|京都府|大阪府|.{2,3}県)")
# 政令指定都市의 「○○市△△区」를 먼저 잡아야 한다. 그러지 않으면 "横浜市"에서 끊긴다.
_CITY_RE = re.compile(r"(.+?郡.+?[町村]|.+?市.+?区|.+?[市区町村])")


def parse_stage(text: str, default: str = STAGE_USED) -> str:
    """「新築」「中古」「新築分譲」 등의 표기를 stage 값으로."""
    if not text:
        return default
    lowered = text.strip().lower()
    if lowered in ("new", "shinchiku") or "新築" in text or "分譲" in text:
        return STAGE_NEW
    if lowered in ("used", "chuko") or "中古" in text:
        return STAGE_USED
    return default


def split_address(address: str) -> tuple[str, str]:
    """「東京都港区六本木3-1-1」→ ("東京都", "港区").

    피드가 都道府県·市区町村 컬럼을 따로 주지 않는 경우가 흔한데, 추이 집계는
    구 이름으로 묶으므로 주소에서 뽑아낼 수 있어야 한다.
    """
    if not address:
        return "", ""
    text = address.strip()

    pref = ""
    match = _PREF_RE.match(text)
    if match:
        pref = match.group(1)
        text = text[match.end():]

    city_match = _CITY_RE.match(text)
    return pref, city_match.group(1) if city_match else ""


def dedupe(listings: Iterable[Listing]) -> list[Listing]:
    """같은 물건이 여러 포털에 중복 게재되는 경우를 하나로 접는다.

    포털 간 ID는 공유되지 않으므로 (주소 + 면적 + 간취り + 층) 조합으로 본다.
    이 조합이 같으면 같은 방으로 간주하고, 먼저 온 쪽(= 수집 순서상 우선
    소스)을 남긴 뒤 나머지는 also_on 에 출처만 기록한다.
    """
    out: list[Listing] = []
    seen: dict[tuple, Listing] = {}

    for item in listings:
        area = item.area_m2 or item.building_area_m2 or item.land_area_m2
        sig = (
            item.address.strip(),
            round(area, 1) if area else None,
            item.layout.strip(),
            item.floor,
        )
        # 주소가 비면 신뢰할 수 없으므로 접지 않는다.
        if not sig[0]:
            out.append(item)
            continue

        prior = seen.get(sig)
        if prior is None:
            seen[sig] = item
            out.append(item)
        else:
            tag = f"also:{item.source}"
            if tag not in prior.features:
                prior.features.append(tag)

    return out
