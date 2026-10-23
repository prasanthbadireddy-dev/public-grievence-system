# AI-Powered Public Grievance Analysis System

An end-to-end intelligent Public Grievance Redressal and Analysis platform designed to automate, categorize, prioritize, and track citizen complaints across municipal departments.

---

## 🌟 Key Features

1. **AI-Driven Complaint Classification**:
   - Classifies complaints into categories (Electricity, Sanitation, Healthcare, Safety, Infrastructure, etc.) and routes them to appropriate departments.
   - Dual-engine NLP: Supports deep fine-tuned multi-task transformer models (DeBERTa-v3) with automatic rule-based NLP fallback for high availability.

2. **Priority & Sentiment Detection**:
   - Assesses urgency and assigns risk levels (`Low`, `Medium`, `High`, `Critical`).
   - Analyzes grievance sentiment and emotional tone to prioritize urgent public safety matters.

3. **Intelligent Duplicate Detection**:
   - Cosine similarity matching using an integrated TF-IDF vectorizer to identify and link recurring complaints.

4. **Multi-Channel & Accessible Citizen Interface**:
   - GPS-enabled address auto-completion with reverse geocoding.
   - Voice-to-text recording integration.
   - Multi-language support via Google Translate.
   - Evidence file upload support (images & PDFs).

5. **Citizen Tracking & Automated Notifications**:
   - Real-time status tracker with stage-by-stage audit logs.
   - Auto-generated QR codes on receipts for quick mobile tracking.
   - Automated email dispatch via SMTP with personalized tracking links.

6. **Administrative Dashboard**:
   - Live analytics on resolution rates, department workloads, and priority distributions.
   - Complaint resolution workflow, duplicate resolution, PDF report generation, and CSV exports.

---

## 📁 Repository Structure

```text
├── backend/
│   ├── app.py                # Main Flask backend server and REST APIs
│   ├── email_service.py      # SMTP notifications and QR receipt generation
│   ├── requirements.txt      # Python dependencies
│   ├── start_server.bat      # One-click startup script for Windows
│   ├── .env.example          # Sample environment variables template
│   └── verify_all.py         # Full feature verification and API test suite
├── Front end/
│   ├── public_grievance_portal_home/  # Citizen portal landing page
│   ├── register_a_new_complaint/     # Live grievance registration portal
│   ├── track_your_grievance/         # Real-time status tracking portal
│   └── admin_grievance_dashboard/    # Administrative control center & login
└── Datasets/
    ├── maps/                 # Category, department, and risk label mappings
    ├── service desk tickets/ # Ticket metadata & vocabularies
    └── Category/             # Category code mapping sheets
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- pip

### 1. Clone the Repository
```bash
git clone https://github.com/prasanthbadireddy-dev/public-grievence-system.git
cd public-grievence-system
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 3. Configure Environment Variables
Copy `backend/.env.example` to `backend/.env` and update your SMTP credentials:
```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
SMTP_EMAIL=your-email@example.com
SMTP_APP_PASSWORD=your-app-password
```

### 4. Run the Server
You can start the server using the Windows batch file:
```bash
backend\start_server.bat
```
Or directly using Python:
```bash
cd backend
python app.py
```

The application will be accessible at:
- **Home Portal**: [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
- **Register Complaint**: [http://127.0.0.1:5000/register](http://127.0.0.1:5000/register)
- **Track Complaint**: [http://127.0.0.1:5000/track](http://127.0.0.1:5000/track)
- **Admin Dashboard**: [http://127.0.0.1:5000/admin](http://127.0.0.1:5000/admin) *(Default: admin / admin123)*
