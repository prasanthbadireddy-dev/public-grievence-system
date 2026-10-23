import email_service
import sys
import logging

logging.basicConfig(level=logging.INFO)

dummy_complaint = {
    "complaint_id": "TEST-12345",
    "name": "Test User",
    "email": "prasanthbadireddy2005@gmail.com",
    "description": "This is a test complaint to verify if the automated email system is working properly.",
    "category": "Test Category",
    "priority": "Low",
    "department": "Test Department",
    "status": "Registered",
    "created_at": "2026-07-09T16:35:00Z"
}

try:
    print("Attempting to send test registration email...")
    email_service.send_registration_email(dummy_complaint)
    print("Test email sent successfully!")
except Exception as e:
    print(f"Failed to send email: {e}")
    sys.exit(1)
