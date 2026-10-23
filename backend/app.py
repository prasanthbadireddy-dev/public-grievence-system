"""
AI-Powered Public Grievance Analysis System - Flask Backend
=============================================================
Provides REST API endpoints for:
  1. Complaint Classification (NLP-based domain categorization)
  2. Priority Detection (urgency scoring)
  3. Sentiment Analysis (tone of complaint)
  4. Duplicate Complaint Detection (similarity matching)
  5. Complaint submission + storage
"""

import os
import re
import json
import math
import uuid
import hashlib
import datetime
import threading
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
from functools import wraps

import email_service

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

from flask import Flask, request, jsonify, send_file, session, redirect, url_for
from werkzeug.utils import secure_filename
from flask_cors import CORS

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR  = os.path.join(BASE_DIR, "..", "Front end")
DB_FILE       = os.path.join(BASE_DIR, "complaints.db")
MODEL_PATH    = os.path.join(BASE_DIR, "..", "Datasets", "b2_multitask_model.pt")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "super_secret_key_123"
CORS(app, supports_credentials=True)   # Allow cross-origin from the HTML pages

# ─────────────────────────────────────────────────────────────
# SQLite Database Setup
# ─────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            complaint_id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            description TEXT,
            category TEXT,
            priority TEXT,
            sentiment TEXT,
            department TEXT,
            confidence REAL,
            status TEXT,
            created_at TEXT,
            timeline TEXT,
            possible_duplicates TEXT,
            parent_id TEXT,
            duplicate_count INTEGER DEFAULT 0,
            evidence_files TEXT
        )
    ''')

    # Migration: add evidence_files column if it doesn't exist (for existing DBs)
    try:
        c.execute("ALTER TABLE complaints ADD COLUMN evidence_files TEXT")
        conn.commit()
    except Exception:
        pass  # Column already exists

    c.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Insert default settings if not present
    defaults = {
        "maintenance": "false",
        "anon": "true",
        "sms": "false",
        "email": "true",
        "profanity": "true",
        "duplicate": "true",
        "threshold": "65",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (k, v))
    
    # Create default admin if not exists
    c.execute("SELECT * FROM admins WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                  ('admin', generate_password_hash('admin123')))
    conn.commit()
    conn.close()

init_db()

def get_settings() -> dict:
    """Fetch all system settings from the database as a dict."""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
    conn.close()
    s = {r["key"]: r["value"] for r in rows}
    # Parse booleans and numbers
    return {
        "maintenance": s.get("maintenance", "false") == "true",
        "anon":        s.get("anon", "true") == "true",
        "sms":         s.get("sms", "false") == "true",
        "email":       s.get("email", "true") == "true",
        "profanity":   s.get("profanity", "true") == "true",
        "duplicate":   s.get("duplicate", "true") == "true",
        "threshold":   int(s.get("threshold", "65")),
    }

def get_all_complaints():
    """Helper to fetch all complaints and parse JSON fields."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM complaints").fetchall()
    conn.close()
    
    complaints = []
    for r in rows:
        c = dict(r)
        c["timeline"] = json.loads(c["timeline"]) if c["timeline"] else []
        c["possible_duplicates"] = json.loads(c["possible_duplicates"]) if c["possible_duplicates"] else []
        c["evidence_files"] = json.loads(c["evidence_files"]) if c.get("evidence_files") else []
        complaints.append(c)
    return complaints


def allowed_file(filename: str) -> bool:
    """Check if an uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Decorator for protected API routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ─────────────────────────────────────────────────────────────
# ML Model (lazy-loaded, optional – falls back to rule-based)
# ─────────────────────────────────────────────────────────────
_model      = None
_tokenizer  = None
_model_lock = threading.Lock()
_model_loaded = False   # True once load attempted

def try_load_model():
    """Attempt to load the DeBERTa multitask model. Silently fails if unavailable."""
    global _model, _tokenizer, _model_loaded
    with _model_lock:
        if _model_loaded:
            return
        _model_loaded = True
        try:
            import torch
            import torch.nn as nn
            from transformers import DebertaV2Model, DebertaV2Config, AutoTokenizer

            class MultiTaskGrievanceModel(nn.Module):
                def __init__(self, config):
                    super().__init__()
                    self.encoder   = DebertaV2Model(config)
                    self.fm_head   = nn.Linear(768, 21)
                    self.dept_head = nn.Linear(768, 22)
                    self.risk_head = nn.Linear(768, 4)

                def forward(self, input_ids, attention_mask=None, token_type_ids=None):
                    out = self.encoder(
                        input_ids=input_ids,
                        attention_mask=attention_mask,
                        token_type_ids=token_type_ids
                    )
                    cls = out.last_hidden_state[:, 0, :]
                    return self.fm_head(cls), self.dept_head(cls), self.risk_head(cls)

            config     = DebertaV2Config.from_pretrained("microsoft/deberta-v3-base")
            model_inst = MultiTaskGrievanceModel(config)
            state_dict = torch.load(MODEL_PATH, map_location=torch.device("cpu"))
            model_inst.load_state_dict(state_dict, strict=True)
            model_inst.eval()
            _model     = model_inst

            _tokenizer = AutoTokenizer.from_pretrained("microsoft/deberta-v3-base")
            print("[INFO] DeBERTa model loaded successfully.")
        except Exception as e:
            print(f"[WARN] Could not load PyTorch model ({e}). Using rule-based fallback.")
            _model = _tokenizer = None


# ─────────────────────────────────────────────────────────────
# Label Mappings  (indices → human labels)
# ─────────────────────────────────────────────────────────────

# 7 fine-tuning label categories (from CSV)
CATEGORY_LABELS = [
    "Electricity",
    "Sanitation",
    "Public Healthcare",
    "Economics",
    "Public Safety",
    "Violence",
    "Public Infrastructure",
]

# 4 risk levels
RISK_LABELS = ["Low", "Medium", "High", "Critical"]

# 22 department labels (realistic mapping)
DEPT_LABELS = [
    "Municipal Corporation",
    "Public Works Department",
    "Water Supply & Sanitation",
    "Electricity Board",
    "Public Health Engineering",
    "Urban Development Authority",
    "Police Department",
    "Fire & Emergency Services",
    "Environment Department",
    "Roads & Transport",
    "Revenue Department",
    "Education Department",
    "Agriculture Department",
    "Social Welfare",
    "Housing Department",
    "Drainage & Sewerage",
    "Animal Husbandry",
    "Forest Department",
    "Consumer Affairs",
    "Labour Department",
    "Sports & Youth Affairs",
    "Others",
]

# ─────────────────────────────────────────────────────────────
# Rule-Based NLP Fallback (works without PyTorch)
# ─────────────────────────────────────────────────────────────

KEYWORD_RULES = {
    "Electricity": [
        "electricity","power","voltage","transformer","wiring","electric","outage",
        "blackout","streetlight","street light","bulb","wire","shock","electrocution",
        "meter","load shedding","generator","inverter","pole","sparks"
    ],
    "Sanitation": [
        "garbage","waste","trash","sewage","drain","drainage","sewer","toilet",
        "sanitation","hygiene","dirty","filth","rubbish","dustbin","cleanliness",
        "sweeping","flush","latrine","defecation","open defecation","mosquito",
        "stench","smell","flies","rat","rodent","pest","landfill"
    ],
    "Water Supply": [
        "water","pipe","pipeline","leak","leakage","drinking water","tap","bore",
        "borewell","well","water supply","water board","contamination","dirty water",
        "sewage water","flood","waterlogging","overflowing"
    ],
    "Roads & Infrastructure": [
        "road","pothole","street","footpath","pavement","broken road","speed breaker",
        "flyover","bridge","underpass","traffic","signal","divider","construction",
        "encroachment","building","structure"
    ],
    "Public Healthcare": [
        "health","hospital","doctor","medicine","disease","illness","sick","clinic",
        "ambulance","nurse","treatment","vaccination","epidemic","outbreak","malaria",
        "dengue","cholera","fever","covid","pandemic","pharmacy","drug","medication"
    ],
    "Public Safety": [
        "safety","accident","fire","emergency","danger","hazard","theft","robbery",
        "crime","assault","harassment","violence","fight","complaint","police","security",
        "unsafe","risk","injury","death","died","killed","casualty","threat"
    ],
    "Public Infrastructure": [
        "park","garden","playground","school","college","library","community center",
        "public toilet","shelter","footbridge","bus stop","railway","metro",
        "market","slum","demolition","construction"
    ],
}

PRIORITY_RULES = {
    "Critical": [
        "death","died","killed","fire","explosion","electrocution","flood","collapse",
        "emergency","critical","fatal","dangerous","immediate","severe","accident","major leak",
        "epidemic","outbreak","hazardous","toxic","poisonous","urgent","life threatening"
    ],
    "High": [
        "high priority","urgent","major","serious","broken pipe","power failure","disease",
        "sick","injured","hospital","violence","robbery","theft","unsafe","danger","hazard",
        "no water","no electricity","blocked","overflow","raw sewage","contaminated"
    ],
    "Medium": [
        "problem","issue","complaint","request","concern","maintenance","repair","pending",
        "delay","overdue","irregular","frequent","repeated","months","weeks","not working",
        "broken","damage","leaking","smelling","dirty"
    ],
    "Low": [
        "minor","small","request","suggestion","inconvenience","slight","inform",
        "feedback","appreciate","improve","could be","when possible","whenever"
    ],
}

SENTIMENT_RULES = {
    "Very Negative": [
        "terrible","horrible","disgusting","outrage","furious","unacceptable","disgusted",
        "shameful","pathetic","failure","incompetent","corrupt","negligent","useless",
        "worst","devastating","appalling"
    ],
    "Negative": [
        "bad","poor","unsatisfactory","disappointed","unhappy","upset","annoyed",
        "frustrated","not resolved","ignored","no response","delayed","denied",
        "problem","issue","complaint","broken","failed","wrong","incorrect"
    ],
    "Neutral": [
        "request","inform","notify","update","inquire","kindly","please","need",
        "require","would like","seeking","attention","matter"
    ],
    "Positive": [
        "good","great","excellent","resolved","satisfied","thank","appreciate",
        "happy","pleased","improved","better","well done","efficient","prompt"
    ],
}


def rule_based_analyze(text: str) -> dict:
    """Rule-based NLP analysis as fallback when PyTorch model is unavailable."""
    text_lower = text.lower()
    tokens = set(re.findall(r'\b\w+\b', text_lower))

    # ── Category classification ──────────────────────────────
    cat_scores = defaultdict(int)
    for cat, keywords in KEYWORD_RULES.items():
        for kw in keywords:
            if kw in text_lower:
                cat_scores[cat] += 1
    if cat_scores:
        category = max(cat_scores, key=cat_scores.get)
        confidence = min(0.95, 0.50 + cat_scores[category] * 0.05)
    else:
        category = "Public Infrastructure"
        confidence = 0.40

    # Build top-3 probabilities
    all_cats = list(KEYWORD_RULES.keys()) + ["Economics", "Violence"]
    cat_probs = {}
    for c in all_cats:
        sc = cat_scores.get(c, 0)
        cat_probs[c] = round(min(0.95, 0.10 + sc * 0.06), 3)
    top_cats = sorted(cat_probs.items(), key=lambda x: -x[1])[:3]

    # ── Priority detection ───────────────────────────────────
    pri_scores = defaultdict(int)
    for lvl, keywords in PRIORITY_RULES.items():
        for kw in keywords:
            if kw in text_lower:
                pri_scores[lvl] += 1
    if pri_scores:
        priority = max(pri_scores, key=pri_scores.get)
        pri_conf = min(0.95, 0.50 + pri_scores[priority] * 0.04)
    else:
        priority = "Medium"
        pri_conf = 0.50

    # ── Sentiment analysis ───────────────────────────────────
    sent_scores = defaultdict(int)
    for sentiment, keywords in SENTIMENT_RULES.items():
        for kw in keywords:
            if kw in text_lower:
                sent_scores[sentiment] += 1
    if sent_scores:
        sentiment = max(sent_scores, key=sent_scores.get)
        sent_conf = min(0.95, 0.50 + sent_scores[sentiment] * 0.05)
    else:
        sentiment = "Neutral"
        sent_conf = 0.50

    # ── Department routing ───────────────────────────────────
    dept_map = {
        "Electricity": "Electricity Board",
        "Sanitation": "Municipal Corporation",
        "Water Supply": "Water Supply & Sanitation",
        "Roads & Infrastructure": "Public Works Department",
        "Public Healthcare": "Public Health Engineering",
        "Public Safety": "Police Department",
        "Public Infrastructure": "Urban Development Authority",
        "Economics": "Revenue Department",
        "Violence": "Police Department",
    }
    department = dept_map.get(category, "Municipal Corporation")

    return {
        "category":     category,
        "confidence":   round(confidence, 3),
        "top_categories": [{"label": c, "score": s} for c, s in top_cats],
        "priority":     priority,
        "priority_confidence": round(pri_conf, 3),
        "sentiment":    sentiment,
        "sentiment_confidence": round(sent_conf, 3),
        "department":   department,
        "model_used":   "rule-based-nlp",
    }


def model_based_analyze(text: str) -> dict:
    """Use the loaded DeBERTa multitask model for analysis."""
    import torch

    inputs = _tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=512,
        padding=True
    )
    with torch.no_grad():
        fm_logits, dept_logits, risk_logits = _model(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
        )

    # Softmax probabilities
    fm_probs   = torch.softmax(fm_logits,   dim=-1).squeeze().tolist()
    dept_probs = torch.softmax(dept_logits, dim=-1).squeeze().tolist()
    risk_probs = torch.softmax(risk_logits, dim=-1).squeeze().tolist()

    # Pick top category from 21 fm outputs, mapped to 7 known labels
    # (21 model outputs → map to 7 category buckets, 3 per bucket)
    def bucket_probs(probs, n_buckets):
        size = len(probs) // n_buckets
        buckets = []
        for i in range(n_buckets):
            chunk = probs[i*size:(i+1)*size]
            buckets.append(sum(chunk))
        total = sum(buckets) or 1
        return [b / total for b in buckets]

    cat_probs_mapped = bucket_probs(fm_probs, len(CATEGORY_LABELS))
    best_cat_idx     = cat_probs_mapped.index(max(cat_probs_mapped))
    category         = CATEGORY_LABELS[best_cat_idx]
    confidence       = round(max(cat_probs_mapped), 3)

    top_cats = sorted(
        zip(CATEGORY_LABELS, cat_probs_mapped),
        key=lambda x: -x[1]
    )[:3]

    # Risk/Priority
    best_risk_idx = risk_probs.index(max(risk_probs))
    priority      = RISK_LABELS[best_risk_idx]
    pri_conf      = round(max(risk_probs), 3)

    # Department
    best_dept_idx = dept_probs.index(max(dept_probs))
    department    = DEPT_LABELS[best_dept_idx % len(DEPT_LABELS)]

    # Sentiment (rule-based — model has no sentiment head)
    fallback = rule_based_analyze(text)

    return {
        "category":     category,
        "confidence":   confidence,
        "top_categories": [{"label": c, "score": round(s, 3)} for c, s in top_cats],
        "priority":     priority,
        "priority_confidence": pri_conf,
        "sentiment":    fallback["sentiment"],
        "sentiment_confidence": fallback["sentiment_confidence"],
        "department":   department,
        "model_used":   "deberta-v3-multitask",
    }


def analyze_text(text: str) -> dict:
    """Main entry point: use model if loaded, else rule-based."""
    # Translate text to English for NLP classification if not English
    text_to_analyze = text
    if GoogleTranslator is not None:
        try:
            translated = GoogleTranslator(source='auto', target='en').translate(text)
            if translated:
                text_to_analyze = translated
        except Exception as e:
            print(f"[WARN] Translation failed ({e}). Using original text.")

    if _model is not None and _tokenizer is not None:
        try:
            return model_based_analyze(text_to_analyze)
        except Exception as e:
            print(f"[WARN] Model inference failed ({e}). Falling back.")
    return rule_based_analyze(text_to_analyze)


def is_fake_complaint(text: str, name: str, address: str) -> bool:
    """
    AI Heuristic to detect spam/fake complaints.
    Rejects gibberish, very short nonsense, or repeated patterns.
    """
    text = text.lower().strip()
    
    # Too short to be a valid complaint
    if len(text) < 15:
        return True
        
    # Gibberish pattern (5+ consonants in a row)
    if re.search(r'[bcdfghjklmnpqrstvwxz]{5,}', text):
        return True
        
    # Keyboard mashing patterns
    if re.search(r'(asdf|qwer|zxcv|hjkl|uiop|1234)', text):
        return True
        
    # Same character repeated 4+ times (e.g. "aaaa", "hhhh")
    if re.search(r'(.)\\1{3,}', text):
        return True
        
    words = text.split()
    if not words:
        return True
        
    # Extremely long word without spaces (like random typing "aksdfjhaksjdfhaksjdfh")
    if any(len(w) > 20 for w in words):
        return True
        
    # Repeating identical words (e.g. "test test test")
    if len(words) >= 3 and len(set(words)) == 1:
        return True
        
    # Common dummy inputs
    if text in ["test", "testing", "asdf", "qwerty", "fake", "spam"]:
        return True
        
    return False


# ─────────────────────────────────────────────────────────────
# Duplicate Detection (TF-IDF cosine similarity)
# ─────────────────────────────────────────────────────────────

def tfidf_vectorize(texts: list[str]) -> list[dict]:
    """Lightweight TF-IDF vectorizer (no sklearn needed)."""
    stop_words = {
        "the","a","an","is","it","in","on","at","to","for","of","and","or","but",
        "this","that","with","from","by","as","are","was","were","be","been","have",
        "has","had","do","does","did","not","no","so","if","we","i","you","he","she",
        "they","my","your","our","their","its","will","would","could","should","may","might"
    }
    tokenized = []
    for text in texts:
        tokens = re.findall(r'\w{3,}', text.lower())
        filtered = [t for t in tokens if t not in stop_words]
        tokenized.append(filtered)

    # IDF calculation
    N = len(texts)
    df = defaultdict(int)
    for tokens in tokenized:
        for token in set(tokens):
            df[token] += 1
    idf = {t: math.log((N + 1) / (df[t] + 1)) + 1 for t in df}

    # TF-IDF vectors
    vectors = []
    for tokens in tokenized:
        tf = defaultdict(float)
        for t in tokens:
            tf[t] += 1
        total = max(len(tokens), 1)
        vec = {t: (cnt / total) * idf.get(t, 1) for t, cnt in tf.items()}
        vectors.append(vec)
    return vectors


def cosine_similarity(v1: dict, v2: dict) -> float:
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    mag1 = math.sqrt(sum(x**2 for x in v1.values()))
    mag2 = math.sqrt(sum(x**2 for x in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def find_duplicates(new_text: str, threshold: float = 0.65) -> list:
    """Find existing complaints similar to the new one."""
    complaints = get_all_complaints()
    if not complaints:
        return []
    existing_texts = [c.get("description", "") for c in complaints]
    all_texts = existing_texts + [new_text]
    vectors = tfidf_vectorize(all_texts)
    new_vec = vectors[-1]
    duplicates = []
    for i, vec in enumerate(vectors[:-1]):
        sim = cosine_similarity(new_vec, vec)
        if sim >= threshold:
            c = complaints[i]
            duplicates.append({
                "complaint_id": c.get("complaint_id", ""),
                "similarity":   round(sim, 3),
                "category":     c.get("category", ""),
                "status":       c.get("status", "Pending"),
                "created_at":   c.get("created_at", ""),
            })
    return sorted(duplicates, key=lambda x: -x["similarity"])[:3]


# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Frontend Page Routes  (serves HTML over HTTP — no CORS issues)
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def serve_home():
    """Serve the public portal home page."""
    page = os.path.join(FRONTEND_DIR, "public_grievance_portal_home", "code.html")
    return send_file(page)

@app.route("/register", methods=["GET"])
def serve_register():
    """Serve the register a complaint page."""
    page = os.path.join(FRONTEND_DIR, "register_a_new_complaint", "code.html")
    return send_file(page)

@app.route("/track", methods=["GET"])
def serve_track():
    """Serve the track your grievance page."""
    page = os.path.join(FRONTEND_DIR, "track_your_grievance", "code.html")
    return send_file(page)

@app.route("/admin", methods=["GET"])
def serve_admin():
    """Serve the admin dashboard page. Protected."""
    if 'admin_logged_in' not in session:
        return redirect(url_for('serve_admin_login'))
    page = os.path.join(FRONTEND_DIR, "admin_grievance_dashboard", "code.html")
    return send_file(page)

@app.route("/admin_login", methods=["GET"])
def serve_admin_login():
    """Serve the admin login page."""
    page = os.path.join(FRONTEND_DIR, "admin_grievance_dashboard", "login.html")
    return send_file(page)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Grievance Analysis API", "version": "2.0"})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    
    conn = get_db()
    admin = conn.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
    conn.close()
    
    if admin and check_password_hash(admin["password_hash"], password):
        session['admin_logged_in'] = True
        session['admin_username'] = username
        return jsonify({"success": True})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return jsonify({"success": True})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """
    Real-time AI analysis of complaint text.
    Body: { "text": "...", "check_duplicates": true }
    Returns classification, priority, sentiment, duplicates.
    """
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()

    if len(text) < 10:
        return jsonify({"error": "Text too short for analysis (min 10 chars)."}), 400

    result = analyze_text(text)

    if data.get("check_duplicates", True):
        result["duplicates"] = find_duplicates(text)
    else:
        result["duplicates"] = []

    return jsonify(result)


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """Return current system settings."""
    return jsonify(get_settings())


@app.route("/api/settings", methods=["POST"])
@login_required
def api_save_settings():
    """Save system settings to the database."""
    data = request.get_json(force=True, silent=True) or {}
    allowed = ["maintenance", "anon", "sms", "email", "profanity", "duplicate", "threshold"]
    conn = get_db()
    for key in allowed:
        if key in data:
            val = str(data[key]).lower() if isinstance(data[key], bool) else str(data[key])
            conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "settings": get_settings()})


@app.route("/api/upload", methods=["POST"])
def upload_evidence():
    """
    Upload evidence files for a complaint.
    Accepts multipart/form-data with up to 3 files (images or PDFs).
    Returns: { files: [ { original_name, saved_name, url } ] }
    """
    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    uploaded = []
    files = request.files.getlist("files")

    if len(files) > 3:
        return jsonify({"error": "Maximum 3 files allowed"}), 400

    for f in files:
        if f.filename == "":
            continue
        if not allowed_file(f.filename):
            return jsonify({"error": f"File type not allowed: {f.filename}"}), 400

        # Check file size (read into memory then check length)
        content = f.read()
        if len(content) > MAX_FILE_SIZE:
            return jsonify({"error": f"File too large (max 5 MB): {f.filename}"}), 400

        safe_name = secure_filename(f.filename)
        unique_name = str(uuid.uuid4())[:8] + "_" + safe_name
        save_path = os.path.join(UPLOAD_FOLDER, unique_name)

        with open(save_path, "wb") as out:
            out.write(content)

        uploaded.append({
            "original_name": f.filename,
            "saved_name": unique_name,
            "url": f"/api/uploads/{unique_name}"
        })

    return jsonify({"success": True, "files": uploaded}), 200


@app.route("/api/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    """Serve an uploaded evidence file."""
    safe = secure_filename(filename)
    file_path = os.path.join(UPLOAD_FOLDER, safe)
    if not os.path.isfile(file_path):
        return jsonify({"error": "File not found"}), 404
    return send_file(file_path)


@app.route("/api/complaints", methods=["POST"])
def submit_complaint():
    """
    Submit a new complaint.
    Body: { name, phone, email, address, description, evidence_names? }
    Returns: { complaint_id, ... }
    """
    settings = get_settings()
    data = request.get_json(force=True, silent=True) or {}

    # Maintenance Mode check
    if settings["maintenance"]:
        return jsonify({"error": "maintenance", "message": "The portal is currently under maintenance. Please try again later."}), 503

    required = ["name", "phone", "email", "address", "description"]
    for field in required:
        if not (data.get(field) or "").strip():
            return jsonify({"error": f"Missing required field: {field}"}), 400

    text = data["description"].strip()
    name = data["name"].strip()
    address = data["address"].strip()

    # Fake/Spam Detection (only if enabled in settings)
    if settings["profanity"] and is_fake_complaint(text, name, address):
        return jsonify({
            "error": "fake_detected",
            "message": "Complaint could not be registered. It was flagged as invalid or spam by the AI."
        }), 400

    # Run AI analysis
    analysis = analyze_text(text)

    # Check duplicates and escalating priority (use threshold from settings, converted to 0–1 scale)
    dup_threshold = settings["threshold"] / 100.0 if settings["duplicate"] else 1.1
    dups = find_duplicates(text, threshold=0.10)  # Keep 0.10 for grouping; threshold controls AI routing
    parent_id = None
    is_urgent_escalation = False
    
    if dups and dups[0]["similarity"] >= 0.10:
        existing_id = dups[0]["complaint_id"]
        # Check if the location is the same (simple text inclusion/match heuristic)
        conn = get_db()
        parent = conn.execute("SELECT * FROM complaints WHERE complaint_id = ?", (existing_id,)).fetchone()
        
        if parent:
            # If address is similar (e.g., matching keywords) or exactly same
            p_addr = parent["address"].lower()
            n_addr = address.lower()
            
            # Simple heuristic: at least 1 word matches in address or exact match
            addr_words_parent = set(re.findall(r'\\b\\w+\\b', p_addr))
            addr_words_new = set(re.findall(r'\\b\\w+\\b', n_addr))
            
            if p_addr == n_addr or len(addr_words_parent & addr_words_new) >= 2:
                parent_id = parent["complaint_id"]
                if parent["parent_id"]: 
                    parent_id = parent["parent_id"] # Link to root master
                is_urgent_escalation = True
                
                # Update the master complaint to be Critical and increment duplicate count
                conn.execute('''
                    UPDATE complaints 
                    SET priority = 'Critical', duplicate_count = duplicate_count + 1 
                    WHERE complaint_id = ?
                ''', (parent_id,))
                
        conn.commit()
        conn.close()

    complaint_id = "PGC-" + datetime.datetime.now().strftime("%Y") + "-" + \
                   str(uuid.uuid4())[:8].upper()

    timeline = [{
        "stage":   "Registered",
        "date":    datetime.datetime.utcnow().isoformat() + "Z",
        "note":    "Complaint registered and AI analysis completed.",
    }]
    
    if is_urgent_escalation:
        timeline.append({
            "stage": "Escalated",
            "date": datetime.datetime.utcnow().isoformat() + "Z",
            "note": "Linked to existing issue at same location. Upgraded priority."
        })

    complaint = {
        "complaint_id":  complaint_id,
        "name":          data["name"],
        "phone":         data["phone"],
        "email":         data["email"],
        "address":       address,
        "description":   text,
        "category":      analysis["category"],
        "priority":      "Critical" if is_urgent_escalation else analysis["priority"],
        "sentiment":     analysis["sentiment"],
        "department":    analysis["department"],
        "confidence":    analysis["confidence"],
        "status":        "Registered",
        "created_at":    datetime.datetime.utcnow().isoformat() + "Z",
        "timeline":      timeline,
        "possible_duplicates": dups,
    }

    # evidence_files: list of server-side filenames, provided after upload step
    evidence_files = data.get("evidence_files", [])  # list of saved filenames

    conn = get_db()
    conn.execute('''
        INSERT INTO complaints (
            complaint_id, name, phone, email, address, description,
            category, priority, sentiment, department, confidence,
            status, created_at, timeline, possible_duplicates, parent_id, duplicate_count,
            evidence_files
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        complaint["complaint_id"], complaint["name"], complaint["phone"], complaint["email"],
        complaint["address"], complaint["description"], complaint["category"],
        complaint["priority"], complaint["sentiment"], complaint["department"],
        complaint["confidence"], complaint["status"], complaint["created_at"],
        json.dumps(complaint["timeline"]), json.dumps(complaint["possible_duplicates"]),
        parent_id, 0, json.dumps(evidence_files)
    ))
    conn.commit()
    conn.close()

    # Trigger email asynchronously (only if email notifications enabled)
    if settings["email"]:
        threading.Thread(target=email_service.send_registration_email, args=(complaint,)).start()

    return jsonify({
        "success":      True,
        "complaint_id": complaint_id,
        "category":     analysis["category"],
        "priority":     analysis["priority"],
        "sentiment":    analysis["sentiment"],
        "department":   analysis["department"],
        "email_sent":   settings["email"],
        "sms_sent":     settings["sms"]
    }), 201


@app.route("/api/complaints", methods=["GET"])
@login_required
def list_complaints():
    """
    List all complaints. Supports filtering:
      ?category=Sanitation&priority=High&status=Pending&q=water&page=1&per_page=20
    """
    cat    = request.args.get("category", "").strip()
    pri    = request.args.get("priority", "").strip()
    status = request.args.get("status", "").strip()
    query  = request.args.get("q", "").strip().lower()
    page   = int(request.args.get("page", 1))
    per    = int(request.args.get("per_page", 20))

    all_c = get_all_complaints()
    # Only show "Master" complaints (parent_id is None)
    filtered = [c for c in all_c if not c.get("parent_id")]
    
    if cat:
        filtered = [c for c in filtered if c.get("category") == cat]
    if pri:
        filtered = [c for c in filtered if c.get("priority") == pri]
    if status:
        filtered = [c for c in filtered if c.get("status") == status]
    if query:
        filtered = [c for c in filtered
                    if query in c.get("description", "").lower()
                    or query in c.get("address", "").lower()]

    total   = len(filtered)
    start   = (page - 1) * per
    results = filtered[start:start+per]

    return jsonify({
        "total":    total,
        "page":     page,
        "per_page": per,
        "items":    results,
    })


@app.route("/api/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id: str):
    """Get a single complaint by ID."""
    complaints = get_all_complaints()
    for c in complaints:
        if c.get("complaint_id") == complaint_id:
            return jsonify(c)
    return jsonify({"error": "Complaint not found."}), 404


@app.route("/api/complaints/<complaint_id>/status", methods=["PATCH"])
@login_required
def update_status(complaint_id: str):
    """
    Update complaint status (admin use).
    Body: { "status": "In Progress", "note": "..." }
    """
    data   = request.get_json(force=True, silent=True) or {}
    status = data.get("status", "").strip()
    note   = data.get("note", "").strip()

    valid_statuses = ["Registered","Under Review","Assigned","In Progress","Resolved","Closed"]
    if status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of: {valid_statuses}"}), 400

    complaints = get_all_complaints()
    for c in complaints:
        if c.get("complaint_id") == complaint_id:
            c["status"] = status
            c["timeline"].append({
                "stage": status,
                "date":  datetime.datetime.utcnow().isoformat() + "Z",
                "note":  note,
            })
            
            conn = get_db()
            conn.execute('''
                UPDATE complaints 
                SET status = ?, timeline = ?
                WHERE complaint_id = ?
            ''', (status, json.dumps(c["timeline"]), complaint_id))
            conn.commit()
            conn.close()
            
            # Trigger status email asynchronously (only if email notifications enabled)
            if get_settings()["email"]:
                threading.Thread(target=email_service.send_status_email, args=(c, status, note)).start()
            
            return jsonify({"success": True, "complaint_id": complaint_id, "status": status})

    return jsonify({"error": "Complaint not found."}), 404


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Dashboard statistics."""
    all_c = get_all_complaints()
    complaints = [c for c in all_c if not c.get("parent_id")]
    
    total    = len(complaints)
    resolved = sum(1 for c in complaints if c.get("status") in ("Resolved","Closed"))
    pending  = sum(1 for c in complaints if c.get("status") not in ("Resolved","Closed"))

    cat_counts = defaultdict(int)
    pri_counts = defaultdict(int)
    sent_counts = defaultdict(int)
    dept_counts = defaultdict(int)
    for c in complaints:
        cat_counts[c.get("category", "Other")]       += 1
        pri_counts[c.get("priority", "Medium")]       += 1
        sent_counts[c.get("sentiment", "Neutral")]    += 1
        dept_counts[c.get("department", "Others")]    += 1

    resolution_rate = round((resolved / total * 100) if total else 0, 1)

    return jsonify({
        "total":           total,
        "resolved":        resolved,
        "pending":         pending,
        "resolution_rate": resolution_rate,
        "by_category":     dict(cat_counts),
        "by_priority":     dict(pri_counts),
        "by_sentiment":    dict(sent_counts),
        "by_department":   dict(dept_counts),
    })


@app.route("/api/model/status", methods=["GET"])
def model_status():
    return jsonify({
        "model_loaded": _model is not None,
        "model_type":   "deberta-v3-multitask" if _model else "rule-based-nlp",
    })


# ─────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Attempt model load in background thread (non-blocking start)
    threading.Thread(target=try_load_model, daemon=True).start()
    print("[INFO] Starting Grievance Analysis API on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
