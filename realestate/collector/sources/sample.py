"""오프라인 데모용 가상 매물 소스.

실제 데이터 경로(공식 API / 라이선스 피드)가 붙기 전까지 파이프라인 전체
(수집 → 차분 → 시세추이 → 뷰어)를 돌려보기 위한 것이다. 날짜를 시드로 쓰므로
하루가 지나면 실제로 몇 건이 新着으로 잡히고 몇 건은 掲載終了로 빠진다.

⚠ 여기서 나오는 물건과 가격은 전부 **가상**이다. 실재 물건도, 실제 도쿄
   시세도 아니다. 이 데이터로 만든 그래프에는 synthetic 플래그가 붙고,
   뷰어는 그걸 보고 경고 배지와 워터마크를 띄운다.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from ..schema import KIND_MANSION, STAGE_NEW, STAGE_USED, Listing, Station
from .base import Source

_EPOCH = date(2020, 1, 1)
_ACTIVE_WINDOW_DAYS = 180   # 현재 게재중 후보를 찾는 범위
_HISTORY_DAYS = 365 * 5     # 추이 데모용으로 되돌아볼 범위

# (구, 도도부현, 기준 坪単価(만엔), 출현 가중치) — 가격 서열만 그럴듯하게 둔 가상값
_WARDS = [
    ("港区",     "東京都", 550, 12),
    ("千代田区", "東京都", 480, 8),
    ("渋谷区",   "東京都", 500, 11),
    ("中央区",   "東京都", 420, 12),
    ("新宿区",   "東京都", 380, 11),
    ("文京区",   "東京都", 370, 10),
    ("江東区",   "東京都", 300, 13),
    # 주변부 — 목록에 다양성만 주는 용도, 추이 대상은 아니다
    ("品川区",   "東京都", 350, 4),
    ("目黒区",   "東京都", 400, 4),
    ("豊島区",   "東京都", 330, 3),
]

_LINES = [
    ("JR山手線", ["渋谷", "恵比寿", "目黒", "五反田", "田町", "巣鴨", "駒込", "高田馬場"]),
    ("東京メトロ丸ノ内線", ["新宿三丁目", "中野坂上", "本郷三丁目", "茗荷谷", "四谷"]),
    ("東京メトロ東西線", ["門前仲町", "早稲田", "落合", "木場", "南砂町"]),
    ("都営大江戸線", ["麻布十番", "六本木", "中井", "月島", "清澄白河"]),
    ("東急東横線", ["中目黒", "学芸大学", "都立大学", "代官山"]),
    ("東京メトロ有楽町線", ["豊洲", "月島", "護国寺", "江戸川橋"]),
    ("東京メトロ南北線", ["白金台", "麻布十番", "東大前", "本駒込"]),
]

_BRANDS = [
    "パークホームズ", "ブリリア", "プラウド", "ザ・パークハウス", "シティタワー",
    "ライオンズ", "クレヴィア", "オープンレジデンシア", "グランドメゾン",
    "パークコート", "ドゥ・トゥール", "アトラス", "サンウッド",
]

_LAYOUTS = ["1K", "1LDK", "2LDK", "2LDK+S", "3LDK", "3LDK+S", "4LDK"]

_FEATURES = [
    "リノベーション済", "ペット可", "南向き", "角部屋", "オートロック",
    "宅配ボックス", "駐車場空有", "眺望良好", "床暖房", "即入居可",
    "２面採光", "コンシェルジュ", "内廊下", "免震構造",
]

_AGENCIES = [
    "みらい不動産販売", "東京シティホーム", "リブレ住宅販売",
    "スカイライン不動産", "コンフォート住販",
]

_ANNUAL_DRIFT = 0.055   # 연 5.5% 상승 가정 (가상)
_NEW_BUILD_RATIO = 0.22  # 게재 중 新築分譲 비중
_NEW_BUILD_PREMIUM = (1.20, 1.38)  # 新築는 같은 입지 中古 대비 이만큼 비싸게


class SampleSource(Source):
    key = "sample"
    name = "サンプル（架空データ）"
    basis = "생성된 가상 데이터. 실재 물건·실제 시세 아님. 파이프라인 검증 전용."

    # ------------------------------------------------------------------
    def fetch(self, config: dict[str, Any]) -> list[Listing]:
        """현재 게재중인 물건."""
        target = (date.today() - _EPOCH).days
        out: list[Listing] = []
        for day in range(target - _ACTIVE_WINDOW_DAYS, target + 1):
            for listing, duration in self._posted_on(day):
                if day + duration <= target:
                    continue
                self._apply_price_cut(listing, day, target)
                out.append(listing)
        return out

    def history(self, config: dict[str, Any], days: int = _HISTORY_DAYS) -> list[Listing]:
        """추이 데모용 — 게재종료분 포함, 과거 전체."""
        target = (date.today() - _EPOCH).days
        out: list[Listing] = []
        for day in range(max(0, target - days), target + 1):
            for listing, _duration in self._posted_on(day):
                out.append(listing)
        return out

    # ------------------------------------------------------------------
    def _posted_on(self, day: int) -> list[tuple[Listing, int]]:
        """해당 날짜 게재분. 날짜만으로 결정되므로 몇 번 돌려도 같다."""
        rng = random.Random(f"tokyo-sample-{day}")
        # 하루 평균 5건 정도는 나와야 (구 × 단계 × 분기) 칸마다 중앙값이
        # 표본 몇 개에 휘둘리지 않는다.
        count = rng.choices([2, 3, 4, 5, 6, 7, 8], weights=[8, 14, 20, 20, 16, 12, 10])[0]
        return [
            self._make(
                rng, day, seq, STAGE_NEW if rng.random() < _NEW_BUILD_RATIO else STAGE_USED
            )
            for seq in range(count)
        ]

    def _make(self, rng: random.Random, day: int, seq: int, stage: str) -> tuple[Listing, int]:
        city, pref, base_tsubo, _weight = rng.choices(
            _WARDS, weights=[w[3] for w in _WARDS]
        )[0]
        line, stations = rng.choice(_LINES)
        station = rng.choice(stations)
        posted = _EPOCH + timedelta(days=day)

        is_new = stage == STAGE_NEW

        # 총 세대수 — 大規模(200세대 이상) 비중은 新築 쪽이 높다
        large_ratio = 0.55 if is_new else 0.34
        if rng.random() < large_ratio:
            total_units = rng.randrange(200, 900, 10)
        else:
            total_units = rng.randrange(14, 200, 2)

        area = round(rng.uniform(28, 110), 2)
        layout = rng.choice(_LAYOUTS)
        total_floors = rng.randint(5, 45) if total_units >= 200 else rng.randint(3, 15)
        floor = rng.randint(1, total_floors)
        # 新築は竣工年＝販売年（〜翌年）。中古は築年数ぶん割り引く。
        built_year = posted.year + rng.choice([0, 0, 1]) if is_new else rng.randint(1988, max(1989, posted.year - 1))

        # 坪単価 = 구 기준가 × 연도 드리프트 × 築年 감가 × 규모/신축 프리미엄 × 개별 편차
        drift = (1 + _ANNUAL_DRIFT) ** (posted.year + posted.month / 12 - 2020)
        age_factor = 1.0 if is_new else max(0.5, 1.0 - (posted.year - built_year) * 0.011)
        scale_bonus = 1.06 if total_units >= 200 else 1.0
        stage_bonus = rng.uniform(*_NEW_BUILD_PREMIUM) if is_new else 1.0
        tsubo_price = (
            base_tsubo * drift * age_factor * scale_bonus * stage_bonus * rng.uniform(0.82, 1.2)
        )

        price_man = round(tsubo_price * (area / 3.30578) / 10) * 10
        price_man = max(price_man, 900)

        brand = rng.choice(_BRANDS)
        title = f"{brand}{station}" if rng.random() < 0.55 else f"{brand}{city.rstrip('区')}"
        if is_new:
            title = f"（新築）{title}"

        listing = Listing(
            source=self.key,
            source_id=f"{day}-{seq:02d}",
            url=f"https://example.invalid/listing/{day}-{seq:02d}",
            title=title,
            kind=KIND_MANSION,
            stage=stage,
            price_yen=int(price_man * 10_000),
            prefecture=pref,
            city=city,
            address=f"{pref}{city}{rng.choice('一二三四五六七')}丁目{rng.randint(1, 30)}-{rng.randint(1, 20)}",
            stations=[Station(line=line, name=station, walk_minutes=rng.randint(1, 15))],
            area_m2=area,
            layout=layout,
            built_year=built_year,
            built_month=rng.randint(1, 12),
            floor=floor,
            total_floors=total_floors,
            total_units=total_units,
            structure=rng.choice(["RC造", "SRC造"]),
            management_fee_yen=rng.randrange(8_000, 34_000, 500),
            repair_reserve_yen=rng.randrange(5_000, 30_000, 500),
            features=rng.sample(_FEATURES, k=rng.randint(2, 5)),
            agency=rng.choice(_AGENCIES),
            listed_on=posted.isoformat(),
        )

        # 新築分譲は完売まで長く出続ける
        duration = rng.randint(90, 400) if is_new else rng.randint(21, 150)
        return listing, duration

    def _apply_price_cut(self, listing: Listing, posted_day: int, today: int) -> None:
        """오래 남은 中古 물건에는 価格変更(대개 인하)이 들어간다."""
        if listing.stage == STAGE_NEW:
            return  # 分譲価格は原則据え置き
        rng = random.Random(f"cut-{listing.source_id}")
        if listing.price_yen is None or today - posted_day < rng.randint(30, 90):
            return
        if rng.random() > 0.55:
            return
        listing.price_yen = int(listing.price_yen * rng.uniform(0.90, 0.985) / 100_000) * 100_000
        if "価格変更あり" not in listing.features:
            listing.features.append("価格変更あり")
