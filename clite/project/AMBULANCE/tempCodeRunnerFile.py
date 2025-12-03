# app.py - Main Ambulance Server (Port 5000)

import json
import random
import time
import urllib.parse
from flask import Flask, request, jsonify, render_template_string, redirect 
import os
from datetime import datetime, timedelta # CRITICAL: Import timedelta for trend generation
from pathlib import Path 
import requests 

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from tempCodeRunnerFile import analyze_vitals_from_client

# NOTE: Placeholder for external analysis logic
def analyze_vitals_for_dashboard(vitals_list):
    """Used for dashboard status (now based on MEWS score)."""
    try:
        mews = calculate_mews_score(vitals_list)
    except Exception:
        mews = 0 
        
    if mews >= 5: return "HIGH PRIORITY", 3
    if mews >= 3: return "MEDIUM PRIORITY", 2
    return "STANDARD PRIORITY", 1
# --- END Placeholder ---

# --- GLOBAL METRICS ---
PATIENT_CASE_COUNT = 0 
HOSPITAL_DATA = []

# ==============================================================================
# --- CONFIGURATION (UPDATE THESE VALUES) ---
# ==============================================================================

SERVER_PORT = 5000 
AMBULANCE_START_LOCATION = "17-22, 2nd Main Rd, Vinayak Nagar, Kattigenahalli, Bengaluru, Karnataka 560064"

# --- CRITICAL FIX: Use Pathlib for robust Windows path handling ---
HTML_FILE_PATH = Path(r"C:\Users\CHTAR\OneDrive\Desktop\clite\template\index.html") # *** VERIFY THIS PATH ***

HOSPITAL_DASHBOARD_PORT = 5001 

# ==============================================================================

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ambulance_app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app)

# ==============================================================================
# --- DATABASE MODEL DEFINITION (NOW FINALIZED) ---
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

class Case(db.Model):
    """Stores details of each patient transport case."""
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
    
    # --- CRITICAL NEW FIELDS FOR DASHBOARD ---
    mews_score = db.Column(db.Integer, nullable=True) 
    vitals_trend_json = db.Column(db.Text, nullable=True) 
    # -----------------------------------------
    
    def __repr__(self):
        return f'<Case {self.id} -> {self.hospital_name}>'

# ==============================================================================
# --- HOSPITAL DATA & SIMULATION LOGIC (Unchanged) ---
# ==============================================================================

def _simulate_doctors(specialty):
    """Generates simulated doctor data based on specialty."""
    if "Cardiology" in specialty:
        names = ["Dr. Anjali Rao", "Dr. Vikas Reddy"]
        quals = ["MD, Interventional Cardiologist", "DM, Cardiovascular Surgeon"]
    elif "Critical Care" in specialty or "Multi" in specialty:
        names = ["Dr. Priya Sharma", "Dr. Rohan Kumar"]
        quals = ["MD, Critical Care Specialist", "DNB, Emergency Medicine"]
    elif "Neuro" in specialty:
        names = ["Dr. Sanjeev Reddy", "Dr. Lakshmi V"]
        quals = ["DM, Neurologist", "MS, Neuro Surgeon"]
    else:
        names = ["Dr. Vivek Menon", "Dr. Sara Khan"]
        quals = ["MBBS, Emergency Physician", "MD, General Surgery Resident"]
    
    doctor_index = random.randint(0, len(names) - 1)
    
    time_hour = time.localtime().tm_hour
    timing_factor = 1.0
    if time_hour < 7 or time_hour > 20: 
        timing_factor = 1.2 
    
    return {
        "name": names[doctor_index],
        "qualification": quals[doctor_index],
        "shift": "24/7 (On Call)" if "24/7" in specialty else "Day Shift",
        "timing_factor": timing_factor
    }

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
        if 'Cancer' in name or 'Oncology' in name or 'Cytecare' in name:
            specialty = "Oncology ONLY"
        elif 'SPARSH' in name or 'Aster' in name:
            specialty = "Critical Care & Neuro"
        elif 'Multi' in name or 'Government' in name:
            specialty = "General Critical Care"

        simulated_distance = round(base_distance + (i * 0.4) + (i % 3 * 0.2), 1)
        traffic_factor = round(1.0 + (i % 4 * 0.1) + (i % 5 * 0.05), 2) 
        
        doctors_data = _simulate_doctors(specialty)
        final_traffic_factor = round(traffic_factor * doctors_data["timing_factor"], 2)

        hospital['specialty'] = specialty
        hospital['distance_km'] = simulated_distance
        hospital['traffic_factor'] = final_traffic_factor
        hospital['doctors'] = doctors_data
        
        final_hospitals.append(hospital)
        
    return final_hospitals

# Function to initialize all app data, including hospital data and DB tables
def initialize_app_data():
    global HOSPITAL_DATA
    HOSPITAL_DATA = _get_hardcoded_hospitals()
    # Create database tables within the application context
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        print(f"Database initialization failed: {e}")

# ==============================================================================
# --- NEW: VITAL TRENDING AND MEWS SCORING LOGIC (CRITICAL FOR DASHBOARD) ---
# ==============================================================================

def calculate_mews_score(vitals):
    """Calculates a simulated MEWS score based on current vitals."""
    # Vitals list order: [0: Age, 1: BP_sys, 2: BP_dias, 3: HR, 4: O2, 5: Temp, 6: Resp_Rate]
    bp_sys, hr, resp_rate = float(vitals[1]), float(vitals[3]), float(vitals[6])
    
    score = 0
    # Respiratory Rate (RR) scoring
    if resp_rate < 9 or resp_rate > 25: score += 3
    elif resp_rate > 20: score += 2
    elif resp_rate > 15: score += 1
    
    # Heart Rate (HR) scoring
    if hr < 40 or hr > 130: score += 3
    elif hr > 110: score += 2
    elif hr < 50 or hr > 90: score += 1
    
    # Systolic BP (SBP) scoring
    if bp_sys < 70 or bp_sys > 200: score += 3
    elif bp_sys < 90: score += 2
    elif bp_sys > 180: score += 1
    
    # O2 (simplified)
    if float(vitals[4]) < 90: score += 2
    
    return score

def generate_vitals_trend(vitals_list):
    """Simulates 5 data points over 20 minutes leading up to the current reading."""
    hr_base, bp_sys_base, o2_base = float(vitals_list[3]), float(vitals_list[1]), float(vitals_list[4])
    
    trend_data = {
        'time_labels': [],
        'hr_trend': [],
        'bp_sys_trend': [],
        'o2_trend': []
    }
    
    now = datetime.now()
    
    for i in range(5):
        time_offset = (4 - i) * 5 # 20, 15, 10, 5, 0 minutes ago
        timestamp = (now - timedelta(minutes=time_offset)).strftime('%H:%M')
        
        # Add random noise, ensuring the current reading (i=4) is the exact input
        if i < 4:
            hr_noise = random.uniform(-4, 4)
            bp_noise = random.uniform(-5, 5)
            o2_noise = random.uniform(-1, 1)
            
            hr = round(hr_base + hr_noise)
            bp = round(bp_sys_base + bp_noise)
            o2 = round(o2_base + o2_noise, 1)
        else:
            hr = int(hr_base)
            bp = int(bp_sys_base)
            o2 = float(o2_base)
            
        trend_data['time_labels'].append(timestamp)
        trend_data['hr_trend'].append(hr)
        trend_data['bp_sys_trend'].append(bp)
        trend_data['o2_trend'].append(o2)
        
    return json.dumps(trend_data)
# ==============================================================================


# ==============================================================================
# --- FLASK API ROUTES ---
# ==============================================================================

@app.route('/', methods=['GET'])
def index():
    """Serves the main HTML application."""
    
    try:
        # Use str() to convert the Path object to a string for open()
        with open(str(HTML_FILE_PATH), 'r', encoding='utf-8') as f:
            html_content = f.read()
        return render_template_string(html_content)
    except FileNotFoundError:
        print(f"\nFATAL ERROR: HTML file not found at: {HTML_FILE_PATH}")
        return f"CRITICAL ERROR: HTML file NOT FOUND. Check path: {HTML_FILE_PATH}", 500
    except Exception as e:
        return f"CRITICAL ERROR reading HTML file: {e}", 500

@app.route('/api/register', methods=['POST'])
def register_user():
    """Handles new user registration and stores credentials in the database."""
    data = request.json
    
    crew_name = data.get('crew_name')
    password = data.get('password')
    hospital_name = data.get('hospital_name')
    hospital_id = data.get('hospital_id')
    
    if not all([crew_name, password, hospital_name, hospital_id]):
        return jsonify({"success": False, "message": "All fields are required for registration."}), 400

    # --- CRITICAL FIX: Wrap all DB ops in app_context ---
    with app.app_context():
        # 1. Check if user already exists
        if User.query.filter_by(crew_name=crew_name).first():
            return jsonify({"success": False, "message": "Crew Name already registered. Please log in."}), 409

        # 2. Create and set password
        new_user = User(
            crew_name=crew_name, 
            hospital_name=hospital_name, 
            hospital_id=hospital_id
        )
        new_user.set_password(password)

        # 3. Add and commit the new user (inside the try/except block)
        try:
            db.session.add(new_user)
            db.session.commit()
            return jsonify({"success": True, "message": "Registration successful. Please log in."}), 201
        except Exception as e:
            db.session.rollback()
            # Log the error to your terminal for debugging
            print(f"Flask Registration Database Error: {e}") 
            return jsonify({"success": False, "message": f"Database error during registration: {e}"}), 500
    # --- END CRITICAL FIX ---


@app.route('/api/login', methods=['POST'])
def login_user():
    """Handles user login authentication using the database."""
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
    """Returns operational counts, calculating user count and case count from the database."""
    
    with app.app_context():
        user_count = User.query.count()
        patient_count = Case.query.count()
    
    return jsonify({
        "success": True,
        "user_count": user_count, 
        "patient_count": patient_count 
    }), 200

@app.route('/api/increment-case-count', methods=['POST'])
def increment_case_count():
    """Returns the latest metrics after a case acknowledgement."""
    
    with app.app_context():
        user_count = User.query.count()
        patient_count = Case.query.count()
    
    return jsonify({
        "success": True,
        "user_count": user_count, 
        "patient_count": patient_count,
        "message": "Case count registered."
    }), 200

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
    
    # 1. AI Prediction and Vitals Status
    prediction, is_critical = analyze_vitals_from_client(vitals_list, symptoms_str)
    
    # 2. Generate Dashboard Data (MEWS Score and Vitals Trends)
    try:
        # CRITICAL: These functions rely on accurate vitals_list input
        mews_score = calculate_mews_score(vitals_list)
        vitals_trend_json = generate_vitals_trend(vitals_list)
    except Exception as e:
        print(f"DATA GENERATION ERROR: {e}")
        mews_score = 0
        vitals_trend_json = None
    
    # 3. Route Optimization
    
    if is_critical:
        target_tags = ["Critical Care", "Trauma", "Neuro", "Oncology"]
        eligible = [h for h in HOSPITAL_DATA if any(tag in h['specialty'] for tag in target_tags)]
    else:
        eligible = HOSPITAL_DATA
    
    if not eligible and HOSPITAL_DATA:
        eligible = HOSPITAL_DATA

    route_info = {}
    best_hospital = None
    simulated_eta = 0 
    
    try:
        if eligible:
            best_hospital = min(eligible, key=lambda h: h['distance_km'] * h['traffic_factor']) 
    except ValueError:
        pass 

    # 4. Prepare Route Info and Save Case
    new_case_id = None
    dashboard_status, critical_count = analyze_vitals_for_dashboard(vitals_list)

    if best_hospital:
        speed_km_min = 0.67 
        raw_time_min = best_hospital['distance_km'] / speed_km_min
        simulated_eta = round(raw_time_min * best_hospital['traffic_factor'])
        
        route_info = {
            "name": best_hospital['name'],
            "specialty": best_hospital['specialty'],
            "address": best_hospital['address'],
            "lat_lon": best_hospital['lat_lon'],
            "distance_km": f"{best_hospital['distance_km']:.1f}",
            "simulated_eta": simulated_eta,
            "doctor": best_hospital['doctors'],
            "origin_address": current_location
        }
        
        # DATABASE SAVE LOGIC
        try:
            with app.app_context(): # Ensure context for saving the case too
                new_case = Case(
                    crew_name=crew_name, 
                    vitals_snapshot=vitals_str,
                    symptoms_snapshot=symptoms_str, 
                    ai_prediction=prediction,
                    is_critical=is_critical,
                    origin_address=current_location,
                    hospital_name=best_hospital.get('name'),
                    hospital_specialty=best_hospital.get('specialty'),
                    distance_km=best_hospital.get('distance_km'),
                    simulated_eta_min=simulated_eta,
                    mews_score=mews_score, # CRITICAL NEW FIELD
                    vitals_trend_json=vitals_trend_json # CRITICAL NEW FIELD
                )
                db.session.add(new_case)
                db.session.commit()
                global PATIENT_CASE_COUNT 
                PATIENT_CASE_COUNT += 1 
                # --- Get the ID of the newly saved case ---
                new_case_id = new_case.id
        except Exception as e:
            db.session.rollback()
            print(f"FATAL DATABASE COMMIT ERROR (Case not saved): {e}") 
        
    return jsonify({
        "success": True, 
        "prediction": prediction, 
        "is_critical": is_critical,
        "route": route_info,
        "dashboard_status": dashboard_status,
        "critical_count": critical_count,
        "new_case_id": new_case_id 
    }), 200


@app.route('/api/cases', methods=['GET'])
def get_case_history():
    """Retrieves the list of all recorded case history from the database."""
    try:
        with app.app_context():
            cases = Case.query.order_by(Case.timestamp.desc()).limit(50).all()
        
            case_list = []
            for case in cases:
                case_list.append({
                    "id": case.id,
                    "timestamp": case.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    "crew_name": case.crew_name,
                    "vitals": case.vitals_snapshot,
                    "symptoms": case.symptoms_snapshot,
                    "critical": case.is_critical,
                    "prediction": case.ai_prediction,
                    "origin": case.origin_address,
                    "hospital": case.hospital_name,
                    "specialty": case.hospital_specialty,
                    "distance_km": case.distance_km,
                    "eta_min": case.simulated_eta_min
                })

            return jsonify({"success": True, "cases": case_list}), 200
        
    except Exception as e:
            return jsonify({"success": False, "message": f"Error retrieving cases: {e}"}), 500


if __name__ == '__main__':
    initialize_app_data()
    print(f"--- Flask Server Running on port {SERVER_PORT} ---")
    print(f"--- Database Initialized: ambulance_app.db ---")
    print("--- Visit http://127.0.0.1:5000/ in your browser ---")
    print("--- Access Case History at http://127.0.0.1:5000/api/cases ---")
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=True)