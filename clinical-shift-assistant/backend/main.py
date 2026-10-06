from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.ai_service import (
    SAFETY_NOTICE,
    answer_question,
    generate_patient_summary,
    generate_sbar,
    patient_facts,
    prioritise_tasks,
)
from backend.alert_service import evaluate_observation
from backend.auth import authenticate_user, logout_user, verify_session
from backend.database import Base, SessionLocal, engine, get_db
from backend.import_service import (
    ImportValidationError,
    parse_patient_upload,
    save_imported_patients,
    seed_database,
)
from backend.models import AlertAcknowledgement, AuditLog, Observation, Patient, Task
from backend.schemas import AlertAcknowledgementRequest, LoginRequest, QuestionRequest

app = FastAPI(title="AI Clinical Shift Assistant", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] ,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


def latest_observation(db: Session, patient_id: str):
    return (
        db.query(Observation)
        .filter(Observation.patient_id == patient_id)
        .order_by(Observation.observed_at.desc())
        .first()
    )


def active_alerts(db: Session, patient_id: str, include_acknowledged: bool = False):
    observation = latest_observation(db, patient_id)
    if observation is None:
        return []
    alerts = []
    for alert in evaluate_observation(observation):
        ack = (
            db.query(AlertAcknowledgement)
            .filter(
                AlertAcknowledgement.patient_id == patient_id,
                AlertAcknowledgement.observation_id == observation.observation_id,
                AlertAcknowledgement.rule_id == alert["rule_id"],
            )
            .first()
        )
        enriched = {
            **alert,
            "observation_id": observation.observation_id,
            "observed_at": observation.observed_at,
            "acknowledged": ack is not None,
            "acknowledged_at": ack.acknowledged_at if ack else None,
        }
        if include_acknowledged or ack is None:
            alerts.append(enriched)
    return alerts


def patient_bundle(db: Session, patient_id: str):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(404, "Patient not found")
    observation = latest_observation(db, patient_id)
    tasks = db.query(Task).filter(Task.patient_id == patient_id).all()
    alerts = active_alerts(db, patient_id, include_acknowledged=True)
    return patient, observation, tasks, alerts


@app.post("/login")
def login(request: LoginRequest):
    return {
        "message": "Login successful.",
        "access_token": authenticate_user(request.username, request.password),
        "token_type": "bearer",
    }


@app.post("/logout")
def logout(token: str = Depends(verify_session)):
    logout_user(token)
    return {"message": "Logout successful."}


@app.get("/")
def root():
    return {"message": "AI Clinical Shift Assistant API is running.", "safety_notice": SAFETY_NOTICE}


@app.get("/patients")
def get_patients(
    search: str | None = Query(default=None, max_length=100),
    ward: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    _: str = Depends(verify_session),
):
    query = db.query(Patient)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(
            Patient.patient_id.ilike(pattern),
            Patient.display_name.ilike(pattern),
            Patient.bed.ilike(pattern),
            Patient.admission_reason.ilike(pattern),
        ))
    if ward:
        query = query.filter(Patient.ward.ilike(ward.strip()))
    patients = query.order_by(Patient.ward, Patient.bed).all()
    result = []
    for patient in patients:
        alerts = active_alerts(db, patient.patient_id)
        result.append({
            "patient_id": patient.patient_id,
            "display_name": patient.display_name,
            "age": patient.age,
            "ward": patient.ward,
            "bed": patient.bed,
            "admission_reason": patient.admission_reason,
            "allergies": patient.allergies,
            "care_notes": patient.care_notes,
            "escalated": bool(alerts),
            "alerts": alerts,
        })
    return result


@app.get("/patients/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient


@app.post("/imports/patients")
async def import_patients(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(verify_session),
):
    content = await file.read()
    if len(content) > 1_000_000:
        raise HTTPException(413, "Import file must be 1 MB or smaller.")
    try:
        records = parse_patient_upload(file.filename or "", content)
        count = save_imported_patients(db, records)
    except ImportValidationError as exc:
        raise HTTPException(422, {"message": "Import validation failed.", "records": exc.errors})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.add(AuditLog(action_type="patient_import", details=f"Imported {count} patient record(s) from {file.filename}."))
    db.commit()
    return {"message": "Import successful.", "imported": count, "filename": file.filename}


@app.get("/patients/{patient_id}/observations")
def get_patient_observations(patient_id: str, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return (
        db.query(Observation)
        .filter(Observation.patient_id == patient_id)
        .order_by(Observation.observed_at.desc())
        .all()
    )


@app.get("/patients/{patient_id}/tasks")
def get_patient_tasks(patient_id: str, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(404, "Patient not found")
    return db.query(Task).filter(Task.patient_id == patient_id).order_by(Task.due_at).all()


@app.patch("/tasks/{task_id}/complete")
def complete_task(task_id: str, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    task.status = "completed"
    task.updated_at = datetime.now(timezone.utc)
    audit = AuditLog(
        action_type="task_completed", patient_id=task.patient_id, task_id=task.task_id,
        details=f"Task {task.task_id} marked as completed at {task.updated_at.isoformat()}.",
    )
    db.add(audit)
    db.commit()
    db.refresh(task)
    return {"message": "Task completed successfully.", "task_id": task.task_id, "status": task.status, "updated_at": task.updated_at}


@app.get("/patients/{patient_id}/alerts")
def get_patient_alerts(
    patient_id: str,
    include_acknowledged: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(verify_session),
):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(404, "Patient not found")
    return active_alerts(db, patient_id, include_acknowledged)


@app.post("/alerts/acknowledge")
def acknowledge_alert(request: AlertAcknowledgementRequest, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    observation = db.get(Observation, request.observation_id)
    if observation is None or observation.patient_id != request.patient_id:
        raise HTTPException(404, "Observation not found for this patient")
    matching = next((a for a in evaluate_observation(observation) if a["rule_id"] == request.rule_id), None)
    if matching is None:
        raise HTTPException(400, "The supplied rule is not active for this observation")
    existing = (
        db.query(AlertAcknowledgement)
        .filter(
            AlertAcknowledgement.patient_id == request.patient_id,
            AlertAcknowledgement.observation_id == request.observation_id,
            AlertAcknowledgement.rule_id == request.rule_id,
        ).first()
    )
    if existing:
        return {"message": "Alert was already acknowledged.", "acknowledgement_id": existing.id, "acknowledged_at": existing.acknowledged_at}
    acknowledgement = AlertAcknowledgement(
        patient_id=request.patient_id, observation_id=request.observation_id, rule_id=request.rule_id
    )
    db.add(acknowledgement)
    db.flush()
    db.add(AuditLog(
        action_type="alert_acknowledged", patient_id=request.patient_id,
        details=f"Alert {request.rule_id} acknowledged for observation {request.observation_id}.",
    ))
    db.commit()
    db.refresh(acknowledgement)
    return {"message": "Alert acknowledged successfully.", "acknowledgement_id": acknowledgement.id, "acknowledged_at": acknowledgement.acknowledged_at}


@app.get("/patients/{patient_id}/summary")
def get_patient_summary(patient_id: str, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    patient, observation, tasks, alerts = patient_bundle(db, patient_id)
    result = generate_patient_summary(patient, observation, tasks, alerts)
    return {**result, "safety_notice": SAFETY_NOTICE}


@app.get("/patients/{patient_id}/sbar")
def get_patient_sbar(patient_id: str, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    patient, observation, tasks, alerts = patient_bundle(db, patient_id)
    return {**generate_sbar(patient, observation, tasks, alerts), "safety_notice": SAFETY_NOTICE}


@app.post("/questions")
def ask_question(request: QuestionRequest, db: Session = Depends(get_db), _: str = Depends(verify_session)):
    if request.patient_id:
        patient, observation, tasks, alerts = patient_bundle(db, request.patient_id)
        records = patient_facts(patient, observation, tasks, alerts)
        return {**answer_question(request.question, records), "scope": request.patient_id, "safety_notice": SAFETY_NOTICE}
    patients = db.query(Patient).order_by(Patient.patient_id).all()
    ward_records = {
        "tasks": [], "alerts": [],
        "admission_reason": f"Ward list contains {len(patients)} patients [patients endpoint].",
        "care_notes": [],
    }
    for patient in patients:
        obs = latest_observation(db, patient.patient_id)
        tasks = db.query(Task).filter(Task.patient_id == patient.patient_id).all()
        facts = patient_facts(patient, obs, tasks, active_alerts(db, patient.patient_id, True))
        ward_records["tasks"].extend(facts["tasks"])
        ward_records["alerts"].extend(facts["alerts"])
        ward_records["care_notes"].append(f"{patient.display_name}: {facts['care_notes']}")
    return {**answer_question(request.question, ward_records), "scope": "ward", "safety_notice": SAFETY_NOTICE}


@app.get("/tasks/prioritised")
def get_prioritised_tasks(db: Session = Depends(get_db), _: str = Depends(verify_session)):
    tasks = db.query(Task).all()
    patient_ids = {task.patient_id for task in tasks}
    alerts_by_patient = {pid: active_alerts(db, pid, include_acknowledged=True) for pid in patient_ids}
    return {"tasks": prioritise_tasks(tasks, alerts_by_patient), "method": "Deterministic ordering by supplied rule severity, task urgency, and due time; AI wording does not create thresholds."}


@app.get("/audit-log")
def get_audit_log(db: Session = Depends(get_db), _: str = Depends(verify_session)):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).all()
