# -*- coding: utf-8 -*-
from fastapi import APIRouter

from openclaw_adapter import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "openclaw-adapter", "version": __version__}
