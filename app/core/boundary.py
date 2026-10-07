"""ASGI request IDs, actual byte limits, and safe request logging."""

import asyncio
import logging
import time
from uuid import uuid4

from starlette.datastructures import State
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ERRORS, ErrorCode, error_body

logger = logging.getLogger("modelgate")


class RequestBoundaryMiddleware:
    def __init__(self, app: ASGIApp, state: State) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        async def reject(code: ErrorCode) -> None:
            response = JSONResponse(error_body(code, request_id), status_code=ERRORS[code][0])
            await response(scope, receive, send_with_id)

        try:
            limit = self.state.settings.max_request_bytes
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    status = 499
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > limit:
                    await reject("request_too_large")
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay, send_with_id)
        except asyncio.CancelledError:
            status = 499
            raise
        except Exception:
            # Do not log exceptions: provider libraries may include raw requests in them.
            if not response_started:
                await reject("internal_error")
        finally:
            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "status_code": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 3),
                    "release_name": scope["state"].get("release_name"),
                    "serving_role": scope["state"].get("serving_role"),
                    "config_version": scope["state"].get("config_version"),
                    "recording_status": scope["state"].get("recording_status"),
                },
            )
