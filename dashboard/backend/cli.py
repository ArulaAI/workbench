"""CLI entry point for the SPEED dashboard backend."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="speed-dashboard",
        description="SPEED Dashboard API server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SPEED_DASHBOARD_PORT", "4440")),
        help="Port to listen on (default: 4440)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--project-root",
        default=os.environ.get("SPEED_PROJECT_ROOT", os.getcwd()),
        help="Target project root (default: cwd or $SPEED_PROJECT_ROOT)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Validate project root
    speed_dir = os.path.join(args.project_root, ".speed")
    if not os.path.isdir(speed_dir):
        print(f"Error: {speed_dir} not found. Run from a SPEED-initialized project.", file=sys.stderr)
        sys.exit(1)

    from .app import create_app

    app = create_app(args.project_root)

    import uvicorn

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main()
