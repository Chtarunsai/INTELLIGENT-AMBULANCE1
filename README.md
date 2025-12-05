# Basic Flask App Structure (Intelligent Ambulance - Basic)

This is a generated basic Flask project skeleton for your Intelligent Ambulance project.
Files added (minimal examples).

## Quick start
1. Copy `.env.example` to `.env` and fill secrets.
2. Install requirements: `pip install -r requirements.txt`
3. Run locally: `python run.py` or `flask run` (ensure FLASK_APP env is set) 
4. Healthcheck: GET /health
5. Prediction endpoint: POST /predict (expects JSON fields like heart_rate, systolic_bp, diastolic_bp, spo2)
