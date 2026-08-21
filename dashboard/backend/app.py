"""FastAPI application for the SPEED dashboard.

Lifespan:
  1. Open SQLite connection (WAL mode)
  2. Run schema migrations
  3. Register project
  4. Backfill existing JSONL files
  5. Start watchdog file watcher
  On shutdown: stop watcher, close DB
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter

from . import db, ingest, spec_registry, spec_graph, spec_watcher
from .schema import schema
from .subscriptions import SubscriptionManager

log = logging.getLogger("speed.dashboard")


def create_app(project_root: str) -> FastAPI:
    """Build the FastAPI app configured for a target project."""

    project_root_path = Path(project_root)
    sub_manager = SubscriptionManager()
    conn = None
    observer = None
    spec_observer = None
    active_feature_observer = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        nonlocal conn, observer, spec_observer, active_feature_observer

        # 1. Database
        log.info("Opening database for %s", project_root)
        conn = db.connect(project_root)
        db.migrate(conn)

        # 2. Register project
        ingest.register_project(conn, project_root)

        # 3. Backfill
        count = ingest.backfill(conn, project_root)
        log.info("Backfill complete: %d files ingested", count)

        # 4. File watcher (JSONL logs)
        loop = asyncio.get_event_loop()
        observer = ingest.start_watcher(conn, project_root, sub_manager, loop)

        # 5. Spec registry
        spec_count = spec_registry.rebuild_registry(conn, project_root)
        log.info("Spec registry: %d specs indexed", spec_count)

        # 6. Spec relationship graph
        edge_count = spec_graph.rebuild_edges(conn, project_root)
        log.info("Spec graph: %d edges", edge_count)

        # 7. Spec file watcher
        spec_observer = spec_watcher.start_spec_watcher(
            conn, project_root, sub_manager, loop
        )

        # 8. Active feature watcher
        active_feature_observer = ingest.start_active_feature_watcher(
            project_root, sub_manager, loop
        )

        yield

        # Shutdown
        if active_feature_observer:
            active_feature_observer.stop()
            active_feature_observer.join(timeout=5)
        if spec_observer:
            spec_observer.stop()
            spec_observer.join(timeout=5)
        if observer:
            observer.stop()
            observer.join(timeout=5)
        if conn:
            conn.close()
        log.info("Dashboard shutdown complete")

    app = FastAPI(
        title="SPEED Dashboard API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for Next.js dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # GraphQL context: provide conn, project_root, sub_manager to all resolvers
    async def get_context() -> dict:
        return {
            "conn": conn,
            "project_root": project_root_path,
            "sub_manager": sub_manager,
        }

    graphql_app = GraphQLRouter(
        schema,
        context_getter=get_context,
    )

    app.include_router(graphql_app, prefix="/graphql")

    @app.get("/health")
    async def healthcheck() -> dict:
        return {"status": "ok", "project_root": project_root}

    return app
