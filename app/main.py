"""
FastAPI Application Entry Point

This module initializes the FastAPI application and registers all routes.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware #CORS only protects the browser JavaScript client, not curl or other http clients

from app import __version__
from app.api.routes import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager. This is used by FastAPI to handle startup and shutdown events.
    """
    # Startup
    # Initialize database connections
    # Load ML models into memory
    # Warm up caches
    yield
    # Shutdown
    # Close database connections
    # Save state
    # Clean up resources


def create_app() -> FastAPI:
    """
    Application factory.
    """
    app = FastAPI(
        title="Problem Interpretation Module",
        description=(
            "Semantic middleware for translating natural language food safety "
            "scenarios into engine-compliant predictive microbiology parameters."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routes
    app.include_router(health.router, tags=["Health"])
    
    return app


# Application instance
app = create_app()