"""소스 레지스트리.

새 데이터 경로가 생기면 Source 를 구현해 여기 등록하면 끝이다.
등록 순서 = 중복 제거 시 우선순위 (앞에 있는 소스의 레코드를 남긴다).
"""

from __future__ import annotations

from .base import Source, SourceError
from .feed import FeedSource
from .portals import PORTALS, PortalSource
from .sample import SampleSource

_ORDERED: tuple[Source, ...] = (
    *PORTALS,        # 포털 우선 — 상세 정보가 가장 풍부하다
    FeedSource(),    # 라이선스 피드
    SampleSource(),  # 데모 (다른 소스가 없을 때만 의미 있음)
)

REGISTRY: dict[str, Source] = {src.key: src for src in _ORDERED}

SOURCE_ORDER: list[str] = [src.key for src in _ORDERED]

__all__ = [
    "REGISTRY",
    "SOURCE_ORDER",
    "Source",
    "SourceError",
    "PortalSource",
    "PORTALS",
]
