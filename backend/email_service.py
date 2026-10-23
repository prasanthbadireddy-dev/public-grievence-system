import os
import smtplib
import qrcode
import base64
import logging
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from dotenv import load_dotenv
from jinja2 import Template

# Load environment variables from .env
load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD", "")

logger = logging.getLogger("email_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# -----------------
# Email Templates
# -----------------

REGISTRATION_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; }
        .container { max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }
        .header { background-color: #002046; color: #fff; padding: 20px; text-align: center; }
        .header h2 { margin: 0; font-size: 24px; }
        .content { padding: 30px; background-color: #f9fbfd; }
        .details-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .details-table th, .details-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .details-table th { width: 40%; color: #002046; }
        .btn { display: inline-block; padding: 12px 24px; background-color: #155fa8; color: #fff; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 20px; text-align: center;}
        .footer { background-color: #f1f1f1; color: #666; font-size: 12px; text-align: center; padding: 15px; }
        .qr-container { text-align: center; margin-top: 20px; }
        .qr-container p { font-size: 12px; color: #777; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Grievance Registered Successfully</h2>
        </div>
        <div class="content">
            <p>Dear <strong>{{ name }}</strong>,</p>
            <p>Your grievance has been successfully submitted and logged into our system. Please find the details below:</p>
            
            <table class="details-table">
                <tr><th>Complaint ID</th><td><strong>{{ complaint_id }}</strong></td></tr>
                <tr><th>Category</th><td>{{ category }}</td></tr>
                <tr><th>Priority</th><td>{{ priority }}</td></tr>
                <tr><th>Assigned Department</th><td>{{ department }}</td></tr>
                <tr><th>Date & Time</th><td>{{ created_at }}</td></tr>
                <tr><th>Status</th><td><span style="color: #2196f3; font-weight: bold;">{{ status }}</span></td></tr>
                <tr><th>Summary</th><td>{{ summary }}...</td></tr>
            </table>

            <div style="text-align: center;">
                <a href="{{ track_url }}" class="btn">Track Complaint</a>
            </div>

            <div class="qr-container">
                <p>Scan to track status on mobile:</p>
                <img src="cid:qrcode_img" alt="Track QR Code" width="150" height="150">
            </div>
        </div>
        <div class="footer">
            <p>Public Grievance Portal - Government of Information Technology</p>
            <p>If you have any questions, please contact our support team.</p>
            <p>This is an automated message. Please do not reply.</p>
        </div>
    </div>
</body>
</html>
"""

STATUS_UPDATE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; }
        .container { max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }
        .header { background-color: #155fa8; color: #fff; padding: 20px; text-align: center; }
        .header h2 { margin: 0; font-size: 24px; }
        .content { padding: 30px; background-color: #f9fbfd; }
        .details-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .details-table th, .details-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .details-table th { width: 35%; color: #002046; }
        .note-box { background-color: #fff3cd; color: #856404; padding: 15px; border-left: 4px solid #ffeeba; margin-top: 20px; }
        .btn { display: inline-block; padding: 12px 24px; background-color: #155fa8; color: #fff; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 20px; text-align: center;}
        .footer { background-color: #f1f1f1; color: #666; font-size: 12px; text-align: center; padding: 15px; }
        .qr-container { text-align: center; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Complaint Status Updated</h2>
        </div>
        <div class="content">
            <p>Dear Citizen,</p>
            <p>There is an update regarding your complaint <strong>{{ complaint_id }}</strong>.</p>
            
            <table class="details-table">
                <tr><th>New Status</th><td><strong style="color: #e65100;">{{ status }}</strong></td></tr>
                <tr><th>Updated On</th><td>{{ updated_at }}</td></tr>
            </table>

            {% if note %}
            <div class="note-box">
                <strong>Officer Remarks:</strong><br>
                {{ note }}
            </div>
            {% endif %}

            <div style="text-align: center;">
                <a href="{{ track_url }}" class="btn">Track Complaint</a>
            </div>

            <div class="qr-container">
                <img src="cid:qrcode_img" alt="Track QR Code" width="120" height="120">
            </div>
        </div>
        <div class="footer">
            <p>Public Grievance Portal</p>
        </div>
    </div>
</body>
</html>
"""

def generate_qr_code(url: str) -> bytes:
    """Generate a QR code for the given URL and return it as PNG bytes."""
    qr = qrcode.QRCode(version=1, box_size=5, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_io = BytesIO()
    img.save(img_io, 'PNG')
    return img_io.getvalue()

def render_email_template(template_str: str, **kwargs) -> str:
    """Render a Jinja2 template with provided arguments."""
    template = Template(template_str)
    return template.render(**kwargs)

def send_email_with_qr(to_email: str, subject: str, html_content: str, qr_code_bytes: bytes):
    """Core function to send HTML email with embedded QR code using SMTP."""
    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        logger.error("SMTP credentials not configured. Skipping email.")
        return False
        
    try:
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From'] = f"Grievance Portal <{SMTP_EMAIL}>"
        msg['To'] = to_email

        # Attach HTML content
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_text = MIMEText("Please view this email in an HTML-compatible client.", 'plain')
        msg_html = MIMEText(html_content, 'html')
        msg_alternative.attach(msg_text)
        msg_alternative.attach(msg_html)

        # Attach QR Code Image
        if qr_code_bytes:
            img = MIMEImage(qr_code_bytes, 'png')
            img.add_header('Content-ID', '<qrcode_img>')
            img.add_header('Content-Disposition', 'inline', filename='qrcode.png')
            msg.attach(img)

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.send_message(msg)
            
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

def send_registration_email(complaint: dict, base_domain: str = "http://127.0.0.1:5000"):
    """Format and send the registration email."""
    if not complaint.get('email'):
        logger.warning(f"No email provided for complaint {complaint.get('complaint_id')}. Skipping email.")
        return

    track_url = f"{base_domain}/track?id={complaint['complaint_id']}"
    qr_bytes = generate_qr_code(track_url)
    
    # Format a short summary
    desc = complaint.get('description', '')
    summary = desc[:100] if len(desc) > 100 else desc
    
    html = render_email_template(
        REGISTRATION_TEMPLATE,
        name=complaint.get('name', 'Citizen'),
        complaint_id=complaint['complaint_id'],
        category=complaint.get('category', 'N/A'),
        priority=complaint.get('priority', 'Medium'),
        department=complaint.get('department', 'Pending'),
        created_at=complaint.get('created_at', 'Now'),
        status=complaint.get('status', 'Registered'),
        summary=summary,
        track_url=track_url
    )
    
    subject = f"Grievance Registered - ID: {complaint['complaint_id']}"
    send_email_with_qr(complaint['email'], subject, html, qr_bytes)

def send_status_email(complaint: dict, new_status: str, note: str, base_domain: str = "http://127.0.0.1:5000"):
    """Format and send the status update email."""
    if not complaint.get('email'):
        return

    track_url = f"{base_domain}/track?id={complaint['complaint_id']}"
    qr_bytes = generate_qr_code(track_url)
    
    from datetime import datetime
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    html = render_email_template(
        STATUS_UPDATE_TEMPLATE,
        complaint_id=complaint['complaint_id'],
        status=new_status,
        updated_at=now_str,
        note=note,
        track_url=track_url
    )
    
    subject = f"Grievance Status Update - {new_status} (ID: {complaint['complaint_id']})"
    send_email_with_qr(complaint['email'], subject, html, qr_bytes)
