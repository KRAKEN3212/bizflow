import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram

from .config import settings
from .db import init_schema
from .routers import auth, crm, system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

REQUESTS = Counter("bizflow_http_requests_total", "HTTP-запросы к API", ["method", "route", "status"])
LATENCY = Histogram(
    "bizflow_http_request_seconds", "Время обработки запроса", ["route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()
    yield


app = FastAPI(title="BizFlow API", version=settings.version, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    if path != "/metrics":
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        LATENCY.labels(path).observe(time.perf_counter() - start)
    response.headers["X-Served-By"] = settings.hostname
    return response


app.include_router(auth.router)
app.include_router(crm.router)
app.include_router(system.router)
