"""Operator / adapter control endpoint for the perception service.

docs/INTEGRATION_CONTRACT.md (shared lane) records that the UI's RESET and CLEAR
PENDING cannot clear the external perception service's track mapping, and that
"that mapping must be reset by its owner".  Spec 5 requires reset to clear
observation caches, world-token bindings and stale events; spec 6.10 requires a
safe reset without restarting hardware.  This tiny HTTP server (stdlib, own thread)
is that owner-side control surface.  Commands are queued and applied by the service
on its main loop between frames, so nothing here touches tracker state concurrently.

Endpoints (JSON):

    GET  /status                         full perception status (same as --status-url payload)
    POST /control/reset                  new session: tracks, bindings, pending, caches cleared
    POST /control/reference              re-capture the empty-board reference
    POST /control/clear_pending          {"track_id": optional}
    POST /control/recalibrate            drop held/smoothed board registration
    POST /control/pause                  {"paused": true|false}
    POST /control/feedback               {"track_id", "accepted", "world_token_id"?, "rejection_reason"?, "removed"?}
    POST /control/operator_class         {"track_id", "piece_class", "operator"?}
    POST /control/reemit                 {"track_id": optional}
    POST /control/exclusions             {"polygons_uv": [[[u,v],...], ...]}  projected UI areas to ignore

Every response is ``{"ok": bool, "queued": true, "session_id": ...}``; the command
takes effect on the next processed frame.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import threading
from typing import Any, Callable

COMMANDS = {"reset", "reference", "clear_pending", "recalibrate", "pause", "feedback",
            "operator_class", "reemit", "exclusions"}


class ControlServer:
    def __init__(self, service, host: str = "127.0.0.1", port: int = 8011):
        self.service = service
        self._queue: "queue.Queue[tuple[str, dict[str, Any]]]" = queue.Queue(maxsize=256)
        self.applied = 0
        self.rejected = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, default=str).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") == "/status":
                    try:
                        self._send(200, outer.service.status())
                    except Exception as exc:  # pragma: no cover
                        self._send(500, {"ok": False, "error": str(exc)})
                else:
                    self._send(404, {"ok": False, "error": "unknown path"})

            def do_POST(self) -> None:  # noqa: N802
                parts = self.path.strip("/").split("/")
                if len(parts) != 2 or parts[0] != "control" or parts[1] not in COMMANDS:
                    self._send(404, {"ok": False, "error": "unknown command", "commands": sorted(COMMANDS)})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                    if not isinstance(payload, dict):
                        raise ValueError("body must be a JSON object")
                except ValueError as exc:
                    self._send(400, {"ok": False, "error": f"bad JSON: {exc}"})
                    return
                try:
                    outer._queue.put_nowait((parts[1], payload))
                except queue.Full:
                    self._send(503, {"ok": False, "error": "control queue full"})
                    return
                self._send(202, {"ok": True, "queued": True, "command": parts[1],
                                 "session_id": outer.service.session_id})

            def log_message(self, *args) -> None:  # silence
                pass

        self._server = ThreadingHTTPServer((host, port), Handler)
        self.host, self.port = self._server.server_address[0], self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="perception-control", daemon=True)

    def start(self) -> "ControlServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def apply_pending(self) -> int:
        """Called by the service on its own thread; returns how many commands were applied."""
        n = 0
        while True:
            try:
                command, payload = self._queue.get_nowait()
            except queue.Empty:
                return n
            try:
                self._apply(command, payload)
                self.applied += 1
                n += 1
            except Exception as exc:
                self.rejected += 1
                self.service._warn(f"control {command} failed: {exc}")

    def _apply(self, command: str, payload: dict[str, Any]) -> None:
        svc = self.service
        if command == "reset":
            svc.reset_session()
        elif command == "reference":
            svc.capture_reference()
        elif command == "clear_pending":
            svc.clear_pending(payload.get("track_id"))
        elif command == "recalibrate":
            svc.recalibrate()
        elif command == "pause":
            svc.set_paused(bool(payload.get("paused", True)))
        elif command == "feedback":
            svc.handle_adapter_feedback(payload)
        elif command == "operator_class":
            svc.apply_operator_class(str(payload["track_id"]), str(payload["piece_class"]),
                                     str(payload.get("operator", "operator")))
        elif command == "reemit":
            svc.request_reemit(payload.get("track_id"))
        elif command == "exclusions":
            svc.set_projected_exclusions(list(payload.get("polygons_uv", [])))

    def status(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "queued": self._queue.qsize(),
                "applied": self.applied, "rejected": self.rejected}
