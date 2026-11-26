import asyncio

from app.middleware import EvidenceUploadSizeLimitMiddleware
from starlette.types import Message, Receive, Scope, Send


def _scope(*, path: str, headers: list[tuple[bytes, bytes]]) -> Scope:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
    }


def test_rejects_oversized_content_length_before_calling_app() -> None:
    app_called = False
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal app_called
        app_called = True

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = EvidenceUploadSizeLimitMiddleware(app, max_request_bytes=5)
    asyncio.run(
        middleware(
            _scope(
                path="/api/v1/action-items/1/progress-updates/2/evidence/files",
                headers=[(b"content-length", b"6")],
            ),
            receive,
            send,
        )
    )

    assert not app_called
    assert sent[0]["status"] == 413


def test_rejects_chunked_body_over_limit_while_streaming() -> None:
    sent: list[Message] = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    app_consumed = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal app_consumed
        app_consumed = True
        while (await receive())["more_body"]:
            pass

    async def receive() -> Message:
        return next(chunks)

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = EvidenceUploadSizeLimitMiddleware(app, max_request_bytes=5)
    asyncio.run(
        middleware(
            _scope(
                path="/api/v1/action-items/1/progress-updates/2/evidence/files",
                headers=[],
            ),
            receive,
            send,
        )
    )

    assert app_consumed
    assert sent[0]["status"] == 413


def test_does_not_limit_unrelated_requests() -> None:
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"123456", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = EvidenceUploadSizeLimitMiddleware(app, max_request_bytes=5)
    asyncio.run(
        middleware(
            _scope(path="/api/v1/health", headers=[]),
            receive,
            send,
        )
    )

    assert sent[0]["status"] == 204
