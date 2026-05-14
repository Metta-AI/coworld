from __future__ import annotations

import atexit
import logging
import os
import sys
from logging.handlers import QueueHandler, QueueListener
from queue import SimpleQueue
from urllib.request import Request, urlopen


class HttpLogHandler(logging.Handler):
    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def emit(self, record: logging.LogRecord) -> None:
        # QueueListener calls Handler.handle directly and does NOT catch
        # exceptions the way Logger.callHandlers does — a single failed POST
        # would kill the listener thread and silently stop all shipping.
        # Treat the POST as best-effort and route any network failure through
        # the stdlib's handleError (which prints a traceback to stderr).
        message = self.format(record)
        print(message, flush=True)
        try:
            request = Request(self.url, data=message.encode(), method="POST")
            request.add_header("Content-Type", "text/plain")
            # Cloudflare's WAF blocks the default "Python-urllib/X.Y" UA with
            # error 1010 ("Bad bot"); any non-default UA suffices.
            request.add_header("User-Agent", "cogame-paintarena/0.1")
            with urlopen(request, timeout=10):
                pass
        except Exception:
            self.handleError(record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    url = os.environ.get("COGAME_LOG_URI")
    if url:
        # QueueHandler enqueues on the caller's thread and a single
        # QueueListener thread drains FIFO into the HTTP handler — so
        # logger.info() doesn't block on the network and lines print and
        # ship in the order they were emitted.
        queue: SimpleQueue[logging.LogRecord] = SimpleQueue()
        listener = QueueListener(queue, HttpLogHandler(url))
        listener.start()
        atexit.register(listener.stop)
        logger.addHandler(QueueHandler(queue))
    else:
        logger.addHandler(logging.StreamHandler(sys.stdout))
    logger.propagate = False
    return logger
