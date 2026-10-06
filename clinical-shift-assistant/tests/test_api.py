import io
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from backend.main import app


def login(client):
    response = client.post('/login', json={'username': 'nurse', 'password': 'Nurse123!'})
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_protected_api_requires_login():
    with TestClient(app) as client:
        response = client.get('/patients')
        assert response.status_code in (401, 403)


def test_filter_and_no_false_alert():
    with TestClient(app) as client:
        headers = login(client)
        patients = client.get('/patients?search=PAT-2001', headers=headers)
        assert patients.status_code == 200
        assert len(patients.json()) == 1
        alerts = client.get('/patients/PAT-2001/alerts', headers=headers)
        assert alerts.status_code == 200
        # The test verifies deterministic evaluation returns a list and never fabricates rules.
        assert all(item['rule_id'].startswith('ESC-') for item in alerts.json())


def test_malformed_import_has_controlled_validation_error():
    with TestClient(app) as client:
        headers = login(client)
        files = {'file': ('bad.json', io.BytesIO(b'{"patient_id":"ONLY-ID"}'), 'application/json')}
        response = client.post('/imports/patients', files=files, headers=headers)
        assert response.status_code == 422
        assert response.json()['detail']['message'] == 'Import validation failed.'


def test_missing_question_warns_without_guessing():
    with TestClient(app) as client:
        headers = login(client)
        response = client.post('/questions', json={
            'patient_id': 'PAT-2001',
            'question': 'What is the patient favourite food?'
        }, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data['exact_match'] is False
        assert data['warning'].startswith('WARNING:')
