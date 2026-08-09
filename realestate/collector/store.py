"""스냅샷 저장과 일별 차분.

"바로바로 업데이트"의 실체는 결국 이것이다 — 주기적으로 전체를 긁고,
직전 스냅샷과 비교해서 新着 / 価格変更 / 掲載終了 를 뽑아낸다.
포털은 push를 주지 않으므로 polling + diff 외의 방법이 없다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .schema import Listing


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


@dataclass
class PriceChange:
    listing: Listing
    old_price_yen: int
    new_price_yen: int

    @property
    def delta_yen(self) -> int:
        return self.new_price_yen - self.old_price_yen

    @property
    def delta_pct(self) -> float:
        if not self.old_price_yen:
            return 0.0
        return round(self.delta_yen / self.old_price_yen * 100, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing": self.listing.to_dict(),
            "old_price_yen": self.old_price_yen,
            "new_price_yen": self.new_price_yen,
            "delta_yen": self.delta_yen,
            "delta_pct": self.delta_pct,
        }


@dataclass
class Changes:
    new: list[Listing] = field(default_factory=list)
    price_changed: list[PriceChange] = field(default_factory=list)
    removed: list[Listing] = field(default_factory=list)
    unchanged_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.new or self.price_changed or self.removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": _today(),
            "generated_at": _now_iso(),
            "summary": {
                "new": len(self.new),
                "price_changed": len(self.price_changed),
                "removed": len(self.removed),
                "unchanged": self.unchanged_count,
            },
            "new": [x.to_dict() for x in self.new],
            "price_changed": [x.to_dict() for x in self.price_changed],
            "removed": [x.to_dict() for x in self.removed],
        }


class Store:
    """data/ 아래에 스냅샷과 차분 이력을 둔다."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.listings_path = self.root / "listings.json"
        self.changes_dir = self.root / "changes"
        self.latest_changes_path = self.root / "latest-changes.json"
        # 추이의 원천. 스냅샷과 달리 한 번 기록한 관측은 지우지 않는다.
        self.observations_path = self.root / "observations.jsonl"

    # ------------------------------------------------------------------
    def load_previous(self) -> dict[str, Listing]:
        if not self.listings_path.exists():
            return {}
        try:
            raw = json.loads(self.listings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 스냅샷이 깨졌으면 전량 신규로 취급하는 편이 조용히 틀리는 것보다 낫다.
            return {}
        result: dict[str, Listing] = {}
        for item in raw.get("listings", []):
            listing = Listing.from_dict(item)
            result[listing.key] = listing
        return result

    # ------------------------------------------------------------------
    def diff(self, previous: dict[str, Listing], current: Iterable[Listing]) -> tuple[Changes, list[Listing]]:
        """차분과 '저장할 최종 목록'을 함께 돌려준다.

        최종 목록에는 first_seen / price_history 가 이월되어 들어간다.
        """
        changes = Changes()
        merged: list[Listing] = []
        now = _now_iso()
        today = _today()
        seen_keys: set[str] = set()

        for listing in current:
            key = listing.key
            seen_keys.add(key)
            prior = previous.get(key)

            if prior is None:
                listing.first_seen = now
                listing.last_seen = now
                if listing.price_yen is not None:
                    listing.price_history = [{"date": today, "price_yen": listing.price_yen}]
                changes.new.append(listing)
                merged.append(listing)
                continue

            # 기존 물건 — 메타 이월
            listing.first_seen = prior.first_seen or now
            listing.last_seen = now
            listing.price_history = list(prior.price_history)

            if (
                listing.price_yen is not None
                and prior.price_yen is not None
                and listing.price_yen != prior.price_yen
            ):
                changes.price_changed.append(
                    PriceChange(listing, prior.price_yen, listing.price_yen)
                )
                listing.price_history.append({"date": today, "price_yen": listing.price_yen})
            else:
                changes.unchanged_count += 1

            merged.append(listing)

        for key, prior in previous.items():
            if key not in seen_keys:
                changes.removed.append(prior)

        return changes, merged

    # ------------------------------------------------------------------
    def save(self, listings: list[Listing], changes: Changes, sources: list[str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.changes_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at": _now_iso(),
            "sources": sources,
            "count": len(listings),
            "listings": [x.to_dict() for x in listings],
        }
        _write_json(self.listings_path, payload)

        changes_payload = changes.to_dict()
        _write_json(self.latest_changes_path, changes_payload)
        # 掲載終了된 물건은 다음 스냅샷에 없으므로, 이력 파일이 유일한 기록이다.
        _write_json(self.changes_dir / f"{_today()}.json", changes_payload)


    # ------------------------------------------------------------------
    def load_observations(self) -> list[dict[str, Any]]:
        if not self.observations_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.observations_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 손상된 한 줄이 전체 이력을 못 쓰게 만들면 안 된다
        return rows

    def record_observations(self, changes: Changes) -> int:
        """새로 본 물건과 가격이 바뀐 물건만 관측 로그에 덧붙인다.

        같은 물건을 매일 다시 적으면 최근 분기의 표본만 부풀어 추이가
        휜다. '처음 본 가격'과 '바뀐 가격'만 한 번씩 남기는 게 맞다.
        """
        rows: list[dict[str, Any]] = []
        today = _today()

        for listing in changes.new:
            row = _observation(listing, today, event="new")
            if row:
                rows.append(row)

        for change in changes.price_changed:
            row = _observation(change.listing, today, event="price_change")
            if row:
                rows.append(row)

        if not rows:
            return 0

        self.observations_path.parent.mkdir(parents=True, exist_ok=True)
        with self.observations_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)

    def append_observations(self, rows: Iterable[dict[str, Any]]) -> int:
        """이미 만들어진 관측 행을 그대로 덧붙인다 (데모 시드용)."""
        rows = list(rows)
        if not rows:
            return 0
        self.observations_path.parent.mkdir(parents=True, exist_ok=True)
        with self.observations_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)


def observation_row(listing: Listing, observed_on: str, event: str = "new") -> dict[str, Any] | None:
    """Listing → 관측 행. 추이 계산에 필요한 최소 필드만 남긴다."""
    return _observation(listing, observed_on, event)


def _observation(listing: Listing, observed_on: str, event: str) -> dict[str, Any] | None:
    unit = listing.unit_price_man_per_tsubo
    if unit is None or not listing.city:
        return None
    return {
        "date": observed_on,
        "event": event,
        "key": listing.key,
        "source": listing.source,
        "ward": listing.city,
        "stage": listing.stage,
        "kind": listing.kind,
        "total_units": listing.total_units,
        "area_m2": listing.area_m2,
        "price_yen": listing.price_yen,
        "unit": unit,
        "listed_on": listing.listed_on or observed_on,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)  # 중간에 죽어도 반쪽 JSON이 남지 않도록
