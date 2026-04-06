# -*- coding: utf-8 -*-
from fastapi import Header, HTTPException

from openclaw_adapter.config import get_settings


async def verify_adapter_api_key(authorization: str | None = Header(None)) -> None:
    settings = get_settings()
    key = settings.adapter_api_key
    if not key:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[7:].strip()
    if token != key:
        raise HTTPException(status_code=401, detail="invalid api key")
