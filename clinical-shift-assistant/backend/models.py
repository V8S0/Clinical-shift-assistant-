from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    ward: Mapped[str] = mapped_column(String, nullable=False)
    bed: Mapped[str] = mapped_column(String, nullable=False)
    admission_reason: Mapped[str] = mapped_column(Text, nullable=False)
    allergies: Mapped[str] = mapped_column(Text, nullable=False)
    care_notes: Mapped[str] = mapped_column(Text, nullable=False)

    observations: Mapped[list["Observation"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class Observation(Base):
    __tablename__ = "observations"

    observation_id: Mapped[str] = mapped_column(String, primary_key=True)

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False,
    )

    observed_at: Mapped[str] = mapped_column(String, nullable=False)
    heart_rate_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    systolic_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diastolic_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resp_rate_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spo2_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    consciousness: Mapped[str | None] = mapped_column(String, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="observations")


class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False,
    )

    task: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    patient: Mapped["Patient"] = relationship(back_populates="tasks")


class AlertAcknowledgement(Base):
    __tablename__ = "alert_acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False,
    )

    observation_id: Mapped[str] = mapped_column(
        ForeignKey("observations.observation_id"),
        nullable=False,
    )

    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=True)

    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    patient_id: Mapped[str | None] = mapped_column(String, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )