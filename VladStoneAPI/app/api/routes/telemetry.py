from fastapi import APIRouter

from app.api.schemas import ClientEventRequest
from app.services.dev_logging import append_dev_log

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("/client-events")
def log_client_event(payload: ClientEventRequest) -> dict:
    append_dev_log(
        "combat-client.jsonl",
        payload.event,
        payload.payload,
    )
    return {"ok": True}
