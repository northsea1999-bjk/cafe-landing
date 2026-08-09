"""수집 실행기.

    python -m realestate.collector.run --config realestate/config.json

하는 일:
  1. 활성화된 소스에서 매물을 긁어온다 (건너뛴 소스는 사유와 함께 보고)
  2. 포털 간 중복 게재를 접는다
  3. 직전 스냅샷과 비교해 新着 / 価格変更 / 掲載終了 를 뽑는다
  4. 새로 본 가격을 관측 로그에 덧붙인다  ← 추이의 원천
  5. 관측 로그로 구별·단계별 가격추이를 만든다
  6. (키가 있으면) 국토교통성 성약가 추이를 배경선으로 함께 만든다
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import market
from .schema import dedupe
from .sources import REGISTRY, SOURCE_ORDER, SourceError
from .sources.portals import PORTALS
from .sources.sample import SampleSource
from .store import Store, observation_row

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "realestate" / "config.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="도쿄 7구 맨션 가격추이 수집기")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path, default=None, help="기본값은 config.data_dir")
    parser.add_argument("--sources", default="", help="쉼표로 구분. 지정하면 이것만 실행")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    data_dir = args.data_dir or (args.config.parent / config.get("data_dir", "web/data"))
    store = Store(data_dir)

    only = {s.strip() for s in args.sources.split(",") if s.strip()}

    # --- 1. 수집 ---------------------------------------------------
    collected: list[Any] = []
    status: list[dict[str, Any]] = []

    for key in SOURCE_ORDER:
        if only and key not in only:
            continue
        source = REGISTRY[key]
        ok, reason = source.available(config)
        if not ok:
            status.append({"key": key, "name": source.name, "state": "skipped", "reason": reason})
            print(f"  - {key:16s} skip   ({reason})")
            continue
        try:
            rows = source.fetch(config)
        except SourceError as exc:
            status.append({"key": key, "name": source.name, "state": "error", "reason": str(exc)})
            print(f"  ! {key:16s} error  ({exc})", file=sys.stderr)
            continue
        collected.extend(rows)
        status.append({"key": key, "name": source.name, "state": "ok", "count": len(rows)})
        print(f"  + {key:16s} {len(rows):5d} 件")

    if not collected:
        print("수집된 물건이 없습니다. config 의 sources 설정을 확인하세요.", file=sys.stderr)
        return 1

    # --- 2. 중복 제거 ------------------------------------------------
    before = len(collected)
    listings = dedupe(collected)
    if before != len(listings):
        print(f"  중복 게재 {before - len(listings)}건 정리 → {len(listings)}건")

    # --- 3. 차분 ------------------------------------------------------
    previous = store.load_previous()
    changes, merged = store.diff(previous, listings)
    print(
        f"  新着 {len(changes.new)} / 価格変更 {len(changes.price_changed)} / "
        f"掲載終了 {len(changes.removed)} / 変更なし {changes.unchanged_count}"
    )

    if args.dry_run:
        print("(dry-run: 파일을 쓰지 않았습니다)")
        return 0

    store.save(merged, changes, sources=[s["key"] for s in status if s["state"] == "ok"])

    # --- 4. 관측 로그 --------------------------------------------------
    seeded = _seed_demo_history(store, config, only)
    if seeded:
        print(f"  데모 이력 {seeded}건 시드 (架空データ)")
    appended = store.record_observations(changes)
    recent = store.update_recent(changes, merged, days=int(config.get("recent_window_days", 7)))
    print(f"  관측 로그 +{appended}건 · 최근 신규 {recent}건")

    # --- 5. 추이 --------------------------------------------------------
    observations = store.load_observations()
    trends = market.build_listing_trends(observations, config)
    if trends is not None:
        sources_used = set(trends.get("sources", []))
        # 샘플에서만 나온 추이는 무조건 '가상' 표시를 단다.
        trends["synthetic"] = sources_used.issubset({"sample"})
        print(
            f"  추이 계열 {len(trends['series'])}개 / 기간 {len(trends['periods'])}구간"
            + ("  ⚠ 架空データ" if trends["synthetic"] else "")
        )
    else:
        print("  추이: 표본 부족 (수집이 쌓이면 생성됩니다)")

    official: dict[str, Any] | None
    try:
        official = market.build_official_trends(config)
        print(f"  공식 성약가 추이 {len(official['series'])}계열")
    except market.MarketUnavailable as exc:
        official = None
        print(f"  공식 성약가 추이: 없음 ({exc})")

    _write_json(
        Path(store.root) / "market.json",
        {
            "generated_at": _now_iso(),
            "listing_trends": trends,
            "official_trends": official,
        },
    )

    # --- 6. 소스 상태 (UI 의 '데이터 출처' 패널용) -------------------
    _write_json(
        Path(store.root) / "sources.json",
        {
            "generated_at": _now_iso(),
            "status": status,
            "portals": [p.describe() for p in PORTALS],
        },
    )

    print(f"완료 → {store.root}")
    return 0


# ----------------------------------------------------------------------
def _seed_demo_history(store: Store, config: dict[str, Any], only: set[str]) -> int:
    """샘플 소스로 과거 관측을 한 번만 채운다 (그래프가 비어 보이지 않도록)."""
    cfg = config.get("sources", {}).get("sample", {})
    if not cfg.get("enabled") or not cfg.get("seed_history"):
        return 0
    if only and "sample" not in only:
        return 0
    if store.observations_path.exists():
        return 0

    days = int(cfg.get("seed_history_days", 365 * 5))
    history = SampleSource().history(config, days=days)
    rows = []
    for item in history:
        row = observation_row(item, observed_on=item.listed_on or _today(), event="seed")
        if row:
            rows.append(row)
    return store.append_observations(rows)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"config 파일이 없습니다: {path}")
    config = json.loads(path.read_text(encoding="utf-8"))
    # feed 어댑터가 상대경로를 config 위치 기준으로 풀 수 있도록
    for key, cfg in config.get("sources", {}).items():
        if isinstance(cfg, dict):
            cfg.setdefault("base_dir", str(path.parent))
    return config


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
