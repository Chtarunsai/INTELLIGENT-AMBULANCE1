# hospital_dashboard.py - Hospital Server (Port 5001)

from flask import Flask, render_template_string, jsonify, request, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os 
import json 
import socket 
from pathlib import Path
import urllib.parse 
import requests 

# --- FUNCTION TO GET LOCAL IP (RETAINED FOR LOCAL DEBUGGING ONLY) ---
def get_local_ip():
    """Detects the computer's local Wi-Fi/Ethernet IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# --- CONFIGURATION ---
HOSPITAL_SERVER_PORT = 5001
MY_IP_ADDRESS = get_local_ip() 

# --- FIX 1: USE RENDER ENVIRONMENT VARIABLE for Inter-Service Communication ---
AMBULANCE_APP_URL = os.environ.get("AMBULANCE_APP_URL", f"http://{MY_IP_ADDRESS}:5000") 

# --- FIX 2: TEMPLATE PATH ---
# Assuming the file's current location relative to the top-level /templates folder is correct.
# We are keeping the existing template_dir calculation (which was aiming for '../.. /.. /templates').
# FIX: Use one level of '..' to go up one directory level to the repository root
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates')) 

hospital_app = Flask(__name__, template_folder=template_dir)
# --- FIX 3: DATABASE CONFIGURATION AND db DEFINITION (Corrected Order) ---
hospital_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ambulance_app.db'
hospital_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(hospital_app) 

# --- FIX 4: DB and Initialization Logic moved outside __main__ ---
def initialize_db():
    with hospital_app.app_context():
        db.create_all()

# --- Initialize DB on Startup so Gunicorn executes it ---
initialize_db() 

# ==============================================================================
# --- DATABASE MODELS (These must always come AFTER db = SQLAlchemy) ---
# ==============================================================================

class User(db.Model):
    __tablename__ = 'user'
    crew_name = db.Column(db.String(80), primary_key=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    hospital_name = db.Column(db.String(120), nullable=False)
    hospital_id = db.Column(db.String(50), nullable=False)
    
    cases = db.relationship('Case', backref='crew_member', lazy='dynamic')

class Case(db.Model):
    __tablename__ = 'case'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=db.func.now())
    crew_name = db.Column(db.String(80), db.ForeignKey('user.crew_name'), nullable=True) 
    
    vitals_snapshot = db.Column(db.String(255), nullable=False) 
    symptoms_snapshot = db.Column(db.String(512), nullable=True) 
    ai_prediction = db.Column(db.String(255), nullable=False) 
    is_critical = db.Column(db.Boolean, nullable=False)
    
    origin_address = db.Column(db.String(255), nullable=False)
    hospital_name = db.Column(db.String(120), nullable=True)
    hospital_specialty = db.Column(db.String(120), nullable=True)
    distance_km = db.Column(db.Float, nullable=True)
    simulated_eta_min = db.Column(db.Integer, nullable=True)
    
    # --- CRITICAL FIELDS ---
    mews_score = db.Column(db.Integer, nullable=True) 
    vitals_trend_json = db.Column(db.Text, nullable=True) 
    acceptance_status = db.Column(db.String(50), default="AWAITING RESPONSE") 

# ==============================================================================
# --- API ENDPOINTS ---
# ==============================================================================

@hospital_app.route('/api/update_acceptance/<int:case_id>', methods=['POST'])
def update_acceptance(case_id):
    """
    Updates the hospital acceptance status and sends a direct notification 
    to the Ambulance Server using the AMBULANCE_APP_URL environment variable.
    """
    data = request.get_json()
    new_status = data.get('status')
    
    if new_status not in ["ACCEPTED", "REJECTED", "ON HOLD"]:
        return jsonify({"success": False, "message": "Invalid status provided."}), 400

    with hospital_app.app_context():
        case = Case.query.get(case_id)
        if not case:
            return jsonify({"success": False, "message": "Case not found"}), 404
        
        try:
            # 1. Update status in the local (Hospital) database
            case.acceptance_status = new_status
            db.session.commit()
            
            # 2. NOTIFY AMBULANCE SERVER DIRECTLY over the public internet
            ambulance_notify_url = f"{AMBULANCE_APP_URL}/api/receive_hospital_update/{case_id}"
            
            # Send POST request to the Ambulance Server
            try:
                requests.post(ambulance_notify_url, json={'status': new_status})
                print(f"[HOSPITAL SENT PUSH] Status {new_status} pushed to Ambulance Server at {AMBULANCE_APP_URL}.")
            except Exception as e:
                # Log the error, but don't fail the Hospital Server's transaction
                print(f"[ERROR] Failed to send push notification to Ambulance Server: {e}")

            response_data = {
                "success": True, 
                "message": f"Case {case_id} status updated to {new_status}",
                "new_status": new_status
            }
            
            return jsonify(response_data), 200
        except Exception as e:
            db.session.rollback()
            print(f"Database update failed: {e}")
            return jsonify({"success": False, "message": f"Database error: {e}"}), 500

@hospital_app.route('/api/case_data/<int:case_id>', methods=['GET'])
def get_case_data(case_id):
    """Fetches case data for the dashboard view."""
    with hospital_app.app_context():
        case = Case.query.get(case_id)
        if not case:
            return jsonify({"success": False, "message": "Case not found"}), 404

        vitals_list = case.vitals_snapshot.split(',')
        triage_status = "CRITICAL CARE" if case.is_critical else "STANDARD TRIAGE"

        try:
            vitals_trend = json.loads(case.vitals_trend_json) if case.vitals_trend_json else None
        except json.JSONDecodeError:
            vitals_trend = None
        
        # Ensure Vitals List is complete
        if len(vitals_list) < 7:
            vitals_list = vitals_list + ['N/A'] * (7 - len(vitals_list))
        
        data = {
            "success": True,
            "case_id": case.id,
            "timestamp": case.timestamp.strftime('%H:%M:%S %p'),
            "crew_name": case.crew_name if case.crew_name else 'N/A', 
            "patient_name_display": "Patient #" + str(case.id),
            "patient_vitals": {
                "age": vitals_list[0],
                "bp": f"{vitals_list[1]} / {vitals_list[2]} mmHg",
                "hr": f"{vitals_list[3]} bpm",
                "o2": f"{vitals_list[4]} %",
                "temp": f"{vitals_list[5]} °F",
                "rr": f"{vitals_list[6]} breaths/min",
            },
            "symptoms_text": case.symptoms_snapshot if case.symptoms_snapshot else 'No remarks.',
            "ai_prediction": case.ai_prediction.split(':')[0],
            "is_critical": case.is_critical,
            "hospital_name": case.hospital_name if case.hospital_name else 'N/A',
            "origin_address": case.origin_address,
            "eta_min": case.simulated_eta_min if case.simulated_eta_min is not None else 'N/A', 
            "triage_status": triage_status,
            "mews_score": case.mews_score if case.mews_score is not None else 0,
            "vitals_trend": vitals_trend,
            "acceptance_status": case.acceptance_status 
        }
        return jsonify(data)

# ==============================================================================
# --- MAIN DASHBOARD ROUTE ---
# ==============================================================================

@hospital_app.route('/')
def dashboard_root():
    """
    New root route. Fetches the list of all cases from the Ambulance Server 
    and redirects to the most recent case ID. (Auto-fetch functionality)
    """
    # 1. Construct the API URL for the Ambulance Server's case history
    ambulance_api_url = f"{AMBULANCE_APP_URL}/api/cases"
    
    try:
        # 2. Request case history from the Ambulance Server
        response = requests.get(ambulance_api_url, timeout=5)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        case_data = response.json()
        
        # 3. Find the most recent case ID
        if case_data.get('success') and case_data.get('cases'):
            # The API returns cases in descending order, so the first case is the latest.
            latest_case = case_data['cases'][0]
            latest_case_id = latest_case['id']
            
            # 4. Redirect to the specific dashboard URL using the latest ID
            return redirect(url_for('hospital_dashboard', case_id=latest_case_id))
            
        else:
            # If successful but no cases are found in the DB
            return "No active cases found on the Ambulance Server database. Deploying complete.", 200

    except requests.exceptions.RequestException as e:
        # If the Ambulance Server is down or unreachable
        print(f"ERROR: Could not connect to Ambulance Server at {AMBULANCE_APP_URL}. {e}")
        return f"CRITICAL ERROR: Hospital Server cannot connect to Ambulance Server at {AMBULANCE_APP_URL}. Check connection and server status.", 503
    except Exception as e:
        return f"Internal Server Error during case retrieval: {e}", 500


@hospital_app.route('/dashboard/<int:case_id>')
def hospital_dashboard(case_id):
    """Serves the main Hospital Dashboard HTML template."""
    # --- FIX: Updated filename to hospital_dashboard.html (with underscore) ---
    try:
        # Template filename is changed from 'hospital dashboard.html' to 'hospital_dashboard.html'
        return render_template('hospital_dashboard.html', case_id=case_id, dashboard_url=AMBULANCE_APP_URL)
    except Exception as e:
        return f"Dashboard HTML file NOT FOUND. Error: {e}", 500

if __name__ == '__main__':
    # This block now only handles the local running instance
    print(f"\n=======================================================")
    print(f"--- HOSPITAL SERVER RUNNING ---")
    print(f"--- 1. On THIS Computer: http://127.0.0.1:{HOSPITAL_SERVER_PORT}")
    print(f"--- 2. On OTHER Devices: http://{MY_IP_ADDRESS}:{HOSPITAL_SERVER_PORT}")
    print(f"=======================================================\n")
    
    # host='0.0.0.0' allows external connections
    hospital_app.run(host='0.0.0.0', port=HOSPITAL_SERVER_PORT, debug=True)