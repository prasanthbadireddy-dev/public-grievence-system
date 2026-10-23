import os
import sys

# Add backend directory to sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[INFO] Running Public Grievance Portal on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
