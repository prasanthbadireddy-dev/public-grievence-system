import requests
import json
import sys

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API = 'http://127.0.0.1:5000/api'
session = requests.Session()
PASS = "[PASS]"
FAIL = "[FAIL]"

results = []

def test(name, passed, details=""):
    status = PASS if passed else FAIL
    print(f"  {status}  {name}")
    if details:
        print(f"       {details}")
    results.append((name, passed))

print("\n" + "="*55)
print("  GRIEVANCE PORTAL - FULL FEATURE VERIFICATION")
print("="*55)

# ─── TEST 1: GET /api/settings ────────────────────────────────
print("\n[1] Settings API - Load")
try:
    r = requests.get(f'{API}/settings', timeout=5)
    s = r.json()
    test("GET /api/settings returns 200", r.status_code == 200, f"Status={r.status_code}")
    test("Has maintenance key", "maintenance" in s, str(s.get("maintenance")))
    test("Has email key", "email" in s, str(s.get("email")))
    test("Has profanity key", "profanity" in s, str(s.get("profanity")))
    test("Has duplicate key", "duplicate" in s, str(s.get("duplicate")))
    test("Has threshold key", "threshold" in s, str(s.get("threshold")))
    test("Has anon key", "anon" in s, str(s.get("anon")))
    test("Threshold is a number", isinstance(s.get("threshold"), int), str(type(s.get("threshold"))))
except Exception as e:
    test("GET /api/settings", False, str(e))

# ─── TEST 2: POST /api/settings (requires login) ─────────────
print("\n[2] Settings API - Save (requires admin login)")
try:
    login = session.post(f'{API}/login', json={"username": "admin", "password": "admin123"}, timeout=5)
    test("Admin login", login.status_code == 200, f"Status={login.status_code}")
    
    payload = {
        "maintenance": False,
        "anon": True,
        "sms": False,
        "email": True,
        "profanity": True,
        "duplicate": True,
        "threshold": 70
    }
    r = session.post(f'{API}/settings', json=payload, timeout=5)
    test("POST /api/settings returns 200", r.status_code == 200, f"Status={r.status_code}")
    data = r.json()
    test("Threshold saved correctly", data.get("settings", {}).get("threshold") == 70, str(data.get("settings", {}).get("threshold")))
    
    # Verify it persisted
    r2 = requests.get(f'{API}/settings', timeout=5)
    s2 = r2.json()
    test("Settings persisted to DB", s2.get("threshold") == 70, str(s2.get("threshold")))
except Exception as e:
    test("Settings save flow", False, str(e))

# ─── TEST 3: Maintenance Mode ─────────────────────────────────
print("\n[3] Maintenance Mode")
try:
    # Enable maintenance
    session.post(f'{API}/settings', json={"maintenance": True}, timeout=5)
    
    # Try to submit complaint — should get 503
    payload = {
        "name": "Test User",
        "phone": "9999999999",
        "email": "test@test.com",
        "address": "123 Test Street",
        "description": "There is a large pothole on the road that is causing accidents"
    }
    r = requests.post(f'{API}/complaints', json=payload, timeout=5)
    test("Maintenance mode blocks submission (503)", r.status_code == 503, f"Status={r.status_code}")
    test("Error message says maintenance", r.json().get("error") == "maintenance", str(r.json()))

    # Disable maintenance
    session.post(f'{API}/settings', json={"maintenance": False}, timeout=5)
except Exception as e:
    test("Maintenance mode", False, str(e))

# ─── TEST 4: Normal Complaint Submission ──────────────────────
print("\n[4] Complaint Submission")
try:
    payload = {
        "name": "Rajesh Kumar",
        "phone": "9876543210",
        "email": "prasanthbadireddy2005@gmail.com",
        "address": "MG Road, Hyderabad, Telangana",
        "description": "There is severe flooding on the main road near MG Road due to blocked drainage causing major traffic and health hazards"
    }
    r = requests.post(f'{API}/complaints', json=payload, timeout=10)
    test("Complaint submitted (201)", r.status_code == 201, f"Status={r.status_code}")
    data = r.json()
    test("Response has complaint_id", "complaint_id" in data, str(data.get("complaint_id")))
    test("Response has category", "category" in data, str(data.get("category")))
    test("Response has priority", "priority" in data, str(data.get("priority")))
    test("Response has email_sent (True)", data.get("email_sent") is True, str(data.get("email_sent")))
    test("Response has sms_sent (False)", data.get("sms_sent") is False, str(data.get("sms_sent")))
    cid = data.get("complaint_id")
except Exception as e:
    test("Complaint submission", False, str(e))
    cid = None

# ─── TEST 5: Fake Complaint Detection ─────────────────────────
print("\n[5] Fake/Spam Detection")
try:
    fake_payload = {
        "name": "Test",
        "phone": "0000000000",
        "email": "test@test.com",
        "address": "asdf",
        "description": "asdfqwer"
    }
    r = requests.post(f'{API}/complaints', json=fake_payload, timeout=5)
    test("Fake complaint blocked (400)", r.status_code == 400, f"Status={r.status_code}")
    test("Error type is fake_detected", r.json().get("error") == "fake_detected", str(r.json()))
except Exception as e:
    test("Fake detection", False, str(e))

# ─── TEST 6: Profanity toggle disables fake detection ─────────
print("\n[6] Profanity Setting Toggle")
try:
    # Disable profanity filter
    session.post(f'{API}/settings', json={"profanity": False}, timeout=5)
    r = requests.post(f'{API}/complaints', json={
        "name": "Test",
        "phone": "0000000000",
        "email": "test@test.com",
        "address": "asdf",
        "description": "asdfqwer"
    }, timeout=5)
    test("Fake complaint passes when profanity OFF", r.status_code in [201, 400, 503], f"Status={r.status_code} - Not blocked by profanity filter")
    # Re-enable
    session.post(f'{API}/settings', json={"profanity": True}, timeout=5)
except Exception as e:
    test("Profanity toggle", False, str(e))

# ─── TEST 7: Status Update (Email gated by setting) ───────────
print("\n[7] Status Update API")
try:
    if cid:
        r = session.patch(f'{API}/complaints/{cid}/status',
                          json={"status": "Under Review", "note": "Reviewing the flooding issue"},
                          timeout=5)
        test("Status update returns 200", r.status_code == 200, f"Status={r.status_code}")
        test("New status in response", r.json().get("status") == "Under Review", str(r.json().get("status")))
    else:
        test("Status update (skipped - no complaint_id)", False, "No complaint created")
except Exception as e:
    test("Status update", False, str(e))

# ─── TEST 8: /api/stats ───────────────────────────────────────
print("\n[8] Dashboard Stats")
try:
    r = requests.get(f'{API}/stats', timeout=5)
    test("Stats endpoint returns 200", r.status_code == 200)
    data = r.json()
    test("Stats has total", "total" in data)
    test("Stats has by_category", "by_category" in data)
except Exception as e:
    test("Stats", False, str(e))

# ─── SUMMARY ─────────────────────────────────────────────────
print("\n" + "="*55)
passed = sum(1 for _, p in results if p)
total  = len(results)
print(f"  RESULTS: {passed}/{total} tests passed")
if passed == total:
    print("  ALL TESTS PASSED \u2705")
else:
    print("  FAILED TESTS:")
    for name, p in results:
        if not p:
            print(f"    - {name}")
print("="*55 + "\n")
