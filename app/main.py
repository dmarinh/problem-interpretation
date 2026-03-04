"""
FastAPI Application Entry Point

Main application factory and configuration.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.log_config import setup_logging, get_logger
from app.api.routes import health, translation


# Setup logging before anything else
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting {settings.app_name}")
    
    # Initialize ComBase engine
    try:
        from app.engines.combase.engine import get_combase_engine
        engine = get_combase_engine()
        
        csv_path = Path("data/combase_models.csv")
        if csv_path.exists():
            count = engine.load_models(csv_path)
            logger.info(f"Loaded {count} ComBase models")
        else:
            logger.warning(f"ComBase models not found at {csv_path}")
    except Exception as e:
        logger.error(f"Failed to initialize ComBase engine: {e}")
    
    # Initialize Vector Store
    try:
        from app.rag.vector_store import get_vector_store
        store = get_vector_store()
        store.initialize()
        doc_count = store.get_count()
        logger.info(f"Vector store initialized with {doc_count} documents")
        
        if doc_count == 0:
            logger.warning("Vector store is empty. Run ingestion to add documents.")
    except Exception as e:
        logger.error(f"Failed to initialize vector store: {e}")
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    """
    app = FastAPI(
        title=settings.app_name,
        description="""
        Problem Translation Module for Predictive Microbiology.
        
        Translates natural language food safety queries into structured predictions
        using ComBase and other predictive models.
        
        ## Features
        
        - Natural language query translation
        - RAG-grounded value extraction
        - Conservative default handling
        - Full provenance tracking
        - ComBase model execution
        """,
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health.router)
    app.include_router(translation.router, prefix="/api/v1")
    
    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )