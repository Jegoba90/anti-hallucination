"""One request's checks in a process of its own, where the HTTP service can stop them.

The service (http_server.py) hands each request's checks to a worker process
with a time limit and, where the system has one, a memory limit: a request
past either is refused instead of holding a core or the machine's memory, and
the service goes on. The checks themselves have limits of their own
(checks.MAX_MATCHES); these catch whatever those do not.

The time is kept here, by a timer in the worker, so it counts the checks and
not the worker's start; the service still kills a worker that does not stop.

This module is what the worker imports first, so it imports nothing heavy.
"""

import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import TypeVar

T = TypeVar("T")
# Linux and macOS: a timer in the worker. Elsewhere only the service's own
# limit applies, which also counts the worker's start.
TIMES_ITSELF = hasattr(signal, "setitimer")
_capped_at: int | None = None


def run_capped(call: Callable[[], T], memory_bytes: int | None, seconds: float | None = None) -> T:
    """Run `call` here, with this process's memory capped at memory_bytes and a timer of `seconds`.

    Past the time, `call` stops with TimeoutError; past the memory, an
    allocation raises MemoryError.
    """
    _cap_memory(memory_bytes)
    with _timer(seconds):
        return call()


class _OutOfTime(Exception):
    """Raised by the timer, so the checks cannot mistake it for one of their own."""


@contextmanager
def _timer(seconds: float | None) -> Iterator[None]:
    if seconds is None or not TIMES_ITSELF or sys.platform == "win32":
        yield
        return

    def ring(signum: int, frame: FrameType | None) -> None:
        raise _OutOfTime

    previous = signal.signal(signal.SIGALRM, ring)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    except _OutOfTime:
        raise TimeoutError(f"the checks took more than {seconds:g} s") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _cap_memory(memory_bytes: int | None) -> None:
    """Cap the address space of this process: past it, an allocation raises MemoryError.

    Only where the resource module exists (Linux, macOS); on Windows the
    time limit is the only one.
    """
    global _capped_at
    if memory_bytes is None or _capped_at == memory_bytes or sys.platform == "win32":
        return
    import resource

    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    soft = memory_bytes if hard == resource.RLIM_INFINITY else min(memory_bytes, hard)
    resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
    _capped_at = memory_bytes
