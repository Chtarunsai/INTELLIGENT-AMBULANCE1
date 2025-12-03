# app.py - Main Ambulance Server (Port 5000)

import json
import random
import time
import urllib.parse
import os
import socket 
from datetime import datetime, timedelta
from pathlib import Path 
import requests 

from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# --- FUNCTION TO GET LOCAL IP ---
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
SERVER_PORT = 5000 
MY_IP_ADDRESS = get_local_ip()

AMBULANCE_START_LOCATION = "17-22, 2nd Main Rd, Vinayak Nagar, Kattigenahalli, Bengaluru, Karnataka 560064"

# *** CRITICAL: VERIFY THIS PATH ON YOUR SYSTEM ***
HTML_FILE_PATH = Path(r"C:\Users\CHTAR\OneDrive\Desktop\clite (2)\clite\template\index.html") 

HOSPITAL_DASHBOARD_PORT = 5001 
HOSPITAL_APP_URL = f"http://{MY_IP_ADDRESS}:{HOSPITAL_DASHBOARD_PORT}"

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ambulance_app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app)

# ==============================================================================
# --- DATABASE MODELS ---
# ==============================================================================

class User(db.Model):
    """Stores crew registration data."""
    crew_name = db.Column(db.String(80), primary_key=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    hospital_name = db.Column(db.String(120), nullable=False)
    hospital_id = db.Column(db.String(50), nullable=False)
    
    cases = db.relationship('Case', backref='crew_member', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.crew_name}>'

# In app.py, inside class Case(db.Model):
class Case(db.Model):
    __tablename__ = 'case'
    # PRIMARY KEY MUST BE PRESENT
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
    # THE MISSING COLUMN (rejected_history)
    rejected_history = db.Column(db.Text, nullable=True)

# ==============================================================================
# --- UTILITY FUNCTIONS ---
# ==============================================================================

def analyze_vitals_from_client(vitals_list, symptoms_str=""):
    """
    Simple in-app analyzer that returns (prediction_str, is_critical_bool).
    """
    try:
        age = int(float(vitals_list[0])) if len(vitals_list) > 0 and vitals_list[0] != "" else 40
        bp_sys = float(vitals_list[1]) if len(vitals_list) > 1 and vitals_list[1] != "" else 120.0
        hr = float(vitals_list[3]) if len(vitals_list) > 3 and vitals_list[3] != "" else 80.0
        o2 = float(vitals_list[4]) if len(vitals_list) > 4 and vitals_list[4] != "" else 98.0
        resp = float(vitals_list[6]) if len(vitals_list) > 6 and vitals_list[6] != "" else 16.0
        temp = float(vitals_list[5]) if len(vitals_list) > 5 and vitals_list[5] != "" else 36.6
    except Exception:
        return "UNDETERMINED", False

    # Basic MEWS-derived score
    score = 0
    if resp < 9 or resp > 25: score += 3
    elif resp > 20: score += 2
    elif resp > 15: score += 1
    if hr < 40 or hr > 130: score += 3
    elif hr > 110: score += 2
    elif hr < 50 or hr > 90: score += 1
    if bp_sys < 70 or bp_sys > 200: score += 3
    elif bp_sys < 90: score += 2
    elif bp_sys > 180: score += 1
    if o2 < 90: score += 2

    # Symptom keyword boosting (EXPANDED LIST)
    symptoms = (symptoms_str or "").lower()
    
    # Comprehensive keywords list to ensure all major symptoms trigger a score boost
    dangerous_keywords = [
        "unconscious", "bleeding", "chest pain", "respiratory arrest", 
        "no pulse", "collapse", "seizure", "severe", 
        "breathing difficulty", "fracture", "trauma", "stroke", "severe pain"
    ]
    
    symptom_score = 0
    for kw in dangerous_keywords:
        # Check if any dangerous keyword is in the symptoms text
        if kw in symptoms: symptom_score += 2

    total_risk = score + symptom_score

    if total_risk >= 6:
        return "Likely Critical — Immediate attention advised", True
    if total_risk >= 3:
        return "Potentially Serious — Monitor and expedite transport", True
    return "Stable / Non-critical", False

def analyze_vitals_for_dashboard(vitals_list):
    """Used for dashboard status (now based on MEWS score)."""
    try:
        mews = calculate_mews_score(vitals_list)
    except Exception:
        mews = 0 
        
    if mews >= 5: return "HIGH PRIORITY", 3
    if mews >= 3: return "MEDIUM PRIORITY", 2
    return "STANDARD PRIORITY", 1

def calculate_mews_score(vitals):
    """Calculates a simulated MEWS score based on current vitals."""
    try:
        bp_sys = float(vitals[1])
        hr = float(vitals[3])
        resp_rate = float(vitals[6])
        o2 = float(vitals[4])
    except:
        return 0
    
    score = 0
    if resp_rate < 9 or resp_rate > 25: score += 3
    elif resp_rate > 20: score += 2
    elif resp_rate > 15: score += 1
    if hr < 40 or hr > 130: score += 3
    elif hr > 110: score += 2
    elif hr < 50 or hr > 90: score += 1
    if bp_sys < 70 or bp_sys > 200: score += 3
    elif bp_sys < 90: score += 2
    elif bp_sys > 180: score += 1
    if o2 < 90: score += 2
    return score

def generate_vitals_trend(vitals_list):
    """Simulates 5 data points over 20 minutes leading up to the current reading."""
    try:
        hr_base = float(vitals_list[3])
        bp_sys_base = float(vitals_list[1])
        o2_base = float(vitals_list[4])
    except:
        return "{}"
    
    trend_data = {'time_labels': [], 'hr_trend': [], 'bp_sys_trend': [], 'o2_trend': []}
    now = datetime.now()
    
    for i in range(5):
        time_offset = (4 - i) * 5 
        timestamp = (now - timedelta(minutes=time_offset)).strftime('%H:%M')
        if i < 4:
            hr = round(hr_base + random.uniform(-4, 4))
            bp = round(bp_sys_base + random.uniform(-5, 5))
            o2 = round(o2_base + random.uniform(-1, 1))
        else:
            hr, bp, o2 = int(hr_base), int(bp_sys_base), float(o2_base)
            
        trend_data['time_labels'].append(timestamp)
        trend_data['hr_trend'].append(hr)
        trend_data['bp_sys_trend'].append(bp)
        trend_data['o2_trend'].append(o2)
        
    return json.dumps(trend_data)

def _simulate_doctors(specialty):
    """Generates simulated doctor data based on specialty."""
    if "Cardiology" in specialty:
        names, quals = ["Dr. Anjali Rao", "Dr. Vikas Reddy"], ["MD, Interventional Cardiologist", "DM, Cardiovascular Surgeon"]
    elif "Critical Care" in specialty or "Multi" in specialty:
        names, quals = ["Dr. Priya Sharma", "Dr. Rohan Kumar"], ["MD, Critical Care Specialist", "DNB, Emergency Medicine"]
    elif "Neuro" in specialty:
        names, quals = ["Dr. Sanjeev Reddy", "Dr. Lakshmi V"], ["DM, Neurologist", "MS, Neuro Surgeon"]
    else:
        names, quals = ["Dr. Vivek Menon", "Dr. Sara Khan"], ["MBBS, Emergency Physician", "MD, General Surgery Resident"]
    
    doctor_index = random.randint(0, len(names) - 1)
    time_hour = time.localtime().tm_hour
    timing_factor = 1.2 if time_hour < 7 or time_hour > 20 else 1.0
    
    return {"name": names[doctor_index], "qualification": quals[doctor_index], "shift": "24/7 (On Call)" if "24/7" in specialty else "Day Shift", "timing_factor": timing_factor}

def _get_hardcoded_hospitals():
    """Initializes the hardcoded hospital data."""
    base_hospitals = [
        {"name": "SPARSH Hospital", "address": "No. 1474/138, International Airport Road, Kogilu Cross, Yelahanka", "lat_lon": "13.0862,77.6322"},
        {"name": "Navya Multispeciality Hospital", "address": "BB Road, Gandhi Nagar, Nehru Nagar, Bengaluru", "lat_lon": "13.0984,77.5986"},
        {"name": "K K Hospital", "address": "#9, A-1/A-2, 9th A Cross Rd, Sector A, Yelahanka New Town", "lat_lon": "13.10048,77.59401"},
        {"name": "Cytecare Cancer Hospitals", "address": "Near Bagalur Cross, Yelahanka", "lat_lon": "13.1166,77.6253"},
        {"name": "Aster CMI Hospital", "address": "New International Airport Road, near Sahakara Nagar", "lat_lon": "13.0531,77.5996"},
        {"name": "Government General Hospital", "address": "Yelahanka Old Town, next to the Old Anjanaya Temple", "lat_lon": "13.0991,77.5995"},
    ]
    final_hospitals = []
    base_distance = 6.0 
    for i, hospital in enumerate(base_hospitals):
        name = hospital['name']
        specialty = "General Trauma & ER"
        if 'Cancer' in name or 'Oncology' in name or 'Cytecare' in name: specialty = "Oncology ONLY"
        elif 'SPARSH' in name or 'Aster' in name: specialty = "Critical Care & Neuro"
        elif 'Multi' in name or 'Government' in name: specialty = "General Critical Care"

        simulated_distance = round(base_distance + (i * 0.4) + (i % 3 * 0.2), 1)
        traffic_factor = round(1.0 + (i % 4 * 0.1) + (i % 5 * 0.05), 2) 
        doctors_data = _simulate_doctors(specialty)
        
        hospital['specialty'] = specialty
        hospital['distance_km'] = simulated_distance
        hospital['traffic_factor'] = round(traffic_factor * doctors_data["timing_factor"], 2)
        hospital['doctors'] = doctors_data
        final_hospitals.append(hospital)
    return final_hospitals

def initialize_app_data():
    global HOSPITAL_DATA
    HOSPITAL_DATA = _get_hardcoded_hospitals()
    try:
        with app.app_context(): db.create_all()
    except Exception as e: print(f"Database initialization failed: {e}")

# ==============================================================================
# --- ROUTES ---
# ==============================================================================

@app.route('/', methods=['GET'])
def index():
    """Serves the main HTML application."""
    try:
        with open(str(HTML_FILE_PATH), 'r', encoding='utf-8') as f:
            html_content = f.read()
        return render_template_string(html_content, is_vitals_view=False, case_data=None)
    except FileNotFoundError:
        print(f"\nFATAL ERROR: HTML file not found at: {HTML_FILE_PATH}")
        return f"CRITICAL ERROR: HTML file NOT FOUND. Check path: {HTML_FILE_PATH}", 500
    except Exception as e:
        return f"CRITICAL ERROR reading HTML file: {e}", 500

@app.route('/case_vitals/<int:case_id>', methods=['GET'])
def case_vitals(case_id):
    """Serves the patient vitals page."""
    notification_message_encoded = request.args.get('notification')
    notification_message = urllib.parse.unquote(notification_message_encoded) if notification_message_encoded else None

    with app.app_context():
        case = Case.query.get(case_id)
        if not case: return "Case not found.", 404

        vitals_list = case.vitals_snapshot.split(',')
        patient_data = {
            "id": case.id, "timestamp": case.timestamp.strftime('%Y-%m-%d %H:%M:%S'), "crew_name": case.crew_name, 
            "vitals_snapshot": case.vitals_snapshot, "symptoms_snapshot": case.symptoms_snapshot, 
            "ai_prediction": case.ai_prediction, "is_critical": case.is_critical,
            "hospital_name": case.hospital_name, "hospital_specialty": case.hospital_specialty,
            "eta_min": case.simulated_eta_min, "mews_score": case.mews_score,
            "acceptance_status": case.acceptance_status, "origin_address": case.origin_address,
            "vitals_details": {"age": vitals_list[0], "bp_sys": vitals_list[1], "bp_dias": vitals_list[2], 
                               "hr": vitals_list[3], "o2": vitals_list[4], "temp": vitals_list[5], "rr": vitals_list[6]}
        }
        
        try:
            with open(str(HTML_FILE_PATH), 'r', encoding='utf-8') as f: html_content = f.read()
            return render_template_string(html_content, case_data=patient_data, notification=notification_message, is_vitals_view=True)
        except FileNotFoundError:
            return f"CRITICAL ERROR: HTML file NOT FOUND at {HTML_FILE_PATH}", 500
        except Exception as e:
            return f"Error rendering page: {e}", 500

# --- NEW ROUTE: Listener for Hospital Status Updates ---
@app.route('/api/receive_hospital_update/<int:case_id>', methods=['POST'])
def receive_hospital_update(case_id):
    """Receives push notification from Hospital Server and updates database."""
    data = request.json
    new_status = data.get('status')
    
    with app.app_context():
        case = Case.query.get(case_id)
        if not case:
            return jsonify({"success": False, "message": "Case not found."}), 404
        
        # Update the status in the Ambulance Server's DB instance
        case.acceptance_status = new_status
        db.session.commit()
        print(f"\n[SERVER NOTIFICATION] Case {case_id} status updated to {new_status} via HOSPITAL PUSH.")
        return jsonify({"success": True, "message": f"Status updated for Case {case_id}"}), 200

# --- NEW ROUTE: Check Current Case Status (for Client-Side Logic) ---
@app.route('/api/get_case_status/<int:case_id>', methods=['GET'])
def get_case_status(case_id):
    """Allows the Ambulance Client to check the current status before diverting."""
    with app.app_context():
        case = Case.query.get(case_id)
        if not case:
            return jsonify({"success": False, "status": "NOT_FOUND"}), 404
        return jsonify({"success": True, "status": case.acceptance_status}), 200


@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.json
    crew_name, password, hospital_name, hospital_id = data.get('crew_name'), data.get('password'), data.get('hospital_name'), data.get('hospital_id')
    if not all([crew_name, password, hospital_name, hospital_id]):
        return jsonify({"success": False, "message": "All fields are required for registration."}), 400

    with app.app_context():
        if User.query.filter_by(crew_name=crew_name).first():
            return jsonify({"success": False, "message": "Crew Name already registered. Please log in."}), 409
        new_user = User(crew_name=crew_name, hospital_name=hospital_name, hospital_id=hospital_id)
        new_user.set_password(password)
        try:
            db.session.add(new_user); db.session.commit()
            return jsonify({"success": True, "message": "Registration successful. Please log in."}), 201
        except Exception as e:
            db.session.rollback(); print(f"Flask Registration Database Error: {e}") 
            return jsonify({"success": False, "message": f"Database error during registration: {e}"}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json
    crew_name = data.get('crew_name')
    password = data.get('password')

    if not all([crew_name, password]):
        return jsonify({"success": False, "message": "Name and Password are required."}), 400

    with app.app_context():
        user = User.query.filter_by(crew_name=crew_name).first()

        if user is not None and user.check_password(password):
            return jsonify({"success": True, "message": f"Welcome, {crew_name}!"}), 200
    
        return jsonify({"success": False, "message": "Invalid Crew Name or Password."}), 401

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    """Returns operational counts."""
    with app.app_context():
        user_count = User.query.count()
        patient_count = Case.query.count()
    
    return jsonify({"success": True, "user_count": user_count, "patient_count": patient_count}), 200

@app.route('/api/analyze', methods=['POST'])
def analyze_data():
    """Performs the vitals analysis and route optimization AND saves the case."""
    
    data = request.json
    vitals_str = data.get('vitals')
    symptoms_str = data.get('symptoms', "")
    current_location = data.get('current_location', AMBULANCE_START_LOCATION)
    crew_name = data.get('crew_name', None) 
    
    if not vitals_str:
        return jsonify({"success": False, "message": "Vitals data is missing."}), 400
        
    vitals_list = vitals_str.split(',')
    
    prediction, is_critical = analyze_vitals_from_client(vitals_list, symptoms_str)
    
    try:
        mews_score = calculate_mews_score(vitals_list)
        vitals_trend_json = generate_vitals_trend(vitals_list)
    except Exception as e:
        print(f"DATA GENERATION ERROR: {e}")
        mews_score = 0
        vitals_trend_json = None
    
    if is_critical:
        target_tags = ["Critical Care", "Trauma", "Neuro", "Oncology"]
        eligible = [h for h in HOSPITAL_DATA if any(tag in h['specialty'] for tag in target_tags)]
    else:
        eligible = HOSPITAL_DATA
    
    if not eligible and HOSPITAL_DATA: eligible = HOSPITAL_DATA

    route_info = {}; best_hospital = None; simulated_eta = 0 
    
    try:
        if eligible: best_hospital = min(eligible, key=lambda h: h['distance_km'] * h['traffic_factor']) 
    except ValueError: pass 

    new_case_id = None
    dashboard_status, critical_count = analyze_vitals_for_dashboard(vitals_list)

    if best_hospital:
        speed_km_min = 0.67 ; raw_time_min = best_hospital['distance_km'] / speed_km_min
        simulated_eta = round(raw_time_min * best_hospital['traffic_factor'])
        
        route_info = {"name": best_hospital['name'], "specialty": best_hospital['specialty'], "address": best_hospital['address'], 
            "lat_lon": best_hospital['lat_lon'], "distance_km": f"{best_hospital['distance_km']:.1f}", "simulated_eta": simulated_eta,
            "doctor": best_hospital['doctors'], "origin_address": current_location}
        
        try:
            with app.app_context(): 
                new_case = Case(crew_name=crew_name, vitals_snapshot=vitals_str, symptoms_snapshot=symptoms_str, 
                    ai_prediction=prediction, is_critical=is_critical, origin_address=current_location,
                    hospital_name=best_hospital.get('name'), hospital_specialty=best_hospital.get('specialty'),
                    distance_km=best_hospital.get('distance_km'), simulated_eta_min=simulated_eta,
                    mews_score=mews_score, vitals_trend_json=vitals_trend_json, acceptance_status="AWAITING RESPONSE")
                db.session.add(new_case); db.session.commit(); new_case_id = new_case.id
        except Exception as e:
            db.session.rollback(); print(f"FATAL DATABASE COMMIT ERROR (Case not saved): {e}") 
        
    return jsonify({"success": True, "prediction": prediction, "is_critical": is_critical, "route": route_info,
        "dashboard_status": dashboard_status, "critical_count": critical_count, "new_case_id": new_case_id}), 200

# In app.py, find the function definition below:
@app.route('/api/suggest-alternative/<int:case_id>', methods=['POST'])
def suggest_alternative(case_id):
    data = request.json
    rejected_hospital_name = data.get('current_hospital')
    with app.app_context():
        case = Case.query.get(case_id); 
        if not case: return jsonify({"success": False, "message": "Case not found."}), 404
        
        # --- START FIX: LOAD HISTORY AND ADD CURRENT REJECTION ---
        
        # Load the existing rejection history (if it exists, parse from JSON, otherwise start empty list)
        history = json.loads(case.rejected_history) if case.rejected_history else []
        
        if rejected_hospital_name and rejected_hospital_name not in history:
            history.append(rejected_hospital_name)
        
        # Filter against ALL hospitals in the history list
        rejected_names_set = set(history)
        remaining_hospitals = [
            h for h in HOSPITAL_DATA 
            if h['name'] not in rejected_names_set
        ]

        # --- END FIX ---
        
        if not remaining_hospitals: return jsonify({"success": False, "message": "No other hospitals available in network."}), 404
        try: best_hospital = min(remaining_hospitals, key=lambda h: h['distance_km'] * h['traffic_factor'])
        except ValueError: return jsonify({"success": False, "message": "Error calculating alternative route."}), 500

        speed_km_min = 0.67; raw_time_min = best_hospital['distance_km'] / speed_km_min
        simulated_eta = round(raw_time_min * best_hospital['traffic_factor'])

        new_route_info = {"name": best_hospital['name'], "specialty": best_hospital['specialty'], "address": best_hospital['address'], 
            "lat_lon": best_hospital['lat_lon'], "distance_km": f"{best_hospital['distance_km']:.1f}", 
            "simulated_eta": simulated_eta, "doctor": best_hospital['doctors']}

        try:
            case.hospital_name = best_hospital['name']; case.hospital_specialty = best_hospital['specialty']
            case.distance_km = best_hospital['distance_km']; case.simulated_eta_min = simulated_eta
            case.acceptance_status = "AWAITING RESPONSE"
            
            # --- SAVE UPDATED HISTORY (CRITICAL) ---
            case.rejected_history = json.dumps(history) # Save the full updated list
            db.session.commit()
            
        except Exception as e: db.session.rollback(); return jsonify({"success": False, "message": f"DB Error: {e}"}), 500

        return jsonify({"success": True, "new_hospital": new_route_info}), 200

@app.route('/api/cases', methods=['GET'])
def get_case_history():
    try:
        with app.app_context(): cases = Case.query.order_by(Case.timestamp.desc()).limit(50).all()
        case_list = [{"id": case.id, "timestamp": case.timestamp.strftime('%Y-%m-%d %H:%M:%S'), 
            "crew_name": case.crew_name, "vitals": case.vitals_snapshot, "hospital": case.hospital_name,
            "eta_min": case.simulated_eta_min, "acceptance_status": case.acceptance_status} for case in cases]
        return jsonify({"success": True, "cases": case_list}), 200
    except Exception as e: return jsonify({"success": False, "message": f"Error retrieving cases: {e}"}), 500

@app.route('/api/increment-case-count', methods=['POST'])
def increment_case_count(): return jsonify({"success": True}), 200

def initialize_app_data():
    global HOSPITAL_DATA
    HOSPITAL_DATA = _get_hardcoded_hospitals()
    try:
        with app.app_context(): db.create_all()
    except Exception as e: print(f"Database initialization failed: {e}")

if __name__ == '__main__':
    initialize_app_data()
    print(f"\n=======================================================")
    print(f"--- AMBULANCE SERVER RUNNING ---")
    print(f"--- 1. On THIS Computer: http://127.0.0.1:{SERVER_PORT}")
    print(f"--- 2. On OTHER Devices: http://{MY_IP_ADDRESS}:{SERVER_PORT}")
    print(f"=======================================================\n")
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=True)