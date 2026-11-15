"""Small, per-process safeguards for the local demo, not a production quota service."""

import time
from collections import deque
from threading import Lock

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.config import get_settings


class DemoGuards:
    def __init__(self, app):
        self.app = app
        self._recent: deque[float] = deque()
        self._active = 0
        self._lock = Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                # The optional framework docs use its CDN; the chat page remains self-only.
                docs = scope["path"] in {"/docs", "/redoc"}
                script_policy = (
                    b"script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                    if docs
                    else b"script-src 'self'; "
                )
                message.setdefault("headers", []).extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; "
                            + script_policy
                            + b"style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                            b"connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                            b"base-uri 'none'; frame-ancestors 'none'",
                        ),
                    ]
                )
            await send(message)

        if scope["path"] != "/api/chat" or scope["method"] != "POST":
            return await self.app(scope, receive, secure_send)

        async def reject(status, message):
            response = JSONResponse(
                {"detail": message},
                status_code=status,
                headers={"Retry-After": "60"} if status == 429 else None,
            )
            await response(scope, receive, secure_send)

        # Other websites must not drive a user's loopback demo using browser requests.
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        expected = f"{scope['scheme']}://{headers.get('host', '')}"
        if origin is not None and origin != expected:
            return await reject(403, "Cross-origin chat requests are not allowed.")

        settings = get_settings()
        now = time.monotonic()
        with self._lock:
            while self._recent and now - self._recent[0] >= 60:
                self._recent.popleft()
            limited = len(self._recent) >= settings.chat_requests_per_minute
            busy = self._active >= settings.chat_max_concurrent
            if not limited and not busy:
                self._recent.append(now)
                self._active += 1
        if limited or busy:
            return await reject(429, "The demo is busy. Please try again in a minute.")

        try:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > settings.chat_max_body_bytes:
                    return await reject(413, "The request is too large. Clear older chat history.")
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, replay, secure_send)
        finally:
            with self._lock:
                self._active -= 1
