#!/usr/bin/env python3
"""Production Uvicorn entrypoint for the Faryo Gateway ASGI application."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Callable

import uvicorn

import asgi_app
import gateway_config
import server as legacy


LOGGER = logging.getLogger("uvicorn.error")


class FaryoServer(uvicorn.Server):
    """Close indefinite Owner streams before Uvicorn waits for HTTP tasks."""

    def __init__(self, config: uvicorn.Config, close_owner_streams: Callable[[], int]) -> None:
        super().__init__(config)
        self.close_owner_streams = close_owner_streams

    async def shutdown(self, sockets=None) -> None:
        closed = self.close_owner_streams()
        LOGGER.info("Closing %d active Owner stream(s) before graceful shutdown", closed)
        await super().shutdown(sockets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--auth-config", required=True)
    parser.add_argument("--owner-env", required=True)
    parser.add_argument("--portal-dir", required=True)
    parser.add_argument("--secret-file", required=True)
    return parser.parse_args()


def create_runtime_app(args: argparse.Namespace):
    config = gateway_config.GatewayConfig(
        Path(args.auth_config),
        Path(args.owner_env),
        Path(args.portal_dir),
        Path(args.secret_file),
        legacy.GATEWAY_CONFIG_RUNTIME,
    )
    return asgi_app.create_app(legacy, config)


def main() -> None:
    args = parse_args()
    app = create_runtime_app(args)
    print(f"Faryo Gateway ASGI listening on http://{args.host}:{args.port}", flush=True)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        access_log=False,
        backlog=128,
        forwarded_allow_ips="127.0.0.1",
        lifespan="off",
        limit_concurrency=256,
        log_level="info",
        proxy_headers=True,
        server_header=False,
        timeout_graceful_shutdown=10,
        timeout_keep_alive=5,
    )
    FaryoServer(config, app.state.close_owner_streams).run()


if __name__ == "__main__":
    main()
