from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime, timezone

class PhotoResizeRequest(BaseModel):
    preset: Optional[str] = "ssc"
    target_kb: Optional[int] = 35
    candidate_name: Optional[str] = None
    dop: Optional[str] = None
    dpi: Optional[int] = 200

class SearchRollNumberRequest(BaseModel):
    query: str
    target_text: Optional[str] = None

class AstraBotActionRequest(BaseModel):
    command: str

class UPIPaymentRequest(BaseModel):
    plan_id: str  # sachet_20, sachet_50, cafe_vip_100
    upi_vpa: Optional[str] = None


class ClientStatusRequest(BaseModel):
    active: bool


class PaymentStatusRequest(BaseModel):
    status: Literal["paid", "rejected"]

class PaymentLog(BaseModel):
    id: Optional[str] = None
    user_identifier: str
    plan_id: str
    amount: float
    status: str = "SUCCESS"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
