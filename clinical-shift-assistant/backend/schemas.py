from pydantic import BaseModel, Field


class AlertAcknowledgementRequest(BaseModel):
    patient_id: str
    observation_id: str
    rule_id: str


class LoginRequest(BaseModel):
    username: str
    password: str


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    patient_id: str | None = None
