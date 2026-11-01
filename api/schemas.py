from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PredictRequest(BaseModel):
    transaction_id: int = Field(..., gt=0, le=2_147_483_647, description="Existing transaction ID (positive integer)")


class PredictResponse(BaseModel):
    prediction_id: int
    transaction_id: int
    prediction: int
    result: Literal["Fraud", "Legitimate"]
    fraud_probability: float
    risk_level: Literal["Low", "Medium", "High"]
    threshold: float
    model: str
    model_version: str
    latency_ms: float


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int


class TransactionRow(BaseModel):
    transaction_id: int
    amount: float
    fraud_probability: float
    risk_level: Literal["Low", "Medium", "High"]
    predicted_class: int
    actual_class: int | None
    model_version: str | None
    source: str | None
    status: str
    processed_at: datetime | None
    latency_ms: float | None
