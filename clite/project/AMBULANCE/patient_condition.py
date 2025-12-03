# patient_condition.py

def check_vital_criticality(vitals_list):
    """
    Analyzes a list of patient vitals to determine the number of critical inputs.

    Args:
        vitals_list (list): A list of seven vital inputs as strings.
            Order MUST be: [0: Age, 1: BP_sys, 2: BP_dias, 3: HR, 4: O2, 5: Temp, 6: Resp_Rate]

    Returns:
        tuple: (critical_count: int, critical_reasons: list)
    """
    
    # 1. Initialize data and counters
    try:
        age = float(vitals_list[0])
        bp_sys = float(vitals_list[1])
        # bp_dias is not used in the primary criticality check, but is here for safety/order
        # bp_dias = float(vitals_list[2])
        hr = float(vitals_list[3])
        o2 = float(vitals_list[4])
        temp = float(vitals_list[5])
        resp_rate = float(vitals_list[6])
    except (ValueError, IndexError):
        # Handle cases where data is missing or non-numeric
        return 7, ["Severe input parsing error (non-numeric/missing data)"] # Force CRITICAL

    critical_count = 0
    reasons_list = []

    # 2. Define Critical Thresholds (Same as your Flask app logic)
    
    # Heart Rate (HR)
    if hr > 110:
        critical_count += 1
        reasons_list.append("HR > 110 (Tachycardia)")
    elif hr < 50:
        critical_count += 1
        reasons_list.append("HR < 50 (Bradycardia)")
            
    # Systolic BP (SBP)
    if bp_sys > 160:
        critical_count += 1
        reasons_list.append("SBP > 160 (Severe Hypertension)")
    elif bp_sys < 90:
        critical_count += 1
        reasons_list.append("SBP < 90 (Hypotension)")
        
    # Respiratory Rate (RR)
    if resp_rate > 24:
        critical_count += 1
        reasons_list.append("RR > 24 (Tachypnea)")
    elif resp_rate < 10:
        critical_count += 1
        reasons_list.append("RR < 10 (Bradypnea)")
        
    # Oxygen Saturation (O2)
    if o2 < 94:
        critical_count += 1
        reasons_list.append("O2 < 94% (Hypoxemia)")
        
    # Temperature (Temp)
    if temp > 100.0:
        critical_count += 1
        reasons_list.append("Temp > 100.0°F (Fever)")
    elif temp < 95.0:
        critical_count += 1
        reasons_list.append("Temp < 95.0°F (Hypothermia)")
        
    # Age-related critical check (Elderly with milder HR/BP issues)
    if age > 75:
        if hr > 90 and hr <= 110: 
            critical_count += 1
            reasons_list.append("Elderly: HR slightly elevated (> 90)")
        if bp_sys < 100 and bp_sys >= 90:
            critical_count += 1
            reasons_list.append("Elderly: SBP slightly low (< 100)")
            
    return critical_count, reasons_list

def analyze_vitals_for_dashboard(vitals_list):
    """
    Determines the patient's condition for dashboard display based on a critical count threshold.

    Args:
        vitals_list (list): A list of vital inputs (strings).

    Returns:
        tuple: (status_string: str, critical_count: int)
    """
    # Get the critical count
    critical_count, _ = check_vital_criticality(vitals_list)
    
    # Apply the new dashboard logic: CRITICAL if 3 or more vitals are critical
    if critical_count >= 3:
        status = "CRITICAL"
    else:
        status = "NORMAL" # Use "NORMAL" for the dashboard as requested

    return status, critical_count

if __name__ == '__main__':
    # --- Example Usage for testing patient_condition.py ---
    
    # Case 1: STABLE/NORMAL (Count: 0)
    stable_vitals = ["40", "120", "80", "75", "98", "98.6", "16"]
    status, count = analyze_vitals_for_dashboard(stable_vitals)
    print(f"Stable Vitals: {status} (Critical Count: {count}) -> Expected NORMAL")
    
    # Case 2: CRITICAL (Count: 3: Hypotension, Hypoxemia, Tachypnea)
    critical_vitals = ["60", "85", "60", "120", "90", "100.0", "28"]
    status, count = analyze_vitals_for_dashboard(critical_vitals)
    print(f"Critical Vitals: {status} (Critical Count: {count}) -> Expected CRITICAL")
    
    # Case 3: NORMAL (Count: 2: Tachycardia, Bradycardia)
    warning_vitals = ["50", "130", "85", "115", "95", "100.0", "18"]
    status, count = analyze_vitals_for_dashboard(warning_vitals)
    print(f"Warning Vitals: {status} (Critical Count: {count}) -> Expected NORMAL")