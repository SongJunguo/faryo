"""Incremental Starlette adapter for the Faryo Gateway contract."""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette

import owner_client
import mcp_service
import asgi_auth
import asgi_agents
import asgi_bridge
import asgi_control
import asgi_support
import asgi_mcp
import asgi_owner_proxy
import asgi_read
import workbench_service


def create_app(legacy: Any, config: Any) -> Starlette:
    client = owner_client.OwnerClient(legacy.BACKENDS, config, encode_label=legacy.owner_label_header_value)
    support = asgi_support.AsgiSupport(legacy, config)
    workbench = workbench_service.WorkbenchService(legacy.WorkbenchRuntime, config, client)
    mcp = mcp_service.McpService(
        config,
        protocol_version=legacy.MCP_PROTOCOL_VERSION,
        server_version=legacy.MCP_SERVER_VERSION,
        tool_name=legacy.MCP_TOOL_NAME,
        tool_schema=legacy.MCP_TOOL_SCHEMAS[legacy.MCP_TOOL_NAME],
    )
    mcp_routes = asgi_mcp.McpRoutes(legacy, config, mcp)
    proxy_routes = asgi_owner_proxy.OwnerProxyRoutes(legacy, config, client, support)
    auth_routes = asgi_auth.AuthRoutes(legacy, config, support)
    read_routes = asgi_read.ReadRoutes(legacy, config, support, workbench)
    control_routes = asgi_control.routes(legacy, config, client, support)
    direct_api_fallback = asgi_control.direct_api_fallback_route(legacy, config, support)
    agent_routes = asgi_agents.routes(legacy, config, client, support)
    bridge_routes = asgi_bridge.routes(legacy, config, client, support)

    routes = [
        *read_routes.public_routes(),
        *auth_routes.routes(),
        *read_routes.account_routes(),
        proxy_routes.api_route(),
        *control_routes,
        *agent_routes,
        *bridge_routes,
        read_routes.api_fallback_route(),
        direct_api_fallback,
        *mcp_routes.routes(),
        read_routes.options_fallback_route(),
        read_routes.home_route(),
        proxy_routes.resource_route(),
        read_routes.static_route(),
    ]
    app = Starlette(routes=routes)
    app.state.close_owner_streams = proxy_routes.close_active_streams
    app.add_middleware(asgi_support.SecurityHeadersMiddleware)
    return app
