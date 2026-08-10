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
    sub_area: str = ""   # 地区名 (六本木·豊洲 등). 구보다 한 단계 아래
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
    """「4,980万円」「1億2000万円」「12800만엔」→ 엔 정수.

    한국어로 적은 표(만엔·억엔)도 그대로 읽는다.
    """
    if not text:
        return None
    s = text.replace(",", "").replace(" ", "")
    total = 0
    matched = False

    oku = re.search(r"([\d.]+)\s*[億억]", s)
    if oku:
        total += int(float(oku.group(1)) * 100_000_000)
        matched = True

    man = re.search(r"([\d.]+)\s*(?:万|만)", s)
    if man:
        total += int(float(man.group(1)) * _MAN_YEN)
        matched = True

    if not matched:
        bare = re.search(r"(\d+)", s)
        if not bare:
            return None
        total = int(bare.group(1))
        # 단위 없이 「9800」처럼 적는 경우, 업계 관행상 万円을 뜻한다.
        # 그대로 엔으로 읽으면 1만 배 틀린 값이 조용히 들어간다.
        if total < 1_000_000:
            total *= _MAN_YEN

    return total or None


def parse_area_m2(text: str) -> float | None:
    """「72.45m2」「72.45㎡」→ float."""
    if not text:
        return None
    m = re.search(r"([\d.]+)\s*(?:m\s*2|㎡|m²|평방미터)", text.replace(",", ""))
    if not m:
        m = re.search(r"([\d.]+)", text.replace(",", ""))
    return float(m.group(1)) if m else None


def parse_built(text: str) -> tuple[int | None, int | None]:
    """「1998年3月」「1998년 3월」「1998-03」→ (연, 월)."""
    if not text:
        return None, None
    year = re.search(r"(\d{4})\s*[年년]", text)
    month = re.search(r"[年년]\s*(\d{1,2})\s*[月월]", text)
    if not year:
        # 「1998-03」「1998/3」 같은 표기도 받아준다
        plain = re.match(r"\s*(\d{4})[-/.](\d{1,2})", text)
        if plain:
            return int(plain.group(1)), int(plain.group(2))
        bare = re.search(r"(\d{4})", text)
        return (int(bare.group(1)) if bare else None), None
    return int(year.group(1)), int(month.group(1)) if month else None


def parse_walk_minutes(text: str) -> int | None:
    """「徒歩8分」「도보 8분」「8」→ 8."""
    if not text:
        return None
    m = re.search(r"(?:徒歩|도보)\s*(\d+)\s*[分분]?", text)
    if m:
        return int(m.group(1))
    stripped = text.strip()
    return int(stripped) if stripped.isdigit() else None


#: 한국어로 번역된 페이지도 그대로 읽는다 (크롬 자동번역 결과를 붙여넣는 경우)
WARD_KO_TO_JA = {
    "지요다구": "千代田区", "주오구": "中央区", "미나토구": "港区",
    "신주쿠구": "新宿区", "분쿄구": "文京区", "고토구": "江東区",
    "시부야구": "渋谷区", "시나가와구": "品川区", "메구로구": "目黒区",
    "도시마구": "豊島区", "다이토구": "台東区", "스미다구": "墨田区",
}

_PREF_RE = re.compile(r"^\s*(東京都|도쿄도|北海道|京都府|大阪府|.{2,3}県)")
# 政令指定都市의 「○○市△△区」를 먼저 잡아야 한다. 그러지 않으면 "横浜市"에서 끊긴다.
_CITY_RE = re.compile(r"(.+?郡.+?[町村]|.+?市.+?区|.+?[市区町村])")


def parse_stage(text: str, default: str = STAGE_USED) -> str:
    """「新築」「中古」「신축」「중고」 등의 표기를 stage 값으로.

    한국어·일본어·영어 어느 쪽으로 적어도 같게 읽는다.
    """
    if not text:
        return default
    lowered = text.strip().lower()
    if lowered in ("new", "shinchiku") or any(k in text for k in ("新築", "分譲", "신축", "분양")):
        return STAGE_NEW
    if lowered in ("used", "chuko") or any(k in text for k in ("中古", "중고")):
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
        pref = "東京都" if match.group(1) == "도쿄도" else match.group(1)
        text = text[match.end():].lstrip()

    # 한국어 표기를 먼저 본다 — 「주오구」는 아래 한자 규칙에 안 걸린다
    for ko, ja in WARD_KO_TO_JA.items():
        if text.startswith(ko):
            return pref or "東京都", ja

    city_match = _CITY_RE.match(text)
    return pref, city_match.group(1) if city_match else ""


def dedupe(listings: Iterable[Listing]) -> list[Listing]:
    """같은 물건이 여러 중개사·포털에 중복 게재된 것을 하나로 접는다.

    주소 문자열만으로는 못 접는다. 실제로 같은 방인데 한쪽은
    「日本橋箱崎町29-1」, 다른 쪽은 「日本橋箱崎町」로 적는 일이 흔하다.
    그래서 (구 + 전용면적 + 간취り + 축년 + 가격) 이 모두 같으면 같은 방으로 본다.
    가격까지 같아야 접으므로, 같은 건물의 다른 호실이 잘못 합쳐지지는 않는다.

    먼저 온 쪽을 남기고, 접힌 쪽의 출처는 also:소스 태그로 남긴다.
    """
    out: list[Listing] = []
    seen: dict[tuple, Listing] = {}

    for item in listings:
        area = item.area_m2 or item.building_area_m2 or item.land_area_m2
        sig = (
            item.city.strip(),
            round(area, 1) if area else None,
            item.layout.strip(),
            item.built_year,
            item.price_yen,
            item.floor,
        )
        # 구·면적·간취り 가 다 있어야 판단할 수 있다. 하나라도 비면 접지 않는다.
        if not (sig[0] and sig[1] and sig[2]):
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
            # 원문 링크가 없던 쪽이면 채워 준다
            if not prior.url and item.url:
                prior.url = item.url

    return out
