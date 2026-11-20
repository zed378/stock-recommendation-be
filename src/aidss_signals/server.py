"""The signal receiver's counterpart: a Socket.IO server the CryptoSpike client connects to.

It speaks the contract the client's code implies (`auth: {token}` at the handshake, `new_signal`
broadcast, `signal_ack` back). A wrong or missing token is refused at the handshake. Nothing is
sent unless the worker publishes, and the server places no order: the client decides what to do
with a signal under its own settings (autoExecute, dry run, filters, position limits).
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import socketio

_ACK_FIELDS = ("signalId", "stage", "environment", "status", "reason")


class SignalHub:
    def __init__(self, token: str, ack_log: Path | None = None) -> None:
        if len(token) < 16:
            raise ValueError("the client token must be at least 16 characters")
        self._token = token.encode()
        self._ack_log = ack_log
        self.acks: list[dict[str, Any]] = []
        self.on_ack: Callable[[dict[str, Any]], None] | None = None
        self.sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
        self.app = socketio.ASGIApp(self.sio)
        self._register()

    def _register(self) -> None:
        @self.sio.event
        async def connect(sid: str, environ: dict[str, Any], auth: Any) -> None:
            supplied = auth.get("token") if isinstance(auth, dict) else None
            if not isinstance(supplied, str) or not hmac.compare_digest(
                supplied.encode(), self._token
            ):
                raise socketio.exceptions.ConnectionRefusedError("invalid client token")

        @self.sio.on("signal_ack")
        async def signal_ack(sid: str, data: Any) -> None:
            if not isinstance(data, dict):
                return
            ack = {k: str(data[k])[:300] for k in _ACK_FIELDS if data.get(k) is not None}
            self.acks.append(ack)
            if self._ack_log is not None:
                try:
                    self._ack_log.parent.mkdir(parents=True, exist_ok=True)
                    with self._ack_log.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(ack) + "\n")
                except OSError:
                    pass
            if self.on_ack is not None:
                self.on_ack(ack)

        @self.sio.on("ping")
        async def ping(sid: str, *_: Any) -> None:
            return None

    async def publish(self, signal: dict[str, Any]) -> int:
        """Broadcast one signal; returns how many receivers were connected to get it."""
        await self.sio.emit("new_signal", signal)
        return len(self.sio.manager.rooms.get("/", {}).get(None, {}))
