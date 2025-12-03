import numpy as np
import pandas as pd 
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

import socket 
from threading import Thread 
import pickle
import os 
import sys 
import time

# --- Global Configuration and State ---
SERVER_PORT = 2222 
classifier = None # The trained model
sc = None       # The trained scaler
running = True  # Thread control flag

# !!! CRITICAL FIX: UPDATE DATA PATH TO CORRECT FILE NAME !!!
# Ensure this path matches the location where 'human_vital_signs_dataset_2024.csv' is saved.
DATA_PATH = r"C:\Users\CHTAR\OneDrive\Desktop\clite\project\HOSPITAL\human_vital_signs_dataset_2024.csv"

# --- Data Loading and Training Logic ---

def load_and_train_model():
    """Loads data, trains the Random Forest model (11 features), and prepares the scaler."""
    global classifier, sc
    
    filename = DATA_PATH
    
    if not os.path.exists(filename):
        print(f"CRITICAL ERROR: Training file '{filename}' NOT found.")
        print("Please ensure the file path above is correct.")
        return False
        
    try:
        # Load Data
        dataset = pd.read_csv(filename)
        
        # --- FIX: CORRECT 11-FEATURE ORDER for training ---
        # This order MUST match the client-side JavaScript calculation order.
        X_cols_to_use = [
            'Age', 
            'Systolic Blood Pressure', 
            'Diastolic Blood Pressure', 
            'Heart Rate', 
            'Oxygen Saturation', 
            'Body Temperature', 
            'Respiratory Rate',
            # --- DERIVED FEATURES ---
            'Derived_Pulse_Pressure', 
            'Derived_MAP', 
            'Derived_BMI', 
            'Derived_HRV'
        ]

        # Check for missing columns (to debug the previous KeyError)
        missing_cols = [col for col in X_cols_to_use if col not in dataset.columns]
        if missing_cols:
             print(f"CRITICAL ERROR: Missing expected columns in CSV: {missing_cols}")
             print("The loaded file likely lacks the required derived feature columns.")
             return False
             
        X = dataset[X_cols_to_use].values
        
        # 2. Select and convert the target: 'Risk Category' -> 1=High Risk, 0=Low Risk
        Y = dataset['Risk Category'].apply(lambda x: 1 if x == 'High Risk' else 0).values
        Y = Y.astype(int)
        
        # Scale features
        sc = StandardScaler()
        X = sc.fit_transform(X)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, Y, test_size=0.3, random_state=0) 
        
        # --- Training (Random Forest) ---
        # Hyperparameter Tuning: n_estimators increased to 100
        rf_cls = RandomForestClassifier(n_estimators=100, random_state=0) 
        rf_cls.fit(X_train, y_train)
        classifier = rf_cls
        
        # Evaluation
        y_pred = rf_cls.predict(X_test)
        acc = accuracy_score(y_test, y_pred) * 100
        
        print(f"\n--- HOSPITAL AI SERVER INITIALIZED (11-FEATURE) ---")
        print(f"Features Used: {len(X_cols_to_use)} features (Order verified for client).")
        print(f"Model: Random Forest (n_estimators=100) | Accuracy (Test Set): {acc:.2f}%")
        print(f"Server is ready to accept connections on port {SERVER_PORT}...")
        return True
        
    except Exception as e:
        print(f"CRITICAL ERROR during model training/initialization: {e}")
        return False


def predict_condition_internal(data_str):
    """Predicts patient condition (Stable/Critical) using the trained model."""
    global sc, classifier
    
    if classifier is None:
        return "ERROR: Classifier not trained."
    
    try:
        # Client side must send 11 features, not 7!
        testData = [float(val.strip()) for val in data_str.split(",")]
        
        if len(testData) != 11: 
            return f"ERROR: Expected 11 features, but received {len(testData)}. Data Order/Calculation Error on Client."
            
        data = np.asarray([testData])
        data = sc.transform(data) 
        predict_val = classifier.predict(data)[0]
        
        msg = "Predicted Output: Stable"
        if predict_val == 1:
            msg = "Predicted Output: Critical"
            
        return msg
    except Exception as e:
        return f"Prediction Error: {e}"

# --- Server Logic (CloudThread and start_server functions remain unchanged) ---

class CloudThread(Thread): 
    def __init__(self, conn, ip, port): 
        Thread.__init__(self)
        self.conn = conn
        self.ip = ip
        self.port = port

    def run(self): 
        try:
            data_in = self.conn.recv(1024)
            if not data_in: return

            dataset_in = pickle.loads(data_in)
            request = dataset_in[0]
            
            if request == "patientdata":
                data_str = dataset_in[1]
                output = predict_condition_internal(data_str)
                self.conn.send(output.encode())
                print(f"SENT Prediction: {output}")

        except Exception as e:
            print(f"Server Thread Error (Check Pickle/Raw Data Format): {e}") 
        finally:
            self.conn.close()

def start_server():
    global running, server_socket
    
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
        server_socket.bind(('localhost', SERVER_PORT))
    except Exception as e:
        print(f"Error binding server socket: {e}")
        return

    while running:
        try:
            server_socket.listen(4)
            conn, (ip, port) = server_socket.accept()
            newthread = CloudThread(conn, ip, port) 
            newthread.start() 
        except socket.error:
            break
        except Exception as e:
            print(f"Server Accept Error: {e}")
            break

# --- Main Execution ---

if __name__ == '__main__':
    if load_and_train_model():
        try:
            start_server()
        except KeyboardInterrupt:
            pass
        finally:
            running = False
            if 'server_socket' in globals() and server_socket:
                server_socket.close()
            print("\nHospital Server Shutdown.")
    else:
        print("\nServer failed to start due to training error.")