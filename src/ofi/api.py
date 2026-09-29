"""Read-only research API: bundled official data, forecast artifacts and cited evidence."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ofi import __version__

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("ofi.requests")
logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(
    title="Open Finance Intelligence",
    version=__version__,
    description=(
        "UK macroeconomic research using official BoE/ONS data and licensed policy documents. "
        "Data and forecasts are versioned snapshots. Research demonstration, not financial advice."
    ),
    contact={"name": "Jayashruthi Rajesh Babu", "url": "https://jayashruthi.com"},
    license_info={"name": "MIT (code); source-specific licences for data"},
)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=8, max_length=600, description="A policy question in English.")


class WindowLimiter:
    """Best-effort single-instance limit; provider budget controls remain necessary at scale."""

    def __init__(self, limit: int = 10, window: float = 60, capacity: int = 1024):
        self.limit, self.window, self.capacity = limit, window, capacity
        self.events: dict[str, deque] = defaultdict(deque)
        self.lock = Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            expired = [k for k, q in self.events.items() if not q or q[-1] <= now - self.window]
            for k in expired:
                del self.events[k]
            if key not in self.events and len(self.events) >= self.capacity:
                return False
            queue = self.events[key]
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if len(queue) >= self.limit:
                return False
            queue.append(now)
            return True


limiter = WindowLimiter()
global_limiter = WindowLimiter(limit=40, capacity=1)


class RequestBoundary:
    """Bound JSON bodies before parsing; attach request IDs and privacy-preserving logs."""

    def __init__(self, app):
        self.application = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return
        started = time.perf_counter()
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        path = scope.get("path", "")

        async def safe_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"x-frame-options", b"DENY"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                if path == "/":
                    headers.append(
                        (
                            b"content-security-policy",
                            (
                                "default-src 'self'; script-src 'self'; style-src 'self'; "
                                "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
                            ).encode(),
                        )
                    )
                if path.startswith("/api/") or path == "/health":
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        try:
            if path == "/api/ask" and scope["method"] == "POST":
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > 8192:
                        response = JSONResponse({"detail": "Request body exceeds 8 KB."}, 413)
                        await response(scope, receive, safe_send)
                        return
                    if not message.get("more_body", False):
                        break
                sent = False

                async def replay():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.application(scope, replay, safe_send)
            else:
                await self.application(scope, receive, safe_send)
        finally:
            state = scope.get("state", {})
            # No request body, query text, IP address, headers or credentials are logged.
            route = scope.get("route")
            logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "method": scope.get("method"),
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "app_version": __version__,
                        "model_version": state.get("model_version"),
                        "retrieval_mode": state.get("retrieval_mode"),
                        "abstained": state.get("abstained"),
                    }
                )
            )


app.add_middleware(RequestBoundary)


def modules():
    # Deferred import makes /health capable of reporting an incomplete deployment.
    from ofi import data, model, rag

    return data, model, rag


@app.get("/health", tags=["Operations"])
def health():
    try:
        data, model, rag = modules()
        series = data.list_series()
        forecast = model.get_forecast()
        corpus = rag.corpus_metadata()
        if not series or not corpus or not data.query_series(series[0]["id"]):
            raise ValueError("Empty required artifact")
        return {
            "status": "ok",
            "version": __version__,
            "series_count": len(series),
            "document_count": len(corpus),
            "model_version": forecast["model_version"],
            "forecast_as_of": forecast["as_of"],
            "checks": {"data": "ok", "forecast": "ok", "corpus": "ok"},
            "external_provider": "not_checked",
        }
    except Exception:
        logger.error(json.dumps({"event": "readiness_failed"}))
        return JSONResponse({"status": "unavailable", "version": __version__}, status_code=503)


@app.get("/api/overview", tags=["Research"])
def overview(request: Request):
    data, model, rag = modules()
    forecast = model.get_forecast()
    request.state.model_version = forecast["model_version"]
    return {
        "series": data.list_series(),
        "forecast": forecast,
        "evaluation": model.get_evaluation(),
        "corpus": rag.corpus_metadata(),
    }


@app.get("/api/series", tags=["Data"])
def series_catalog():
    data, _, _ = modules()
    return {"series": data.list_series()}


@app.get("/api/data/{series_id}", tags=["Data"])
def query_data(
    series_id: str,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    if start and end and start > end:
        raise HTTPException(422, "start must be on or before end")
    data, _, _ = modules()
    metadata = next((s for s in data.list_series() if s["id"] == series_id), None)
    if metadata is None:
        raise HTTPException(404, "Unknown series. See /api/series for supported identifiers.")
    observations = data.query_series(
        series_id, start.isoformat() if start else None, end.isoformat() if end else None
    )
    return {"series": metadata, "observations": observations, "count": len(observations)}


@app.get("/api/forecast", tags=["Forecast"])
def forecast(request: Request):
    _, model, _ = modules()
    result = model.get_forecast()
    request.state.model_version = result["model_version"]
    return result


@app.get("/api/evaluation", tags=["Forecast"])
def evaluation():
    return modules()[1].get_evaluation()


@app.get("/api/corpus", tags=["Evidence"])
def corpus_catalog():
    return {"documents": modules()[2].corpus_metadata()}


@app.post("/api/ask", tags=["Evidence"])
async def ask(payload: Question, request: Request):
    host = request.client.host if request.client else "unknown"
    if not limiter.allow(host) or not global_limiter.allow("instance"):
        raise HTTPException(
            429, "Please wait a minute before asking again.", headers={"Retry-After": "60"}
        )
    _, _, rag = modules()
    result = await run_in_threadpool(rag.answer_question, payload.question)
    request.state.retrieval_mode = result.get("mode")
    request.state.abstained = result.get("abstained")
    return result


@app.get("/", include_in_schema=False)
def interface():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/robots.txt", include_in_schema=False)
def robots():
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /docs\n")


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
