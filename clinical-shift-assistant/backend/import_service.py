import csv
import io
import json
from pathlib import Path

from pydantic import BaseModel, ValidationError, Field
from sqlalchemy.orm import Session

from backend.models import Patient, Observation, Task

DATA_FOLDER = Path(__file__).resolve().parents[1] / "data"


class PatientImport(BaseModel):
    patient_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    age: int = Field(ge=0, le=130)
    ward: str = Field(min_length=1)
    bed: str = Field(min_length=1)
    admission_reason: str = Field(min_length=1)
    allergies: str = Field(min_length=1)
    care_notes: str = Field(min_length=1)


def seed_database(db: Session):
    if db.query(Patient).count() > 0:
        return
    with (DATA_FOLDER / "patients.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            db.add(Patient(**PatientImport.model_validate(row).model_dump()))
    db.flush()
    with (DATA_FOLDER / "observations.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            db.add(Observation(
                observation_id=row["observation_id"], patient_id=row["patient_id"], observed_at=row["observed_at"],
                heart_rate_bpm=int(row["heart_rate_bpm"]) if row["heart_rate_bpm"] else None,
                systolic_bp=int(row["systolic_bp"]) if row["systolic_bp"] else None,
                diastolic_bp=int(row["diastolic_bp"]) if row["diastolic_bp"] else None,
                resp_rate_min=int(row["resp_rate_min"]) if row["resp_rate_min"] else None,
                spo2_percent=int(row["spo2_percent"]) if row["spo2_percent"] else None,
                temperature_c=float(row["temperature_c"]) if row["temperature_c"] else None,
                consciousness=row["consciousness"] or None,
            ))
    with (DATA_FOLDER / "tasks.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            db.add(Task(**row))
    db.commit()


def parse_patient_upload(filename: str, content: bytes):
    suffix = Path(filename or "").suffix.lower()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("File must use UTF-8 encoding.") from exc
    try:
        if suffix == ".json":
            raw = json.loads(text)
            records = raw if isinstance(raw, list) else [raw]
        elif suffix == ".csv":
            records = list(csv.DictReader(io.StringIO(text)))
        else:
            raise ValueError("Only .csv and .json patient files are supported.")
    except (json.JSONDecodeError, csv.Error) as exc:
        raise ValueError(f"Malformed {suffix[1:].upper()} file.") from exc
    if not records:
        raise ValueError("The import file contains no records.")
    valid, errors = [], []
    for index, record in enumerate(records, start=1):
        try:
            valid.append(PatientImport.model_validate(record))
        except ValidationError as exc:
            errors.append({"record": index, "errors": exc.errors(include_url=False)})
    if errors:
        raise ImportValidationError(errors)
    return valid


class ImportValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors


def save_imported_patients(db: Session, records):
    duplicates = [r.patient_id for r in records if db.get(Patient, r.patient_id)]
    if duplicates:
        raise ValueError("Patient ID already exists: " + ", ".join(duplicates))
    for record in records:
        db.add(Patient(**record.model_dump()))
    db.commit()
    return len(records)
