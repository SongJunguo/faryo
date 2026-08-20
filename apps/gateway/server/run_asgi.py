#!/usr/bin/env python3
"""Production Uvicorn entrypoint for the Faryo Gateway ASGI application."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

import asgi_app
import gateway_config
import server as legacy


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
    uvicorn.run(
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


if __name__ == "__main__":
    main()
