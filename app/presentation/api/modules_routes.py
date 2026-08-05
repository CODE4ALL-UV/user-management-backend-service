from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json
import uuid

router = APIRouter(prefix="/api/modules", tags=["modules"])

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "modules"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class ModulePayload(BaseModel):
    module_id: str | None = None
    name: str | None = None
    topics: list[str] | None = None


@router.post("/", status_code=201)
def create_module(payload: ModulePayload):
    module_id = payload.module_id or str(uuid.uuid4())
    path = UPLOAD_DIR / f"{module_id}.json"
    data = {
        "id": module_id,
        "name": payload.name or "",
        "topics": payload.topics or [],
    }
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data


@router.get("/{module_id}")
def get_module(module_id: str):
    path = UPLOAD_DIR / f"{module_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Module not found")
    return json.loads(path.read_text())


@router.patch("/{module_id}")
def update_module(module_id: str, payload: ModulePayload):
    path = UPLOAD_DIR / f"{module_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Module not found")
    data = json.loads(path.read_text())
    if payload.name is not None:
        data["name"] = payload.name
    if payload.topics is not None:
        data["topics"] = payload.topics
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data
