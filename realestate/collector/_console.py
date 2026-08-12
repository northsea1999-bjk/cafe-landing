"""콘솔 출력 준비.

윈도우 기본 콘솔은 한국어판이면 cp949, 일본어판이면 cp932다. 이 프로그램은
일본어 지명(アットホーム·中央区)과 한국어를 함께 찍기 때문에, 그대로 두면
윈도우에서 UnicodeEncodeError 로 죽는다. 실제로 죽는다 — 경고가 아니라
프로그램이 멈춘다.

그래서 진입점마다 이 함수를 먼저 부른다. 표준 출력을 UTF-8 로 바꾸고,
그래도 못 찍는 글자는 죽는 대신 대체 문자로 흘려보낸다.
"""

from __future__ import annotations

import sys


def setup() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue                      # 파이프로 넘어간 경우 등
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass                          # 못 바꿔도 프로그램은 계속 돈다
