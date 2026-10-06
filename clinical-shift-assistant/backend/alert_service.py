import json
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parents[1] / "data" / "escalation_rules.json"


def load_rules():
    with RULES_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def evaluate_observation(observation):
    alerts = []
    for rule in load_rules():
        value = getattr(observation, rule["field"], None)
        if value is None:
            continue
        operator = rule["operator"]
        threshold = rule["threshold"]
        triggered = (operator == ">=" and value >= threshold) or (
            operator == "<=" and value <= threshold
        )
        if triggered:
            alerts.append({
                "rule_id": rule["rule_id"],
                "field": rule["field"],
                "severity": rule["severity"],
                "message": rule["message"],
                "value": value,
                "operator": operator,
                "threshold": threshold,
            })
    return alerts
