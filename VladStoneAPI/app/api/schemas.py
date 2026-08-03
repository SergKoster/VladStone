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


class PlacementRequest(BaseModel):
    card_id: str = Field(min_length=1, max_length=64)
    row: int = Field(ge=0, lt=5)
    col: int = Field(ge=0, lt=5)


class SpellRequest(BaseModel):
    card_id: str = Field(min_length=1, max_length=64)
    # Точка применения; None — для заклинаний на всё поле (scope=board).
    row: int | None = Field(default=None, ge=0, lt=5)
    col: int | None = Field(default=None, ge=0, lt=5)


class ResolveTurnRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=96)
    turn: int = Field(ge=1)
    # Рука v4 ограничена шестью картами; больше намерений не может быть
    # легальным и не должно доходить до доменного резолвера.
    placements: list[PlacementRequest] = Field(default_factory=list, max_length=6)
    spells: list[SpellRequest] = Field(default_factory=list, max_length=6)


class ReadyTurnRequest(ResolveTurnRequest):
    """V3: готовность к резолву; несёт и финальный план (атомарно с флагом)."""

    ready: bool = True


class JoinMatchInviteRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class ClientEventRequest(BaseModel):
    event: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict, max_length=24)
