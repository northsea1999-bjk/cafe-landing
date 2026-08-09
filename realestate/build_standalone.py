"""단일 HTML 파일 빌드.

web/ 의 CSS·JS·데이터를 한 파일로 합쳐 standalone.html 을 만든다.
fetch 가 막힌 환경(로컬 file://, 정적 호스팅 없이 파일만 전달)에서도 그대로 열린다.

    python3 realestate/build_standalone.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = WEB / "data"
OUT = WEB / "standalone.html"

#: 신규 매물 카드에 실제로 쓰이는 필드만 남긴다 (전체를 심으면 파일이 몇 배가 된다)
LISTING_FIELDS = (
    "title", "city", "stage", "price_man", "price_yen", "layout", "area_m2",
    "unit_price_man_per_tsubo", "total_units", "built_year", "station_labels",
)
MAX_LISTINGS = 60


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _slim_changes(changes: dict | None) -> dict | None:
    if not changes:
        return None
    return {
        "date": changes.get("date"),
        "summary": changes.get("summary"),
        "new": [
            {k: item.get(k) for k in LISTING_FIELDS}
            for item in sorted(
                changes.get("new", []),
                key=lambda x: x.get("price_yen") or 0,
                reverse=True,
            )[:MAX_LISTINGS]
        ],
    }


def _slim_recent(recent: dict | None) -> dict | None:
    if not recent:
        return None
    items = sorted(
        recent.get("items", []),
        key=lambda x: (x.get("found_on", ""), x.get("price_yen") or 0),
        reverse=True,
    )[:MAX_LISTINGS]
    return {
        "window_days": recent.get("window_days"),
        "items": [{k: it.get(k) for k in (*LISTING_FIELDS, "found_on")} for it in items],
    }


def build_artifact() -> Path:
    """호스트가 <html>/<head>/<body> 를 감싸주는 배포용 변형 (본문만 남긴다)."""
    full = build().read_text(encoding="utf-8")
    body = full.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    title = "<title>도쿄 7구 대규모 맨션 가격추이</title>\n"
    style = full.split("<style>", 1)[1].split("</style>", 1)[0]
    out = WEB / "artifact.html"
    out.write_text(f"{title}<style>\n{style}\n</style>\n{body}", encoding="utf-8")
    return out


def build() -> Path:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    payload = {
        "market": _read_json(DATA / "market.json"),
        "latest-changes": _slim_changes(_read_json(DATA / "latest-changes.json")),
        "sources": _read_json(DATA / "sources.json"),
        "recent-new": _slim_recent(_read_json(DATA / "recent-new.json")),
    }
    if payload["market"] is None:
        raise SystemExit("market.json 이 없습니다. 먼저 수집기를 실행하세요.")

    # </script> 가 데이터 안에 있으면 스크립트가 조기 종료된다
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    html = html.replace(
        '<link rel="stylesheet" href="styles.css">',
        f"<style>\n{css}\n</style>",
    )
    html = html.replace(
        '<script src="app.js"></script>',
        f"<script>window.__REALESTATE_DATA__ = {blob};</script>\n<script>\n{js}\n</script>",
    )

    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    import sys

    path = build_artifact() if "--artifact" in sys.argv else build()
    print(f"{path}  ({path.stat().st_size / 1024:.0f} KB)")
