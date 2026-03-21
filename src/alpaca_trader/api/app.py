"""FastAPI application for alpaca-trader."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from alpaca_trader.core.database import init_db
from alpaca_trader.api.routes import account, orders, options
from alpaca_trader.api.routes import alerts, monitor

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize DB on startup."""
    await init_db()
    yield


app = FastAPI(
    title="alpaca-trader API",
    description="Alpaca options paper trading backend",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(account.router, prefix="/api/account", tags=["account"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(options.router, prefix="/api/options", tags=["options"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["monitor"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}


# Serve built React frontend at /
_FRONTEND_DIR = Path(__file__).parent.parent.parent.parent / "dist" / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIR / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str = ""):
        """Serve the React SPA for all non-API routes."""
        index = _FRONTEND_DIR / "index.html"
        return FileResponse(str(index))
