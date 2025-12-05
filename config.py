import os
class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///instance/ambulance_app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MODEL_PATH = os.getenv("MODEL_PATH", "clite/hospital/services/model.pkl")
