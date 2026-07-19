from typing import Any

from pydantic import BaseModel, EmailStr, Field


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeResponse(BaseModel):
    ok: bool
    dev_code: str | None = None


class EmailVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class GoogleDevLoginRequest(BaseModel):
    email: EmailStr
    name: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    user: dict


class AscendCardRequest(BaseModel):
    ascension: str = "default"


class PlacementRequest(BaseModel):
    card_id: str
    row: int
    col: int


class SpellRequest(BaseModel):
    card_id: str
    # Точка применения; None — для заклинаний на всё поле (scope=board).
    row: int | None = None
    col: int | None = None


class ResolveTurnRequest(BaseModel):
    match_id: str
    turn: int = Field(ge=1)
    placements: list[PlacementRequest] = Field(default_factory=list)
    spells: list[SpellRequest] = Field(default_factory=list)


class ReadyTurnRequest(ResolveTurnRequest):
    """V3: готовность к резолву; несёт и финальный план (атомарно с флагом)."""

    ready: bool = True


class ClientEventRequest(BaseModel):
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
