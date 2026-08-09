"""소스 어댑터 인터페이스.

새 데이터 경로가 생기면 이 클래스를 하나 더 구현해서 registry 에 등록하면
끝이다. 수집기·차분·뷰어는 건드릴 필요가 없다.
"""

from __future__ import annotations

from typing import Any

from ..schema import Listing


class SourceError(RuntimeError):
    """어댑터가 데이터를 가져오지 못한 경우."""


class Source:
    key: str = ""
    name: str = ""
    #: 사람이 읽을 데이터 출처 근거 (라이선스·약관·계약). README 와 함께 관리한다.
    basis: str = ""

    def available(self, config: dict[str, Any]) -> tuple[bool, str]:
        """지금 이 환경에서 실행 가능한지. (가능여부, 사유)"""
        return True, ""

    def fetch(self, config: dict[str, Any]) -> list[Listing]:
        raise NotImplementedError

    # 편의
    def __repr__(self) -> str:  # pragma: no cover - 디버그용
        return f"<Source {self.key}>"
