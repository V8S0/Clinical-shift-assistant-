"""Grounded AI orchestration.

Amazon Bedrock is used when BEDROCK_MODEL_ID is configured and AWS credentials are
available. A deterministic grounded fallback keeps the local PoC usable without
network access. In both modes, facts are assembled from database records first.
"""
import json
import os
from datetime import datetime

SAFETY_NOTICE = (
    "Synthetic-data prototype. Verify all information using approved clinical "
    "systems and processes. This tool does not provide diagnosis, treatment or "
    "medication advice."
)


def _value(value):
    return "not recorded" if value is None or value == "" else str(value)


def _bedrock_text(prompt: str) -> tuple[str | None, str]:
    model_id = os.getenv("BEDROCK_MODEL_ID", "").strip()
    if not model_id:
        return None, "grounded-local-fallback"
    try:
        import boto3
        client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        response = client.converse(
            modelId=model_id,
            system=[{"text": (
                "Use only the supplied synthetic record facts. Do not diagnose, "
                "prescribe, calculate doses, create thresholds, or invent facts. "
                "Preserve record citations exactly."
            )}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 700, "temperature": 0.0},
        )
        return response["output"]["message"]["content"][0]["text"], "amazon-bedrock"
    except Exception:
        return None, "grounded-local-fallback"


def patient_facts(patient, observation, tasks, alerts):
    obs_cite = (
        f"[observation:{observation.observation_id} at {observation.observed_at}]"
        if observation else "[no observation recorded]"
    )
    facts = {
        "identity": f"{patient.display_name}, age {patient.age} [patient:{patient.patient_id} fields:display_name,age]",
        "location": f"Ward {patient.ward}, bed {patient.bed} [patient:{patient.patient_id} fields:ward,bed]",
        "admission_reason": f"{patient.admission_reason} [patient:{patient.patient_id} field:admission_reason]",
        "allergies": f"{patient.allergies} [patient:{patient.patient_id} field:allergies]",
        "care_notes": f"{patient.care_notes} [patient:{patient.patient_id} field:care_notes]",
    }
    if observation:
        facts.update({
            "heart_rate": f"{_value(observation.heart_rate_bpm)} bpm {obs_cite}",
            "blood_pressure": f"{_value(observation.systolic_bp)}/{_value(observation.diastolic_bp)} mmHg {obs_cite}",
            "respiratory_rate": f"{_value(observation.resp_rate_min)} /min {obs_cite}",
            "oxygen_saturation": f"{_value(observation.spo2_percent)}% {obs_cite}",
            "temperature": f"{_value(observation.temperature_c)} C {obs_cite}",
            "consciousness": f"{_value(observation.consciousness)} {obs_cite}",
        })
    facts["tasks"] = [
        f"{t.task} (status {t.status}, due {t.due_at}) [task:{t.task_id} at {t.due_at}]"
        for t in tasks
    ]
    facts["alerts"] = [
        f"{a['message']} - rule {a['rule_id']} triggered by {a['field']}={a['value']} "
        f"[observation:{a['observation_id']} at {a['observed_at']}]"
        for a in alerts
    ]
    return facts


def generate_patient_summary(patient, observation, tasks, alerts):
    facts = patient_facts(patient, observation, tasks, alerts)
    pending = [t for t in tasks if t.status.lower() != "completed"]
    alert_text = "; ".join(facts["alerts"]) if facts["alerts"] else "No current rule-triggered alert."
    local = (
        f"{facts['identity']} is in {facts['location']} and was admitted for "
        f"{facts['admission_reason']}. Allergies: {facts['allergies']}. "
        f"Latest recorded observations: temperature {facts.get('temperature', 'not recorded')}, "
        f"heart rate {facts.get('heart_rate', 'not recorded')}, SpO2 "
        f"{facts.get('oxygen_saturation', 'not recorded')}. {alert_text} "
        f"Pending tasks: {len(pending)}."
    )
    prompt = "Create a concise shift summary from this JSON. Keep every citation.\n" + json.dumps(facts)
    generated, provider = _bedrock_text(prompt)
    return {"summary": generated or local, "provider": provider, "citations": facts}


def generate_sbar(patient, observation, tasks, alerts):
    facts = patient_facts(patient, observation, tasks, alerts)
    pending = facts["tasks"] or ["No supplied tasks recorded."]
    alert_text = facts["alerts"] or ["No latest observation meets a supplied escalation threshold."]
    sbar = {
        "situation": f"{facts['identity']}; {facts['location']}; admitted for {facts['admission_reason']}.",
        "background": f"Allergies: {facts['allergies']}. Care notes: {facts['care_notes']}.",
        "assessment": (
            f"Latest recorded values: HR {facts.get('heart_rate', 'not recorded')}; "
            f"BP {facts.get('blood_pressure', 'not recorded')}; RR {facts.get('respiratory_rate', 'not recorded')}; "
            f"SpO2 {facts.get('oxygen_saturation', 'not recorded')}; temperature {facts.get('temperature', 'not recorded')}. "
            + " Alerts: " + " ".join(alert_text)
        ),
        "recommendation": "Review supplied pending nursing tasks: " + " ".join(pending),
    }
    prompt = "Format this grounded JSON as SBAR without adding advice or facts. Preserve citations.\n" + json.dumps(sbar)
    generated, provider = _bedrock_text(prompt)
    return {"sbar": generated or sbar, "provider": provider}


def answer_question(question, records):
    q = question.lower()
    field_map = {
        "allerg": "allergies", "admission": "admission_reason", "why": "admission_reason",
        "care note": "care_notes", "heart": "heart_rate", "pulse": "heart_rate",
        "blood pressure": "blood_pressure", "bp": "blood_pressure", "resp": "respiratory_rate",
        "oxygen": "oxygen_saturation", "spo2": "oxygen_saturation", "temperature": "temperature",
        "conscious": "consciousness", "task": "tasks", "alert": "alerts", "ward": "location", "bed": "location",
    }
    selected = None
    for term, field in field_map.items():
        if term in q:
            selected = field
            break
    if selected and records.get(selected):
        value = records[selected]
        if isinstance(value, list):
            answer = " ".join(value) if value else "No matching records are supplied."
        else:
            answer = str(value)
        return {"answer": answer, "exact_match": True, "warning": None, "provider": "grounded-record-retrieval"}

    related = []
    for field in ("admission_reason", "care_notes", "tasks", "alerts"):
        value = records.get(field)
        if value:
            related.extend(value if isinstance(value, list) else [value])
    return {
        "answer": " ".join(related[:3]) or "No related recorded information is available.",
        "exact_match": False,
        "warning": "WARNING: The exact answer is not present in the supplied records. Only the closest related recorded information is shown; no facts were guessed.",
        "provider": "grounded-record-retrieval",
    }


def prioritise_tasks(tasks, alerts_by_patient):
    severity_score = {"critical": 3, "high": 3, "medium": 2, "warning": 2, "low": 1}
    now = datetime.now().astimezone()
    rows = []
    for task in tasks:
        if task.status.lower() == "completed":
            continue
        try:
            due = datetime.fromisoformat(task.due_at.replace("Z", "+00:00"))
            due_cmp = due if due.tzinfo else due.replace(tzinfo=now.tzinfo)
            minutes = int((due_cmp - now).total_seconds() / 60)
        except ValueError:
            minutes = 999999
        patient_alerts = alerts_by_patient.get(task.patient_id, [])
        max_severity = max((severity_score.get(a["severity"].lower(), 1) for a in patient_alerts), default=0)
        urgency = 2 if minutes <= 0 else 1 if minutes <= 60 else 0
        rows.append((-(max_severity), -urgency, minutes, task, patient_alerts))
    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3].task_id))
    result = []
    for rank, (_, _, minutes, task, alerts) in enumerate(rows, 1):
        alert_reason = (
            f"triggered severity {max(a['severity'] for a in alerts)} via rule(s) {', '.join(a['rule_id'] for a in alerts)}"
            if alerts else "no triggered escalation rule"
        )
        due_reason = "overdue" if minutes <= 0 else f"due in approximately {minutes} minutes"
        result.append({
            "rank": rank, "task_id": task.task_id, "patient_id": task.patient_id,
            "task": task.task, "due_at": task.due_at, "status": task.status,
            "explanation": f"Ordered using alert severity first, then urgency and due time: {alert_reason}; {due_reason}."
        })
    return result
