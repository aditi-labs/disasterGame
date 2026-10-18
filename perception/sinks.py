"""Non-blocking observation / status sinks (spec 6.8).

The capture and tracking loop must never wait on the network.  ``HttpSink`` posts
from its own thread through a bounded queue and drops the *oldest* item when the
queue overflows, counting what it dropped so the operator can see it.
"""
from __future__ import annotations

import json
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Any, Callable, Protocol
import urllib.error
import urllib.request

from .events import PhysicalObservation


class ObservationSink(Protocol):
    def emit(self, observation: PhysicalObservation) -> None: ...
    def close(self) -> None: ...
    def status(self) -> dict[str, Any]: ...


class CallbackSink:
    def __init__(self, callback: Callable[[PhysicalObservation], None]):
        self.callback = callback
        self.count = 0

    def emit(self, observation: PhysicalObservation) -> None:
        self.count += 1
        self.callback(observation)

    def close(self) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {"kind": "callback", "emitted": self.count}


class JsonlSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.count = 0

    def emit(self, observation: PhysicalObservation) -> None:
        self._fh.write(observation.to_json() + "\n")
        self._fh.flush()
        self.count += 1

    def close(self) -> None:
        self._fh.close()

    def status(self) -> dict[str, Any]:
        return {"kind": "jsonl", "path": str(self.path), "emitted": self.count}


class StdoutSink:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.count = 0

    def emit(self, observation: PhysicalObservation) -> None:
        self.stream.write(observation.to_json() + "\n")
        self.stream.flush()
        self.count += 1

    def close(self) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {"kind": "stdout", "emitted": self.count}


class HttpPoster:
    """Threaded JSON POSTer with a bounded queue; shared by observation and status sinks."""

    def __init__(self, url: str, *, timeout_s: float = 2.0, queue_size: int = 256, name: str = "http-sink"):
        self.url = url
        self.timeout_s = timeout_s
        self._queue: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self.last_error: str | None = None
        self.last_status: int | None = None
        self.last_response: Any = None
        self.last_sent_at: float | None = None
        self.on_response: Callable[[dict[str, Any], Any], None] | None = None
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def post(self, payload: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.dropped += 1
                self._queue.put_nowait(payload)
            except (queue.Empty, queue.Full):
                self.dropped += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    self.last_status = resp.status
                    raw = resp.read()
                    try:
                        self.last_response = json.loads(raw.decode("utf-8")) if raw else None
                    except ValueError:
                        self.last_response = raw[:200].decode("utf-8", "replace")
                    self.sent += 1
                    self.last_sent_at = time.time()
                    self.last_error = None
                    if self.on_response is not None:
                        try:
                            self.on_response(payload, self.last_response)
                        except Exception as exc:  # pragma: no cover - callback bugs must not kill the thread
                            self.last_error = f"on_response: {exc}"
            except urllib.error.HTTPError as exc:
                self.failed += 1
                self.last_status = exc.code
                self.last_error = f"HTTP {exc.code}"
            except Exception as exc:
                self.failed += 1
                self.last_error = str(exc)[:160]

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def status(self) -> dict[str, Any]:
        return {"url": self.url, "sent": self.sent, "failed": self.failed, "dropped": self.dropped,
                "queued": self._queue.qsize(), "last_status": self.last_status, "last_error": self.last_error}


class HttpSink:
    def __init__(self, url: str, *, timeout_s: float = 2.0, queue_size: int = 256,
                 on_response: Callable[[dict[str, Any], Any], None] | None = None):
        self.poster = HttpPoster(url, timeout_s=timeout_s, queue_size=queue_size, name="observe-sink")
        self.poster.on_response = on_response

    def emit(self, observation: PhysicalObservation) -> None:
        self.poster.post(observation.as_dict())

    def close(self) -> None:
        self.poster.close()

    def status(self) -> dict[str, Any]:
        return {"kind": "http", **self.poster.status()}


class FanoutSink:
    def __init__(self, sinks: list[ObservationSink]):
        self.sinks = list(sinks)

    def add(self, sink: ObservationSink) -> None:
        self.sinks.append(sink)

    def emit(self, observation: PhysicalObservation) -> None:
        for s in self.sinks:
            try:
                s.emit(observation)
            except Exception as exc:  # one broken sink must not stop the others
                sys.stderr.write(f"[perception] sink {type(s).__name__} failed: {exc}\n")

    def close(self) -> None:
        for s in self.sinks:
            try:
                s.close()
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        return {"sinks": [s.status() for s in self.sinks]}
