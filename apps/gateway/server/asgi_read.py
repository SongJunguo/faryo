"""Starlette read-only Gateway pages, assets, status, and workbench routes."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any

from anyio import to_thread
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import gateway_security


class ReadRoutes:
    ICON_FILES = {"pwa-light-192.png", "pwa-light-512.png", "favicon.png", "favicon.ico", "faryo-mark.png"}

    def __init__(self, legacy: Any, config: Any, support: Any, workbench: Any) -> None:
        self.legacy = legacy
        self.config = config
        self.support = support
        self.workbench = workbench
        self.static_dir = Path(legacy.STATIC_DIR)
        self.shared_static_dir = Path(legacy.SHARED_STATIC_DIR)

    async def manifest(self, _request: Request) -> Response:
        return self.support.json_response(self.legacy.PWA_MANIFEST)

    async def service_worker(self, _request: Request) -> Response:
        return Response(
            self.legacy.PWA_SW.encode("utf-8"),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    async def static_asset(self, request: Request) -> Response:
        filename = request.path_params["filename"]
        content_type = self.legacy.GATEWAY_STATIC_FILES.get(filename) or self.legacy.SHARED_STATIC_FILES.get(filename)
        if not content_type:
            current = self.support.username(request)
            if not current:
                target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse(
                    "/login?" + self.legacy.urlencode({"next": gateway_security.safe_target(target)}),
                    status_code=HTTPStatus.SEE_OTHER,
                )
            return self.not_found()
        root = self.static_dir if filename in self.legacy.GATEWAY_STATIC_FILES else self.shared_static_dir
        return Response(
            (root / filename).read_bytes(),
            headers={"Content-Type": content_type, "Cache-Control": "no-store"},
        )

    def icon_response(self, filename: str) -> Response:
        path = self.static_dir / "icons" / filename
        if filename not in self.ICON_FILES or not path.is_file():
            return self.not_found()
        content_type = "image/x-icon" if filename.endswith(".ico") else "image/png"
        return Response(
            path.read_bytes(),
            headers={"Content-Type": content_type, "Cache-Control": "public, max-age=86400"},
        )

    async def icon(self, request: Request) -> Response:
        return self.icon_response(str(request.path_params["filename"]))

    async def favicon(self, _request: Request) -> Response:
        return self.icon_response("favicon.ico")

    def not_found(self) -> Response:
        status = HTTPStatus.NOT_FOUND
        short, explain = self.legacy.GatewayHandler.responses[status]
        body = self.legacy.GatewayHandler.error_message_format % {
            "code": status.value,
            "message": short,
            "explain": explain,
        }
        return Response(
            body.encode("utf-8", errors="replace"),
            status_code=status,
            headers={"Content-Type": self.legacy.GatewayHandler.error_content_type},
        )

    async def api_fallback(self, request: Request) -> Response:
        if not self.support.username(request):
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return self.support.json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    async def options_fallback(self, _request: Request) -> Response:
        return Response(status_code=HTTPStatus.NO_CONTENT)

    async def security_activity(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        try:
            limit = int(request.query_params.get("limit", "30"))
        except ValueError:
            limit = 30
        entries = await to_thread.run_sync(lambda: self.config.control_activity(current, limit))
        return self.support.json_response({"ok": True, "entries": entries})

    async def bridge_packages(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        packages = await to_thread.run_sync(lambda: self.config.list_bridge_packages(current))
        return self.support.json_response({"ok": True, "packages": packages})

    async def gateway_status(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        routes = self.config.user_routes(current)
        entries = await to_thread.run_sync(lambda: [self.legacy.backend_status(route) for route in routes])
        return self.support.json_response({"ok": True, "entries": entries})

    async def workbench_payload(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        query = {key: request.query_params.getlist(key) for key in request.query_params}
        filters = self.legacy.history_filters_from_query(query)
        payload = await to_thread.run_sync(lambda: self.workbench.payload(current, page, filters))
        return self.support.json_response(payload)

    async def bridge_package_asset(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            target = gateway_security.safe_target(request.url.path)
            return RedirectResponse(
                "/login?" + self.legacy.urlencode({"next": target}),
                status_code=HTTPStatus.SEE_OTHER,
            )
        package_id = str(request.path_params["package_id"])
        filename = str(request.path_params["filename"])
        if not self.legacy.clean_package_id(package_id) or filename != Path(filename).name:
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        package = self.config.bridge_package(package_id, current)
        asset_path = self.config.bridge_root / package_id / filename
        if not package or not asset_path.is_file():
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        content_type = self.legacy.BRIDGE_SUFFIX_MIME.get(
            asset_path.suffix.lower(),
            "application/octet-stream",
        )
        return Response(
            asset_path.read_bytes(),
            headers={"Content-Type": content_type, "Cache-Control": "private, no-store"},
        )

    async def home(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            target = gateway_security.safe_target(
                request.url.path + (f"?{request.url.query}" if request.url.query else "")
            )
            return RedirectResponse(
                "/login?" + self.legacy.urlencode({"next": target}),
                status_code=HTTPStatus.SEE_OTHER,
            )
        return self.support.html_page(
            request,
            self.legacy.portal_html(current, self.config.user_routes(current)),
        )

    def public_routes(self) -> list[Route]:
        return [
            Route("/manifest.json", self.manifest, methods=["GET"]),
            Route("/sw.js", self.service_worker, methods=["GET"]),
            Route("/icons/{filename}", self.icon, methods=["GET"]),
            Route("/favicon.ico", self.favicon, methods=["GET"]),
        ]

    def account_routes(self) -> list[Route]:
        return [
            Route("/api/security-activity", self.security_activity, methods=["GET"]),
            Route("/api/gateway-status", self.gateway_status, methods=["GET"]),
            Route("/api/workbench", self.workbench_payload, methods=["GET"]),
            Route("/bridge/packages/{package_id}/{filename}", self.bridge_package_asset, methods=["GET"]),
            Route("/api/bridge-packages", self.bridge_packages, methods=["GET"]),
        ]

    def home_route(self) -> Route:
        return Route("/", self.home, methods=["GET"])

    def api_fallback_route(self) -> Route:
        return Route("/api/{tail:path}", self.api_fallback, methods=["GET"])

    def static_route(self) -> Route:
        return Route("/{filename}", self.static_asset, methods=["GET"])

    def options_fallback_route(self) -> Route:
        return Route("/{path:path}", self.options_fallback, methods=["OPTIONS"])
