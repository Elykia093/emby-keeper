from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import get_current_user
from .kv import kv_store

router = APIRouter(prefix="/kv", tags=["kv"])


class KVSetRequest(BaseModel):
    key: str
    value: Any


class KVUpdateRequest(BaseModel):
    data: Dict[str, Any]


@router.get("")
async def get_all(_user=Depends(get_current_user)) -> Dict[str, Any]:
    return kv_store.all()


@router.get("/{key}")
async def get_value(key: str, _user=Depends(get_current_user)) -> Any:
    if not kv_store.has(key):
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    return {"key": key, "value": kv_store.get(key)}


@router.post("")
async def set_value(req: KVSetRequest, _user=Depends(get_current_user)):
    kv_store.set(req.key, req.value)
    return {"success": True, "key": req.key}


@router.put("")
async def update_values(req: KVUpdateRequest, _user=Depends(get_current_user)):
    kv_store.update(req.data)
    return {"success": True, "updated_keys": list(req.data.keys())}


@router.delete("/{key}")
async def delete_value(key: str, _user=Depends(get_current_user)):
    if not kv_store.delete(key):
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    return {"success": True, "key": key}


@router.delete("")
async def clear_all(_user=Depends(get_current_user)):
    kv_store.clear()
    return {"success": True}
