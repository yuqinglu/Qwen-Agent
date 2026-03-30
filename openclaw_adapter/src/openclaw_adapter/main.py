# -*- coding: utf-8 -*-
"""Application entrypoint."""

import logging
import socket
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from openclaw_adapter import __version__
from openclaw_adapter.api.routes import dev, health, inbound, tasks
from openclaw_adapter.config import get_settings
from openclaw_adapter.constants import API_URL_PREFIX
from openclaw_adapter.db.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_nacos_register_host(bind_host: str) -> str:
    if bind_host != "0.0.0.0":
        return bind_host
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("openclaw-adapter %s DB ready", __version__)

    settings = get_settings()
    app.state.nacos_register_ok = False

    if settings.nacos_enabled:
        from openclaw_adapter.nacos_service import (
            extract_openclaw_adapter_api_routes,
            get_nacos_registry,
            init_nacos_registry,
        )

        registry = init_nacos_registry(
            enabled=True,
            server_addresses=settings.nacos_server_addresses,
            namespace=settings.nacos_namespace,
            username=settings.nacos_username,
            password=settings.nacos_password,
            service_name=settings.nacos_service_name,
            group_name=settings.nacos_group_name,
        )
        if registry:
            reg_host = _resolve_nacos_register_host(settings.host)
            api_routes = extract_openclaw_adapter_api_routes()
            reg_metadata = {
                "version": __version__,
                "service_type": "openclaw-adapter-api",
            }
            reg_metadata.update(settings.parsed_nacos_metadata_extra())
            if registry.register_api_services(
                host=reg_host,
                port=settings.port,
                api_routes=api_routes,
                metadata=reg_metadata,
            ):
                app.state.nacos_register_ok = True
                app.state.nacos_registered_host = reg_host
                app.state.nacos_registered_port = settings.port
                logger.info("Registered with Nacos: %s:%s", reg_host, settings.port)
            else:
                logger.warning("Nacos registration failed; service continues without Nacos")

    try:
        yield
    finally:
        if getattr(app.state, "nacos_register_ok", False):
            reg = get_nacos_registry()
            if reg:
                try:
                    reg.deregister_service(
                        app.state.nacos_registered_host,
                        app.state.nacos_registered_port,
                    )
                    logger.info("Deregistered from Nacos")
                except Exception as e:
                    logger.warning("Nacos deregister error: %s", e)


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenClaw Adapter",
        description="REST bridge: ty-mem-agent ↔ OpenClaw Gateway",
        version=__version__,
        lifespan=lifespan,
    )
    api = APIRouter(prefix=API_URL_PREFIX)
    api.include_router(health.router)
    api.include_router(inbound.router)
    api.include_router(dev.router)
    v1 = APIRouter(prefix="/v1")
    v1.include_router(tasks.router)
    api.include_router(v1)
    app.include_router(api)

    return app


app = create_app()


def run():
    import uvicorn

    s = get_settings()
    uvicorn.run(app, host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    run()
