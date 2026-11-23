"""ログが届くまで待つための、繰り返し確認の仕組み。

呼び出しログも CloudTrail も、呼び出した直後には見つからない（届くまで数分かかる）。
そのため、決まった間隔で探し直し、時間切れになったら「見つからなかった」と返す。
"""

from __future__ import annotations

import time
from collections.abc import Callable


def poll[T](
    fetch: Callable[[], T | None],
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T | None:
    """fetch() が None 以外を返すまで、interval_s 秒ごとに繰り返す。

    入力: 探す関数, 待つ上限（秒）, 間隔（秒）, 待ち方と時計（テストで差し替える）
    戻り値: 見つかった値。時間切れなら None
    """
    deadline = clock() + timeout_s
    while True:
        found = fetch()
        if found is not None:
            return found
        if clock() + interval_s > deadline:
            return None
        sleep(interval_s)
