import os
import sqlite3
import math
import json

DB_FILE = os.path.join(os.path.dirname(__file__), "gait_analysis.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn

def init_db():
    """Create any missing database objects without deleting existing data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create Patients Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        age INTEGER CHECK (age > 0 AND age <= 120),
        height_cm REAL NOT NULL,
        weight_kg REAL NOT NULL,
        healthy_leg TEXT CHECK(healthy_leg IN ('LEFT', 'RIGHT')),
        prosthetic_leg TEXT CHECK(prosthetic_leg IN ('LEFT', 'RIGHT')),
        injury_history TEXT DEFAULT '',
        treatment_goals TEXT DEFAULT ''
    );
    """)
    
    # Create Sessions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        patient_id TEXT,
        created_at TEXT NOT NULL,
        is_practice_mode INTEGER DEFAULT 0,
        FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE
    );
    """)
    
    # Create Segments Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS segments (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        start_offset_sec REAL NOT NULL,
        end_offset_sec REAL NOT NULL,
        source_type TEXT CHECK(source_type IN ('manual', 'ai_flag')) NOT NULL,
        note TEXT DEFAULT '',
        video_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    """)
    
    # One row represents the immutable pair of source videos created by a
    # continuous recording. Analysis segments only store offsets into these
    # files, so the originals remain available after changing tabs or
    # restarting the application.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recording_archives (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        frontal_video_id TEXT NOT NULL,
        sagittal_video_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        stopped_at TEXT,
        duration_sec REAL NOT NULL DEFAULT 0,
        frontal_frame_count INTEGER NOT NULL DEFAULT 0,
        sagittal_frame_count INTEGER NOT NULL DEFAULT 0,
        status TEXT CHECK(status IN ('recording', 'complete', 'interrupted'))
            NOT NULL DEFAULT 'recording',
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    """)

    # Create Scans Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        segment_id TEXT,
        scan_type TEXT NOT NULL,
        label TEXT NOT NULL,
        left_knee TEXT,
        right_knee TEXT,
        left_ankle TEXT,
        right_ankle TEXT,
        left_hip TEXT,
        right_hip TEXT,
        pelvic_tilt TEXT,
        plantar_load_symmetry REAL,
        cop_trajectory TEXT,
        cadence REAL,
        stride_length REAL,
        fatigue_flag INTEGER DEFAULT 0,
        fatigue_slope REAL,
        actual_adjustment_degrees REAL DEFAULT 0.0,
        actual_adjustment_notes TEXT DEFAULT '',
        recorded_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(segment_id) REFERENCES segments(id) ON DELETE SET NULL
    );
    """)
    
    # Create Clinical Notes Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clinical_notes (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        pinned_scan_id TEXT,
        note_type TEXT CHECK(note_type IN ('history', 'symptom')) NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(pinned_scan_id) REFERENCES scans(id) ON DELETE SET NULL
    );
    """)
    
    # Create Exercises Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exercises (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        evaluation_method TEXT CHECK(evaluation_method IN ('joint_curve_dtw', 'load_symmetry', 'cop_trajectory')) NOT NULL,
        primary_camera TEXT CHECK(primary_camera IN ('frontal', 'sagittal')) NOT NULL,
        tracked_joints TEXT, -- JSON Array
        reference_video_path TEXT NOT NULL,
        reference_curves TEXT, -- JSON Object
        tolerance_band TEXT, -- JSON Object
        target_symmetry_ratio REAL DEFAULT 50.0,
        symmetry_tolerance REAL DEFAULT 5.0,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)
    
    # Create Practice Attempts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS practice_attempts (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        exercise_id TEXT NOT NULL,
        linked_session_id TEXT,
        sound_leg_curves TEXT, -- JSON Object
        prosthetic_leg_curves TEXT, -- JSON Object
        dtw_distance REAL,
        load_symmetry_actual REAL,
        similarity_score_avg REAL NOT NULL,
        deviation_events TEXT, -- JSON Array
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE,
        FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE RESTRICT,
        FOREIGN KEY(linked_session_id) REFERENCES sessions(id) ON DELETE SET NULL
    );
    """)
    
    # Keep schema changes explicit and traceable. Future migrations should bump
    # this value after applying their ALTER/CREATE statements transactionally.
    cursor.execute("PRAGMA user_version = 2;")

    # Index foreign keys and common history lookups. SQLite does not create
    # indexes automatically for child-key columns.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_patient ON sessions(patient_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scans_session ON scans(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scans_segment ON scans(segment_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recording_archives_session ON recording_archives(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_patient ON clinical_notes(patient_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_session ON clinical_notes(session_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attempts_patient ON practice_attempts(patient_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attempts_exercise ON practice_attempts(exercise_id);")

    conn.commit()
    conn.close()

def populate_demo_data():
    """Optional local demo fixture. Production startup never calls this function."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patients")
    count = cursor.fetchone()[0]
    if count == 0:
        # Patient 1: Nguyễn Văn An (45 tuổi, cụt chân phải)
        cursor.execute("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("p-01", "Nguyễn Văn An", 45, 172.0, 68.0, "LEFT", "RIGHT",
                        "Đứt dây chằng gối phải, cắt cụt 1/3 dưới đùi phải năm 2024.",
                        "Đi lại không cần gậy hỗ trợ, bước lên dốc cầu thang thăng bằng."))
        
        # Session 1
        cursor.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                       ("s-01", "p-01", "2026-07-08T09:30:00Z", 0))
        
        # Curves
        left_knee_base = [62 - math.sin(i / 10) * 12 for i in range(101)]
        right_knee_base = [50 - math.sin(i / 10) * 10 for i in range(101)]
        left_ankle_base = [10 + math.cos(i / 15) * 5 for i in range(101)]
        right_ankle_base = [8 + math.cos(i / 15) * 4 for i in range(101)]
        pelvic_base = [math.sin(i / 8) * 2.5 for i in range(101)]
        left_hip_base = [30 - math.sin(i / 10) * 15 for i in range(101)]
        right_hip_base = [28 - math.sin(i / 10) * 13 for i in range(101)]
        
        empty_cop = []
        
        cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("baseline", "s-01", None, "baseline", "Baseline chân lành",
                        json.dumps(left_knee_base), json.dumps(right_knee_base),
                        json.dumps(left_ankle_base), json.dumps(right_ankle_base),
                        json.dumps(left_hip_base), json.dumps(right_hip_base),
                        json.dumps(pelvic_base), 100.0, json.dumps(empty_cop),
                        112.0, 0.82, 0, 0.0, 0.0, "", "2026-07-08T09:32:00Z"))
        
        # Scan 1: Đánh giá chân giả (Deficit)
        left_knee_s1 = [62 - math.sin(i / 10) * 12 for i in range(101)]
        right_knee_s1 = [42 - math.sin(i / 10) * 8 for i in range(101)]
        left_ankle_s1 = [10 + math.cos(i / 15) * 5 for i in range(101)]
        right_ankle_s1 = [4 + math.cos(i / 15) * 2 for i in range(101)]
        pelvic_s1 = [math.sin(i / 8) * 8.2 for i in range(101)]
        left_hip_s1 = [30 - math.sin(i / 10) * 15 for i in range(101)]
        right_hip_s1 = [20 - math.sin(i / 10) * 8 for i in range(101)]
        
        cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("scan_1", "s-01", None, "scan_1", "Đánh giá chân giả - Scan #1",
                        json.dumps(left_knee_s1), json.dumps(right_knee_s1),
                        json.dumps(left_ankle_s1), json.dumps(right_ankle_s1),
                        json.dumps(left_hip_s1), json.dumps(right_hip_s1),
                        json.dumps(pelvic_s1), 100.0, json.dumps(empty_cop),
                        90.0, 0.62, 0, 0.0, 10.0, "Nới lỏng phuộc gối phải 10 độ", "2026-07-08T09:35:00Z"))
        
        # Scan 2: Đánh giá sau căn chỉnh (Improved)
        left_knee_s2 = [62 - math.sin(i / 10) * 12 for i in range(101)]
        right_knee_s2 = [52 - math.sin(i / 10) * 11 for i in range(101)]
        left_ankle_s2 = [10 + math.cos(i / 15) * 5 for i in range(101)]
        right_ankle_s2 = [8 + math.cos(i / 15) * 4 for i in range(101)]
        pelvic_s2 = [math.sin(i / 8) * 4.1 for i in range(101)]
        left_hip_s2 = [30 - math.sin(i / 10) * 15 for i in range(101)]
        right_hip_s2 = [28 - math.sin(i / 10) * 12 for i in range(101)]
        
        cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("scan_2", "s-01", None, "scan_2", "Đánh giá chân giả - Scan #2",
                        json.dumps(left_knee_s2), json.dumps(right_knee_s2),
                        json.dumps(left_ankle_s2), json.dumps(right_ankle_s2),
                        json.dumps(left_hip_s2), json.dumps(right_hip_s2),
                        json.dumps(pelvic_s2), 100.0, json.dumps(empty_cop),
                        108.0, 0.78, 0, 0.0, 0.0, "Dáng đi cải thiện rõ rệt, kết thúc phiên tinh chỉnh.", "2026-07-08T09:42:00Z"))
        
        # Clinical Notes
        cursor.execute("INSERT INTO clinical_notes VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ("n-01", "p-01", "s-01", None, "history", "Đã từng phẫu thuật chỉnh hình mỏm cụt lần 2 do xước da sát xương.", "2026-07-08T09:31:00Z"))
        cursor.execute("INSERT INTO clinical_notes VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ("n-02", "p-01", "s-01", "scan_1", "symptom", "Cảm giác đau châm chích nhẹ vùng ụ chịu lực phía sau sau khi đi bộ 10 phút.", "2026-07-08T09:36:00Z"))
        
        # Patient 2: Lê Hoàng Nam (32 tuổi, cụt chân trái)
        cursor.execute("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("p-02", "Lê Hoàng Nam", 32, 168.0, 58.0, "RIGHT", "LEFT",
                        "Tai nạn giao thông chấn thương nát cẳng chân trái năm 2025.",
                        "Phục hồi thăng bằng lực đi bộ."))
        
        # Exercises Library (11 exercises)
        exercises_list = [
            ("ex-01", "Đi bộ đường bằng (Level walking)", "joint_curve_dtw", "sagittal", '["knee", "hip"]', "assets/videos/ref_level_walking.mp4", 95.0, 5.0),
            ("ex-02", "Đi lên dốc (Ramp ascent)", "joint_curve_dtw", "sagittal", '["knee"]', "assets/videos/ref_ramp_ascent.mp4", 95.0, 5.0),
            ("ex-03", "Đi xuống dốc (Ramp descent)", "joint_curve_dtw", "sagittal", '["knee"]', "assets/videos/ref_ramp_descent.mp4", 95.0, 5.0),
            ("ex-04", "Leo cầu thang (Stair ascent)", "joint_curve_dtw", "sagittal", '["knee", "hip"]', "assets/videos/ref_stair_ascent.mp4", 95.0, 5.0),
            ("ex-05", "Bước xuống cầu thang (Stair descent)", "joint_curve_dtw", "sagittal", '["knee", "hip"]', "assets/videos/ref_stair_descent.mp4", 95.0, 5.0),
            ("ex-06", "Bước qua chướng ngại vật thấp (Obstacle clearance)", "joint_curve_dtw", "sagittal", '["knee"]', "assets/videos/ref_obstacle.mp4", 95.0, 5.0),
            ("ex-07", "Bài tập chịu tải và chuyển trọng tâm (Weight shifting)", "load_symmetry", "frontal", '[]', "assets/videos/ref_weight_shifting.mp4", 50.0, 5.0),
            ("ex-08", "Đứng lên ngồi xuống ghế (Sit-to-stand)", "load_symmetry", "frontal", '[]', "assets/videos/ref_sit_to_stand.mp4", 50.0, 5.0),
            ("ex-09", "Đi bước ngang / Đi chéo (Side-stepping)", "joint_curve_dtw", "frontal", '["pelvic_tilt"]', "assets/videos/ref_side_stepping.mp4", 95.0, 5.0),
            ("ex-10", "Đi lùi (Backward walking)", "joint_curve_dtw", "sagittal", '["hip"]', "assets/videos/ref_backward.mp4", 95.0, 5.0),
            ("ex-11", "Đi nối gót (Tandem walking)", "load_symmetry", "frontal", '[]', "assets/videos/ref_tandem.mp4", 50.0, 5.0)
        ]
        
        for ex in exercises_list:
            cursor.execute("INSERT INTO exercises (id, name, evaluation_method, primary_camera, tracked_joints, reference_video_path, target_symmetry_ratio, symmetry_tolerance, reference_curves, tolerance_band, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (ex[0], ex[1], ex[2], ex[3], ex[4], ex[5], ex[6], ex[7], "{}", "{}", 1, "2026-07-08T09:00:00Z"))
            
        conn.commit()
    conn.close()
