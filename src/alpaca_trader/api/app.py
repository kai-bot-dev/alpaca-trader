"""FastAPI application for alpaca-trader."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from alpaca_trader.core.database import init_db
from alpaca_trader.api.routes import account, orders, options

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


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}
