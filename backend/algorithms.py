import numpy as np
from scipy.signal import butter, filtfilt
from scipy.interpolate import CubicSpline
import math
import json
from database import get_db_connection

def calculate_angle(a, b, c):
    """Tính góc giữa 3 điểm: Hông (a), Đầu gối (b - đỉnh góc), Mắt cá (c)"""
    try:
        radians = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(a[1] - b[1], a[0] - b[0])
        angle = abs(radians * 180.0 / math.pi)
        if angle > 180.0:
            angle = 360.0 - angle
        return int(angle)
    except Exception:
        return 0

def resample(data, target_len=101):
    if not data:
        return [0.0 for _ in range(target_len)]
    n = len(data)
    if n == 1:
        return [data[0] for _ in range(target_len)]
    try:
        x = np.linspace(0, 1, n)
        x_new = np.linspace(0, 1, target_len)
        cs = CubicSpline(x, data)
        resampled = cs(x_new)
        return [round(float(v), 2) for v in resampled]
    except Exception:
        # Fallback to linear interpolation
        resampled = []
        for i in range(target_len):
            idx = i * (n - 1) / (target_len - 1)
            low = int(math.floor(idx))
            high = int(math.ceil(idx))
            weight = idx - low
            val = data[low] * (1 - weight) + data[high] * weight
            resampled.append(round(val, 2))
        return resampled

def filter_signal(data):
    if not data or len(data) < 15:
        return data
    try:
        b, a = butter(4, 0.35, btype='low')
        filtered = filtfilt(b, a, data)
        return [round(float(v), 2) for v in filtered]
    except Exception:
        return data

def estimate_socket_moment(fsr_force, cop_y, ankle_y):
    lever_arm = abs(cop_y - ankle_y) / 100.0
    moment = fsr_force * lever_arm
    return round(moment, 2)

def homography_project(x, y):
    h00, h01, h02 = 0.005, 0.0001, -1.0
    h10, h11, h12 = 0.0, 0.005, -2.0
    h20, h21 = 0.0001, 0.0002
    
    w_coord = h20 * x + h21 * y + 1.0
    X = (h00 * x + h01 * y + h02) / w_coord
    Y = (h10 * x + h11 * y + h12) / w_coord
    return X, Y

def compute_dtw_distance(s1, s2):
    n, m = len(s1), len(s2)
    dtw_matrix = np.zeros((n + 1, m + 1))
    dtw_matrix.fill(float('inf'))
    dtw_matrix[0, 0] = 0
    
    w = max(int(0.2 * max(n, m)), 15)
    for i in range(1, n + 1):
        for j in range(max(1, i - w), min(m + 1, i + w)):
            cost = abs(s1[i - 1] - s2[j - 1])
            dtw_matrix[i, j] = cost + min(dtw_matrix[i - 1, j],
                                          dtw_matrix[i, j - 1],
                                          dtw_matrix[i - 1, j - 1])
    return dtw_matrix[n, m]

def analyze_cropped_segment(
    start_t, end_t,
    recorded_timestamps,
    recorded_left_knee, recorded_right_knee,
    recorded_left_ankle, recorded_right_ankle,
    recorded_left_hip, recorded_right_hip,
    recorded_pelvic_tilt,
    healthy_leg, active_session_id
):
    indices = [i for i, t in enumerate(recorded_timestamps) if start_t <= t <= end_t]
    if not indices:
        indices = list(range(len(recorded_timestamps)))
        
    if not indices:
        raise ValueError("Không có dữ liệu camera trong đoạn thời gian được chọn")
        
    s_l_knee = [recorded_left_knee[i] for i in indices]
    s_r_knee = [recorded_right_knee[i] for i in indices]
    s_l_ankle = [recorded_left_ankle[i] for i in indices]
    s_r_ankle = [recorded_right_ankle[i] for i in indices]
    s_l_hip = [recorded_left_hip[i] for i in indices]
    s_r_hip = [recorded_right_hip[i] for i in indices]
    s_pelvic = [recorded_pelvic_tilt[i] for i in indices]
    
    s_l_knee_f = filter_signal(s_l_knee)
    s_r_knee_f = filter_signal(s_r_knee)
    s_l_ankle_f = filter_signal(s_l_ankle)
    s_r_ankle_f = filter_signal(s_r_ankle)
    s_l_hip_f = filter_signal(s_l_hip)
    s_r_hip_f = filter_signal(s_r_hip)
    s_pelvic_f = filter_signal(s_pelvic)
    
    knee_ref = s_l_knee_f if healthy_leg == 'LEFT' else s_r_knee_f
    peaks_idx = []
    for i in range(1, len(knee_ref) - 1):
        if knee_ref[i] > knee_ref[i-1] and knee_ref[i] > knee_ref[i+1] and knee_ref[i] > 35:
            peaks_idx.append(i)
            
    cycles_l_knee = []
    cycles_r_knee = []
    cycles_l_ankle = []
    cycles_r_ankle = []
    cycles_l_hip = []
    cycles_r_hip = []
    cycles_pelvic = []
    
    if len(peaks_idx) >= 2:
        for k in range(len(peaks_idx) - 1):
            p0, p1 = peaks_idx[k], peaks_idx[k+1]
            if p1 - p0 > 10:
                cycles_l_knee.append(resample(s_l_knee_f[p0:p1]))
                cycles_r_knee.append(resample(s_r_knee_f[p0:p1]))
                cycles_l_ankle.append(resample(s_l_ankle_f[p0:p1]))
                cycles_r_ankle.append(resample(s_r_ankle_f[p0:p1]))
                cycles_l_hip.append(resample(s_l_hip_f[p0:p1]))
                cycles_r_hip.append(resample(s_r_hip_f[p0:p1]))
                cycles_pelvic.append(resample(s_pelvic_f[p0:p1]))
                
    if cycles_l_knee:
        left_knee = list(np.mean(cycles_l_knee, axis=0))
        right_knee = list(np.mean(cycles_r_knee, axis=0))
        left_ankle = list(np.mean(cycles_l_ankle, axis=0))
        right_ankle = list(np.mean(cycles_r_ankle, axis=0))
        left_hip = list(np.mean(cycles_l_hip, axis=0))
        right_hip = list(np.mean(cycles_r_hip, axis=0))
        pelvic_tilt = list(np.mean(cycles_pelvic, axis=0))
        num_cycles = len(cycles_l_knee)
    else:
        left_knee = resample(s_l_knee_f)
        right_knee = resample(s_r_knee_f)
        left_ankle = resample(s_l_ankle_f)
        right_ankle = resample(s_r_ankle_f)
        left_hip = resample(s_l_hip_f)
        right_hip = resample(s_r_hip_f)
        pelvic_tilt = resample(s_pelvic_f)
        num_cycles = 1
        
    left_knee = [round(float(v), 2) for v in left_knee]
    right_knee = [round(float(v), 2) for v in right_knee]
    left_ankle = [round(float(v), 2) for v in left_ankle]
    right_ankle = [round(float(v), 2) for v in right_ankle]
    left_hip = [round(float(v), 2) for v in left_hip]
    right_hip = [round(float(v), 2) for v in right_hip]
    pelvic_tilt = [round(float(v), 2) for v in pelvic_tilt]
    
    # Pressure metrics remain unavailable until the insole adapter supplies them.
    plantar_load_symmetry = None
    cop_trajectory = []
    
    duration = end_t - start_t
    if duration <= 0:
        duration = 10.0
    cadence = round(num_cycles * 2 * (60.0 / duration), 1)
    if cadence < 40 or cadence > 160:
        cadence = None
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT height_cm FROM patients WHERE id = (SELECT patient_id FROM sessions WHERE id = ?)", (active_session_id,))
    res = cursor.fetchone()
    height_cm = res[0] if res else 170.0
    conn.close()
    
    stride_length = round(0.52 * (height_cm / 170.0) + (num_cycles / duration) * 0.15, 2)
    
    fatigue_flag = 0
    fatigue_slope = 0.0
    
    return left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, json.dumps(cop_trajectory), cadence, stride_length, fatigue_flag, fatigue_slope
