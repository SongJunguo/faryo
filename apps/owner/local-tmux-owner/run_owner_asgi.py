#!/usr/bin/env python3
"""Production Uvicorn entrypoint for the Faryo Owner."""

from __future__ import annotations

import logging
from typing import Callable

import uvicorn

import owner_asgi
import server as core


LOGGER = logging.getLogger("uvicorn.error")


class FaryoOwnerServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, close_event_streams: Callable[[], int]) -> None:
        super().__init__(config)
        self.close_event_streams = close_event_streams

    async def shutdown(self, sockets=None) -> None:
        closed = self.close_event_streams()
        LOGGER.info("Closing %d active Owner stream(s) before graceful shutdown", closed)
        await super().shutdown(sockets)


def main() -> int:
    args = core.parse_args()
    token = args.token or core.secrets.token_urlsafe(24)
    config = core.Config(
        session=args.session,
        token=token,
        pane_width=args.pane_width,
    )
    core.scrub_tmux_global_environment(config)
    try:
        core.ensure_pane_width(config)
    except core.OwnerError as exc:
        print(f"warning: {exc}", file=core.sys.stderr, flush=True)
    core.refresh_command_catalog_if_needed()
    app = owner_asgi.create_app(core, config)
    print(
        f"Faryo Owner ASGI listening on http://{args.host}:{args.port}/?token=<private-token>",
        flush=True,
    )
    print(f"session={args.session} pane_width={config.pane_width}", flush=True)
    uvicorn_config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        access_log=False,
        backlog=128,
        forwarded_allow_ips="127.0.0.1",
        lifespan="on",
        limit_concurrency=128,
        log_level="info",
        proxy_headers=True,
        server_header=False,
        timeout_graceful_shutdown=10,
        timeout_keep_alive=5,
    )
    FaryoOwnerServer(uvicorn_config, app.state.close_event_streams).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
