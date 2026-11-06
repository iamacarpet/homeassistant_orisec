"""Logging for messages that would otherwise repeat on every poll or packet."""

from __future__ import annotations

import logging
import time
from typing import Any

from .const import DEBUG_LOG_INTERVAL


class ThrottledLog:
    """Log each kind of message at most once per ``interval``.

    The next message of a kind that gets through says how many were skipped, so debug
    logging can stay on through an intermittent fault without a line per packet.
    """

    def __init__(
        self, logger: logging.Logger, interval: float = DEBUG_LOG_INTERVAL
    ) -> None:
        self._logger = logger
        self._interval = interval
        # kind -> (when it was last logged, how many were skipped since)
        self._last: dict[str, tuple[float, int]] = {}

    def debug(self, kind: str, msg: str, *args: Any) -> None:
        self.log(logging.DEBUG, kind, msg, *args)

    def warning(self, kind: str, msg: str, *args: Any) -> None:
        self.log(logging.WARNING, kind, msg, *args)

    def log(self, level: int, kind: str, msg: str, *args: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        now = time.monotonic()
        last = self._last.get(kind)
        if last is not None and now - last[0] < self._interval:
            self._last[kind] = (last[0], last[1] + 1)
            return
        if last is not None and last[1]:
            msg += " (%d more like this skipped in the last %.0fs)"
            args = (*args, last[1], now - last[0])
        self._last[kind] = (now, 0)
        self._logger.log(level, msg, *args)
