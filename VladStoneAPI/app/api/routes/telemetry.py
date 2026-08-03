from fastapi import APIRouter, HTTPException, status

from app.api.schemas import ClientEventRequest
from app.core.config import get_settings
from app.services.dev_logging import append_dev_log

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("/client-events")
def log_client_event(payload: ClientEventRequest) -> dict:
    # Это локальный диагностический файл, а не production telemetry pipeline.
    # Внешний сервер не должен принимать произвольный payload и писать его на
    # диск, пока не появится bounded structured telemetry.
    if get_settings().environment != "local":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    append_dev_log(
        "combat-client.jsonl",
        payload.event,
        payload.payload,
    )
    return {"ok": True}
