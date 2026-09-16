import json
import math
import queue
import re
import socket
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

try:
    # Use the shared project implementation when this file is run in AI-ProGait.
    from backend.fsr_force import matrix_to_newton
except (ImportError, ModuleNotFoundError):
    # Standalone fallback: keep this app usable when only FSR_Transmitter.py is
    # copied to another Windows computer. Keep these constants synchronized
    # with backend/fsr_force.py.
    def _analog_to_weight_smooth(adc):
        value = float(adc)
        if value >= 4950.0:
            return 0.0
        if value > 680.0:
            return max(0.0, -0.0868 * value + 434.03)
        return 132728.45 * value ** (-0.889) if value > 0 else 0.0

    def _gram_to_newton(gram):
        return max(0.0, float(gram) * 9.80665 / 1000.0)

    def matrix_to_newton(matrix, unit):
        normalized_unit = str(unit or "raw_adc").strip().lower()
        values = [[float(value) for value in row] for row in matrix]
        if normalized_unit == "newton":
            return (
                [[max(0.0, value) for value in row] for row in values],
                "N",
                "packet",
            )
        if normalized_unit == "gram":
            force_values = [
                [_gram_to_newton(value) for value in row]
                for row in values
            ]
        else:
            force_values = [
                [_gram_to_newton(_analog_to_weight_smooth(value)) for value in row]
                for row in values
            ]
        return force_values, "N_estimated", "formula_estimate"

DEFAULT_TARGET_IP = "127.0.0.1"
DEFAULT_TARGET_PORT = 8765
DEFAULT_SEND_RATE_HZ = 20
DEFAULT_BAUDRATE = 9600
DEFAULT_SERIAL_TIMEOUT = 0.5
MIN_FORCE = 30.0
MAX_FORCE = 5500.0
CHART_WINDOW_SECONDS = 30.0
CHART_MAX_POINTS = 6000
CHART_COLORS = {
    "left": "#2563eb",
    "right": "#ef4444",
    "heel": "#2563eb",
    "midfoot": "#0f9d8a",
    "forefoot": "#ea6a14",
}


def is_outgoing_bluetooth_port(port_info):
    """Windows Bluetooth SPP uses LOCALMFG&0002 for the connect-out port."""
    return "LOCALMFG&0002" in str(getattr(port_info, "hwid", "")).upper()


def selectable_fsr_ports(port_infos):
    """Return ports that can actually connect to FSR modules, never SPP input."""
    infos = list(port_infos)
    outgoing = [item for item in infos if is_outgoing_bluetooth_port(item)]
    if outgoing:
        return outgoing
    return [
        item for item in infos
        if "LOCALMFG&0000" not in str(getattr(item, "hwid", "")).upper()
    ]

INDEX_MAP_RR = [
    [  36,     24,     12,     0  ],
    [  47,     35,     23,     11 ],
    [  37,     25,     13,     1  ],
    [  46,     34,     22,     10 ],
    [  38,     26,     14,     2  ],
    [  45,     33,     21,     9  ],
    [  39,     27,     15,     3  ],
    [  44,     32,     20,     8  ],
    [  40,     28,     16,     4  ],
    [  43,     31,     19,     7  ],
    [  41,     29,     17,     5  ],
    [  42,     30,     18,     6  ],
]

INDEX_MAP_LL = [row[::-1] for row in INDEX_MAP_RR]


def get_force_color(value, min_val=MIN_FORCE, max_val=MAX_FORCE):
    if value < min_val:
        return "#111827"

    t = min(max((value - min_val) / (max_val - min_val), 0.0), 1.0)

    if t < 0.5:
        red = 255
        green = int(255 * (t / 0.5))
        blue = 0
    else:
        red = int(255 * ((1.0 - t) / 0.5))
        green = 255
        blue = 0

    return f"#{red:02x}{green:02x}{blue:02x}"


def validate_matrix(matrix):
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("Ma trận không hợp lệ")
    if not isinstance(matrix[0], list) or not matrix[0]:
        raise ValueError("Ma trận không hợp lệ")

    columns = len(matrix[0])
    normalized = []
    for row in matrix:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError("Cột không nhất quán")
        normalized_row = []
        for value in row:
            if not isinstance(value, (int, float)):
                raise ValueError("Giá trị phải là số")
            if value < 0:
                raise ValueError("Giá trị không được âm")
            normalized_row.append(float(value))
        normalized.append(normalized_row)
    return normalized


def unit_label(unit):
    return {
        'raw_adc': 'ADC thô',
        'newton': 'Newton (N, ước tính)',
    }.get(str(unit).strip().lower(), 'ADC thô')


def matrix_for_unit(raw_adc_matrix, unit):
    '''Convert raw ADC values to the unit selected for preview and UDP.'''
    raw_adc_matrix = validate_matrix(raw_adc_matrix)
    if str(unit).strip().lower() == 'newton':
        force_matrix, _, _ = matrix_to_newton(raw_adc_matrix, 'raw_adc')
        return force_matrix
    return [row[:] for row in raw_adc_matrix]


def color_range_for_unit(unit):
    if str(unit).strip().lower() == 'newton':
        return 0.05, 80.0
    return MIN_FORCE, MAX_FORCE


def parse_hardware_frame(values_list, side, expected_rows=None, expected_columns=None):
    total_values = len(values_list)
    if total_values == 0:
        raise ValueError("Không tìm thấy dữ liệu")

    if total_values == 48:
        mapping = INDEX_MAP_LL if side == "left" else INDEX_MAP_RR
        matrix = []
        for row_indices in mapping:
            row_vals = [values_list[idx] for idx in row_indices]
            matrix.append(row_vals)
    else:
        rows = expected_rows or 12
        cols = expected_columns or 4
        if total_values != rows * cols:
            raise ValueError(
                f"Nhận được {total_values} giá trị, cần {rows * cols}"
            )
        matrix = [
            values_list[r * cols : (r + 1) * cols]
            for r in range(rows)
        ]

    return validate_matrix(matrix), side


def matrix_summary(matrix):
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return total, None, None
    weighted_x = 0.0
    weighted_y = 0.0
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            weighted_x += x * value
            weighted_y += y * value
    return total, weighted_x / total, weighted_y / total


def matrix_region_totals(matrix):
    """Split a 12-row insole like the main backend: forefoot 0:4, mid 4:9, heel 9:12."""
    rows = validate_matrix(matrix)
    row_count = len(rows)
    forefoot_end = max(1, round(row_count * 4 / 12))
    midfoot_end = max(forefoot_end + 1, round(row_count * 9 / 12))
    midfoot_end = min(midfoot_end, row_count)

    def total(first_row, last_row):
        return sum(sum(row) for row in rows[first_row:last_row])

    heel = total(midfoot_end, row_count)
    midfoot = total(forefoot_end, midfoot_end)
    forefoot = total(0, forefoot_end)
    return {
        "heel": heel,
        "midfoot": midfoot,
        "forefoot": forefoot,
        "total": heel + midfoot + forefoot,
    }


def nice_axis_max(value, minimum):
    """Round a chart ceiling to a readable 1/2/5 × 10^n value."""
    target = max(float(value) * 1.12, float(minimum))
    exponent = 10 ** math.floor(math.log10(target)) if target > 0 else 1.0
    normalized = target / exponent
    step = 1.0 if normalized <= 1 else 2.0 if normalized <= 2 else 5.0 if normalized <= 5 else 10.0
    return step * exponent


def build_packet(device_id, side, unit, sequence, matrix):
    return {
        "type": "fsr_matrix",
        "version": 1,
        "device_id": device_id,
        "side": side,
        "unit": unit,
        "sequence": sequence,
        "timestamp_ms": int(time.time() * 1000),
        "rows": len(matrix),
        "columns": len(matrix[0]),
        "values": matrix,
    }


class FSRTransmitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FSR Matrix Transmitter")
        self.root.geometry("1320x860")
        self.root.minsize(1080, 700)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.serial_connections = {}
        self.serial_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.sequence = 0
        self.running = False
        self.workers = []
        self.active_channels = set()
        self.connected_channels = set()
        self.detected_sides = {}
        self.frame_counts = {1: 0, 2: 0}
        self.ema_alpha = tk.DoubleVar(value=0.20)
        self.ema_alpha_value = 0.20
        self.ema_label_text = tk.StringVar(value='EMA alpha: 0.20')
        self.smoothed_matrices = {}
        self.last_raw_matrices = {}
        self.chart_history = {
            "left": deque(maxlen=CHART_MAX_POINTS),
            "right": deque(maxlen=CHART_MAX_POINTS),
        }
        self.chart_started_at = time.monotonic()
        self.chart_unit = "newton"
        self.chart_redraw_pending = False
        self.total_chart_canvas = None
        self.region_chart_canvas = None

        self.log_lock = threading.Lock()
        self.log_handle = None
        self.log_path = None
        self.log_started_at = None
        self.log_sample_count = 0

        self.playback_records = []
        self.playback_index = 0
        self.playback_after_id = None
        self.playback_path = None

        self.preview_state = {
            "left": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
            "right": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
        }

        self.target_ip = tk.StringVar(value=DEFAULT_TARGET_IP)
        self.target_port = tk.StringVar(value=str(DEFAULT_TARGET_PORT))
        self.device_id = tk.StringVar(value="fsr-device-01")
        self.side = tk.StringVar(value="right")
        self.unit = tk.StringVar(value="newton")
        self._selected_unit = self.unit.get()
        self.preview_unit_label = tk.StringVar(
            value=f'Đơn vị hiển thị/gửi: {unit_label(self._selected_unit)}'
        )
        self.unit.trace_add('write', self._on_unit_change)
        self.rate_hz = tk.StringVar(value=str(DEFAULT_SEND_RATE_HZ))

        self.com_port_1 = tk.StringVar()
        self.com_port_2 = tk.StringVar()
        self.baudrate = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        self.matrix_rows = tk.StringVar(value="12")
        self.matrix_columns = tk.StringVar(value="4")

        self.status = tk.StringVar(value="Sẵn sàng")
        self.summary_left = tk.StringVar(value="12\u00d74 | Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u")
        self.summary_right = tk.StringVar(value="12\u00d74 | Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u")
        self.bt_button_text = tk.StringVar(value="Kết nối 2 FSR")
        self.module_code = tk.StringVar(value="--")
        self.channel_status_1 = tk.StringVar(value="Chưa kết nối")
        self.channel_status_2 = tk.StringVar(value="Chưa kết nối")
        self.log_button_text = tk.StringVar(value="Bắt đầu lưu log")
        self.log_status = tk.StringVar(value="Chưa lưu log")
        self.playback_status = tk.StringVar(value="Chưa mở log")
        self.connection_toggle_text = tk.StringVar(value="▼ Thu gọn thiết lập kết nối")
        self.connection_panel_collapsed = False
        self.connection_settings_body = None
        self.main_notebook = None
        self.total_chart_tab = None

        self._build_ui()
        self.refresh_com_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        connection_section = ttk.Frame(container)
        connection_section.pack(fill=tk.X)
        ttk.Button(
            connection_section,
            textvariable=self.connection_toggle_text,
            command=self._toggle_connection_panel,
        ).pack(fill=tk.X)
        self.connection_settings_body = ttk.Frame(connection_section)
        self.connection_settings_body.pack(fill=tk.X, pady=(6, 0))

        bluetooth = ttk.LabelFrame(
            self.connection_settings_body,
            text="Bluetooth Serial - nhận đồng thời 2 chân",
            padding=10,
        )
        bluetooth.pack(fill=tk.X)

        ttk.Label(bluetooth, text="FSR 1 (tự nhận LL/RR)").grid(
            row=0, column=0, padx=(0, 5), sticky="w"
        )
        self.com_box_1 = ttk.Combobox(
            bluetooth, textvariable=self.com_port_1, width=35, state="readonly"
        )
        self.com_box_1.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        self.com_box_1.bind("<Button-1>", self._refresh_com_ports_from_event)
        ttk.Label(bluetooth, textvariable=self.channel_status_1, width=22).grid(
            row=0, column=2, padx=(0, 8), sticky="w"
        )

        ttk.Label(bluetooth, text="FSR 2 (tự nhận LL/RR)").grid(
            row=1, column=0, padx=(0, 5), pady=(8, 0), sticky="w"
        )
        self.com_box_2 = ttk.Combobox(
            bluetooth, textvariable=self.com_port_2, width=35, state="readonly"
        )
        self.com_box_2.grid(row=1, column=1, padx=(0, 8), pady=(8, 0), sticky="ew")
        self.com_box_2.bind("<Button-1>", self._refresh_com_ports_from_event)
        ttk.Label(bluetooth, textvariable=self.channel_status_2, width=22).grid(
            row=1, column=2, padx=(0, 8), pady=(8, 0), sticky="w"
        )

        ttk.Button(bluetooth, text="Quét lại", command=self.refresh_com_ports).grid(
            row=0, column=3, padx=(0, 12), sticky="ew"
        )
        ttk.Label(bluetooth, text="Baudrate").grid(row=0, column=4, padx=(0, 5), sticky="w")
        ttk.Combobox(
            bluetooth,
            textvariable=self.baudrate,
            values=("9600", "19200", "38400", "57600", "115200"),
            width=9,
            state="readonly",
        ).grid(row=0, column=5, sticky="w")

        self.bt_button = ttk.Button(
            bluetooth, textvariable=self.bt_button_text, command=self.toggle_stream
        )
        self.bt_button.grid(row=1, column=3, columnspan=3, padx=(0, 0), pady=(8, 0), sticky="ew")

        ttk.Label(bluetooth, text="Kích thước").grid(row=2, column=0, pady=(10, 0), sticky="w")
        dimensions = ttk.Frame(bluetooth)
        dimensions.grid(row=2, column=1, pady=(10, 0), sticky="w")
        ttk.Label(dimensions, text="Hàng").pack(side=tk.LEFT)
        ttk.Entry(dimensions, textvariable=self.matrix_rows, width=6).pack(side=tk.LEFT, padx=(5, 12))
        ttk.Label(dimensions, text="Cột").pack(side=tk.LEFT)
        ttk.Entry(dimensions, textvariable=self.matrix_columns, width=6).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(bluetooth, text="Đã nhận:").grid(
            row=2, column=2, pady=(10, 0), padx=(0, 5), sticky="e"
        )
        ttk.Label(
            bluetooth,
            textvariable=self.module_code,
            font=("Segoe UI", 10, "bold"),
            foreground="#2563eb",
        ).grid(row=2, column=3, columnspan=3, pady=(10, 0), sticky="w")

        bluetooth.columnconfigure(1, weight=1)

        connection = ttk.LabelFrame(
            self.connection_settings_body, text="Đích nhận UDP", padding=10
        )
        connection.pack(fill=tk.X, pady=(10, 0))
        fields = [
            ("IP", self.target_ip, 18),
            ("Port", self.target_port, 8),
            ("Device ID", self.device_id, 18),
            ("Tần số tối đa (Hz)", self.rate_hz, 8),
        ]
        for column, (label, variable, width) in enumerate(fields):
            ttk.Label(connection, text=label).grid(row=0, column=column * 2, padx=(0, 5), sticky="w")
            ttk.Entry(connection, textvariable=variable, width=width).grid(
                row=0, column=column * 2 + 1, padx=(0, 12), sticky="ew"
            )

        ttk.Label(connection, text="Chân (gửi thử)").grid(row=1, column=0, pady=(10, 0), sticky="w")
        ttk.Combobox(
            connection, textvariable=self.side, values=("left", "right"), width=15, state="readonly"
        ).grid(row=1, column=1, pady=(10, 0), sticky="w")
        ttk.Label(connection, text="Đơn vị").grid(row=1, column=2, pady=(10, 0), sticky="w")
        ttk.Combobox(
            connection, textvariable=self.unit, values=("raw_adc", "newton"), width=15, state="readonly"
        ).grid(row=1, column=3, pady=(10, 0), sticky="w")

        ttk.Label(connection, textvariable=self.preview_unit_label).grid(
            row=2, column=2, columnspan=2, pady=(8, 0), sticky='w'
        )

        ttk.Label(connection, textvariable=self.ema_label_text).grid(
            row=1, column=4, pady=(10, 0), padx=(12, 5), sticky='e'
        )
        ttk.Scale(
            connection, from_=0.01, to=1.0, variable=self.ema_alpha,
            command=self._on_alpha_change,
        ).grid(row=1, column=5, columnspan=3, pady=(10, 0), sticky='ew')

        log_controls = ttk.LabelFrame(container, text="Biểu đồ và FSR log", padding=8)
        log_controls.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(
            log_controls,
            textvariable=self.log_button_text,
            command=self.toggle_logging,
        ).pack(side=tk.LEFT)
        ttk.Button(
            log_controls, text="Mở và chạy log", command=self.open_and_play_log
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            log_controls, text="Dừng phát", command=self.stop_playback
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            log_controls, text="Xóa biểu đồ", command=self.clear_charts
        ).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(
            log_controls, text="Xóa file log", command=self.delete_log_file
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(log_controls, textvariable=self.playback_status).pack(side=tk.RIGHT)
        ttk.Label(log_controls, textvariable=self.log_status).pack(side=tk.RIGHT, padx=(0, 18))

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True, pady=12)
        self.main_notebook = notebook

        map_tab = ttk.Frame(notebook)
        total_chart_tab = ttk.Frame(notebook, padding=8)
        region_chart_tab = ttk.Frame(notebook, padding=8)
        self.total_chart_tab = total_chart_tab
        notebook.add(map_tab, text="Bản đồ lực")
        notebook.add(total_chart_tab, text="Tổng tải")
        notebook.add(region_chart_tab, text="Ba vùng bàn chân")

        body = ttk.Frame(map_tab)
        body.pack(fill=tk.BOTH, expand=True, pady=12)

        editor_frame = ttk.LabelFrame(body, text="Ma trận FSR dạng JSON (gửi thử)", padding=10)
        editor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 6))
        self.matrix_text = tk.Text(editor_frame, width=31, wrap=tk.NONE, font=("Consolas", 11))
        self.matrix_text.pack(fill=tk.BOTH, expand=True)
        sample_12x4 = "[\n" + ",\n".join(["  [0, 0, 0, 0]"] * 12) + "\n]"
        self.matrix_text.insert("1.0", sample_12x4)

        preview_frame = ttk.LabelFrame(
            body, text="Xem trước lực từng điểm - 2 chân", padding=8
        )
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        left_preview = ttk.LabelFrame(preview_frame, text="CHÂN TRÁI (LL)", padding=5)
        left_preview.grid(row=0, column=0, padx=(0, 4), sticky="nsew")
        self.canvas_left = tk.Canvas(
            left_preview, background="#111827", highlightthickness=0
        )
        self.canvas_left.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            left_preview, textvariable=self.summary_left, anchor="w", justify=tk.LEFT
        ).pack(fill=tk.X, pady=(6, 0))

        right_preview = ttk.LabelFrame(preview_frame, text="CHÂN PHẢI (RR)", padding=5)
        right_preview.grid(row=0, column=1, padx=(4, 0), sticky="nsew")
        self.canvas_right = tk.Canvas(
            right_preview, background="#111827", highlightthickness=0
        )
        self.canvas_right.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            right_preview, textvariable=self.summary_right, anchor="w", justify=tk.LEFT
        ).pack(fill=tk.X, pady=(6, 0))

        self.total_chart_canvas = tk.Canvas(
            total_chart_tab,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.total_chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.total_chart_canvas.bind("<Configure>", self._on_chart_resize)

        self.region_chart_canvas = tk.Canvas(
            region_chart_tab,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.region_chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.region_chart_canvas.bind("<Configure>", self._on_chart_resize)

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Xem ma trận", command=self.preview_manual_matrix).pack(side=tk.LEFT)
        ttk.Button(controls, text="Gửi 1 frame", command=self.send_manual_once).pack(side=tk.LEFT, padx=8)
        ttk.Label(controls, textvariable=self.status).pack(side=tk.RIGHT)
        empty_matrix = [[0.0] * 4 for _ in range(12)]
        self.root.after(80, self.draw_matrix, empty_matrix, "left")
        self.root.after(80, self.draw_matrix, empty_matrix, "right")
        self.root.after(120, self._redraw_charts)

    def _toggle_connection_panel(self):
        self._set_connection_panel_collapsed(not self.connection_panel_collapsed)

    def _set_connection_panel_collapsed(self, collapsed):
        if self.connection_settings_body is None:
            return
        self.connection_panel_collapsed = bool(collapsed)
        if self.connection_panel_collapsed:
            self.connection_settings_body.pack_forget()
            self.connection_toggle_text.set("▶ Hiện thiết lập kết nối")
        else:
            if not self.connection_settings_body.winfo_manager():
                self.connection_settings_body.pack(fill=tk.X, pady=(6, 0))
            self.connection_toggle_text.set("▼ Thu gọn thiết lập kết nối")
        self.root.after_idle(self._schedule_chart_redraw)

    def _on_unit_change(self, *_args):
        selected = self.unit.get().strip().lower()
        self._selected_unit = selected if selected in ('raw_adc', 'newton') else 'raw_adc'
        self.clear_charts()
        self.preview_unit_label.set(
            f'Đơn vị hiển thị/gửi: {unit_label(self._selected_unit)}'
        )
        for side, raw_matrix in list(self.last_raw_matrices.items()):
            self.draw_matrix(
                matrix_for_unit(raw_matrix, self._selected_unit),
                side,
                self._selected_unit,
            )
            self._append_chart_sample(
                side,
                matrix_for_unit(raw_matrix, self._selected_unit),
                unit=self._selected_unit,
            )
        if self.last_raw_matrices:
            self.status.set(f'Đã đổi sang {unit_label(self._selected_unit)}')

    def _on_alpha_change(self, value):
        self.ema_alpha_value = min(max(float(value), 0.01), 1.0)
        self.ema_label_text.set(f'EMA alpha: {self.ema_alpha_value:.2f}')

    def _apply_ema_filter(self, channel_id, matrix):
        previous = self.smoothed_matrices.get(channel_id)
        if (
            previous is None
            or len(previous) != len(matrix)
            or len(previous[0]) != len(matrix[0])
        ):
            filtered = [row[:] for row in matrix]
        else:
            alpha = self.ema_alpha_value
            filtered = [
                [
                    alpha * value
                    + (1.0 - alpha) * previous[row_index][column_index]
                    for column_index, value in enumerate(row)
                ]
                for row_index, row in enumerate(matrix)
            ]
        self.smoothed_matrices[channel_id] = filtered
        return [row[:] for row in filtered]

    @staticmethod
    def _chart_unit_label(unit):
        return "N" if str(unit).lower() == "newton" else "ADC"

    def _append_chart_sample(self, side, matrix, sample_time=None, unit=None):
        if side not in self.chart_history:
            return
        matrix = validate_matrix(matrix)
        unit = str(unit or self._selected_unit).lower()
        if self.chart_unit is not None and self.chart_unit != unit:
            for history in self.chart_history.values():
                history.clear()
            self.chart_started_at = time.monotonic()
        self.chart_unit = unit
        regions = matrix_region_totals(matrix)
        timestamp = (
            float(sample_time)
            if sample_time is not None
            else time.monotonic() - self.chart_started_at
        )
        self.chart_history[side].append(
            {
                "time": max(0.0, timestamp),
                "total": regions["total"],
                "heel": regions["heel"],
                "midfoot": regions["midfoot"],
                "forefoot": regions["forefoot"],
            }
        )
        self._schedule_chart_redraw()

    def _on_chart_resize(self, _event=None):
        self._schedule_chart_redraw()

    def _schedule_chart_redraw(self):
        if self.chart_redraw_pending:
            return
        self.chart_redraw_pending = True
        self.root.after(80, self._redraw_charts)

    def _redraw_charts(self):
        self.chart_redraw_pending = False
        if self.total_chart_canvas is not None:
            self._draw_total_chart()
        if self.region_chart_canvas is not None:
            self._draw_region_chart()

    @staticmethod
    def _visible_history(history, x_start, x_end):
        return [point for point in history if x_start <= point["time"] <= x_end]

    @staticmethod
    def _draw_chart_line(canvas, points, x_map, y_map, color, dash=None):
        segment = []
        previous_time = None
        for point in points:
            timestamp, value = point
            if previous_time is not None and timestamp - previous_time > 0.6:
                if len(segment) >= 4:
                    canvas.create_line(
                        *segment, fill=color, width=2.5, dash=dash, smooth=False
                    )
                segment = []
            segment.extend((x_map(timestamp), y_map(value)))
            previous_time = timestamp
        if len(segment) >= 4:
            canvas.create_line(
                *segment, fill=color, width=2.5, dash=dash, smooth=False
            )

    def _draw_chart_frame(self, canvas, title, series, legend, minimum_y):
        canvas.delete("all")
        width = max(canvas.winfo_width(), 360)
        height = max(canvas.winfo_height(), 260)
        left, right, top, bottom = 76, 24, 82, 58
        plot_left, plot_top = left, top
        plot_right, plot_bottom = width - right, height - bottom

        canvas.create_text(
            width / 2, 23, text=title, fill="#172033", font=("Segoe UI", 14, "bold")
        )

        all_times = [
            point["time"]
            for side in ("left", "right")
            for point in self.chart_history[side]
        ]
        latest_time = max(all_times, default=0.0)
        x_end = max(CHART_WINDOW_SECONDS, latest_time)
        x_start = max(0.0, x_end - CHART_WINDOW_SECONDS)

        visible_by_side = {
            side: self._visible_history(self.chart_history[side], x_start, x_end)
            for side in ("left", "right")
        }
        visible_values = []
        for item in series:
            for point in visible_by_side[item["side"]]:
                visible_values.append(point[item["field"]])
        y_max = nice_axis_max(max(visible_values, default=0.0), minimum_y)

        def x_map(value):
            span = max(x_end - x_start, 1e-6)
            return plot_left + (value - x_start) / span * (plot_right - plot_left)

        def y_map(value):
            return plot_bottom - max(0.0, value) / y_max * (plot_bottom - plot_top)

        for index in range(6):
            fraction = index / 5
            x = plot_left + fraction * (plot_right - plot_left)
            y = plot_bottom - fraction * (plot_bottom - plot_top)
            canvas.create_line(x, plot_top, x, plot_bottom, fill="#e2e8f0")
            canvas.create_line(plot_left, y, plot_right, y, fill="#e2e8f0")
            canvas.create_text(
                x,
                plot_bottom + 20,
                text=f"{x_start + fraction * (x_end - x_start):.0f}",
                fill="#5e6b7a",
                font=("Segoe UI", 9),
            )
            canvas.create_text(
                plot_left - 12,
                y,
                text=f"{fraction * y_max:.0f}",
                anchor="e",
                fill="#5e6b7a",
                font=("Segoe UI", 9),
            )

        canvas.create_rectangle(
            plot_left, plot_top, plot_right, plot_bottom, outline="#9eacbb", width=1
        )
        canvas.create_text(
            (plot_left + plot_right) / 2,
            height - 18,
            text="Thời gian (s)",
            fill="#334155",
            font=("Segoe UI", 10),
        )
        canvas.create_text(
            19,
            (plot_top + plot_bottom) / 2,
            text=f"Lực ({self._chart_unit_label(self.chart_unit)})",
            angle=90,
            fill="#334155",
            font=("Segoe UI", 10),
        )

        legend_x = plot_left
        legend_y = 52
        for label, color, dash in legend:
            canvas.create_line(
                legend_x, legend_y, legend_x + 28, legend_y,
                fill=color, width=3, dash=dash,
            )
            canvas.create_text(
                legend_x + 35,
                legend_y,
                text=label,
                anchor="w",
                fill="#334155",
                font=("Segoe UI", 9),
            )
            label_width = max(54, len(label) * 7)
            legend_x += 48 + label_width

        for item in series:
            points = [
                (point["time"], point[item["field"]])
                for point in visible_by_side[item["side"]]
            ]
            self._draw_chart_line(
                canvas,
                points,
                x_map,
                y_map,
                item["color"],
                item.get("dash"),
            )

        if not visible_values:
            canvas.create_text(
                (plot_left + plot_right) / 2,
                (plot_top + plot_bottom) / 2,
                text="Chưa có dữ liệu FSR",
                fill="#64748b",
                font=("Segoe UI", 12),
            )

    def _draw_total_chart(self):
        self._draw_chart_frame(
            self.total_chart_canvas,
            "TỔNG TẢI TRÊN TỪNG CHÂN",
            [
                {"side": "left", "field": "total", "color": CHART_COLORS["left"]},
                {
                    "side": "right",
                    "field": "total",
                    "color": CHART_COLORS["right"],
                    "dash": (8, 4),
                },
            ],
            [
                ("Chân trái", CHART_COLORS["left"], None),
                ("Chân phải", CHART_COLORS["right"], (8, 4)),
            ],
            100.0 if self.chart_unit == "newton" else 1000.0,
        )

    def _draw_region_chart(self):
        series = []
        for side, dash in (("left", None), ("right", (8, 4))):
            for field in ("heel", "midfoot", "forefoot"):
                series.append(
                    {
                        "side": side,
                        "field": field,
                        "color": CHART_COLORS[field],
                        "dash": dash,
                    }
                )
        self._draw_chart_frame(
            self.region_chart_canvas,
            "PHÂN BỐ LỰC THEO BA VÙNG BÀN CHÂN",
            series,
            [
                ("Gót", CHART_COLORS["heel"], None),
                ("Giữa", CHART_COLORS["midfoot"], None),
                ("Mũi", CHART_COLORS["forefoot"], None),
                ("Trái: liền", "#475569", None),
                ("Phải: đứt", "#475569", (8, 4)),
            ],
            50.0 if self.chart_unit == "newton" else 500.0,
        )

    def clear_charts(self):
        for history in self.chart_history.values():
            history.clear()
        self.chart_started_at = time.monotonic()
        self.chart_unit = self._selected_unit
        self._schedule_chart_redraw()
        self.status.set("Đã xóa dữ liệu đang vẽ trên biểu đồ")

    def _default_log_directory(self):
        directory = Path(__file__).resolve().parent / "fsr_logs"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def toggle_logging(self):
        if self.log_handle is not None:
            self._stop_logging()
            return

        directory = self._default_log_directory()
        default_name = time.strftime("fsr_%Y%m%d_%H%M%S.jsonl")
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Lưu FSR log",
            initialdir=str(directory),
            initialfile=default_name,
            defaultextension=".jsonl",
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
            confirmoverwrite=True,
        )
        if not selected:
            return

        try:
            handle = open(selected, "w", encoding="utf-8", buffering=1)
            header = {
                "type": "fsr_log",
                "version": 1,
                "created_at": time.time(),
                "description": "Raw ADC, EMA ADC and displayed FSR matrix",
            }
            handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        except OSError as exc:
            messagebox.showerror("Không lưu được log", str(exc))
            return

        with self.log_lock:
            self.log_handle = handle
            self.log_path = Path(selected).resolve()
            self.log_started_at = time.monotonic()
            self.log_sample_count = 0
        self.log_button_text.set("Dừng và đóng log")
        self.log_status.set(f"Đang lưu: {Path(selected).name}")

    def _stop_logging(self, status_text=None):
        with self.log_lock:
            handle = self.log_handle
            path = self.log_path
            count = self.log_sample_count
            self.log_handle = None
            self.log_started_at = None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
        self.log_button_text.set("Bắt đầu lưu log")
        if status_text is not None:
            self.log_status.set(status_text)
        elif path is not None:
            self.log_status.set(f"Đã lưu {count} mẫu: {path.name}")
        else:
            self.log_status.set("Chưa lưu log")

    def _write_log_sample(
        self,
        side,
        raw_matrix,
        filtered_raw_matrix,
        display_matrix,
        unit,
        received_monotonic,
    ):
        with self.log_lock:
            handle = self.log_handle
            started_at = self.log_started_at
            if handle is None or started_at is None:
                return
            record = {
                "type": "fsr_sample",
                "elapsed": max(0.0, received_monotonic - started_at),
                "received_at": time.time(),
                "side": side,
                "unit": unit,
                "rows": len(display_matrix),
                "columns": len(display_matrix[0]),
                "raw_values": raw_matrix,
                "filtered_raw_values": filtered_raw_matrix,
                "values": display_matrix,
            }
            try:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.log_sample_count += 1
                count = self.log_sample_count
                if count % 20 == 0:
                    handle.flush()
                    self.root.after(
                        0,
                        self.log_status.set,
                        f"Đang lưu: {self.log_path.name} · {count} mẫu",
                    )
            except OSError as exc:
                self.log_handle = None
                self.log_started_at = None
                try:
                    handle.close()
                except OSError:
                    pass
                self.root.after(0, self._log_failed, str(exc))

    def _log_failed(self, error_message):
        self.log_button_text.set("Bắt đầu lưu log")
        self.log_status.set("Lỗi ghi log")
        messagebox.showerror("Lỗi ghi FSR log", error_message)

    def open_and_play_log(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Mở FSR log",
            initialdir=str(self._default_log_directory()),
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
        )
        if not selected:
            return

        records = []
        try:
            with open(selected, "r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Dòng {line_number}: JSON không hợp lệ") from exc
                    if record.get("type") == "fsr_log":
                        continue
                    side = str(record.get("side", "")).lower()
                    if side not in ("left", "right"):
                        continue
                    matrix = record.get("values")
                    unit = str(record.get("unit", "raw_adc")).lower()
                    if record.get("forceValues") and unit.lower().startswith("n"):
                        matrix = record["forceValues"]
                        unit = "newton"
                    matrix = validate_matrix(matrix)
                    elapsed = float(record.get("elapsed", record.get("time", 0.0)))
                    records.append(
                        {
                            "elapsed": max(0.0, elapsed),
                            "side": side,
                            "unit": "newton" if unit in ("n", "n_estimated") else unit,
                            "values": matrix,
                            "raw_values": record.get("raw_values", record.get("rawAdcValues")),
                        }
                    )
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Không mở được FSR log", str(exc))
            return

        if not records:
            messagebox.showwarning("FSR log trống", "Không tìm thấy mẫu FSR hợp lệ trong file.")
            return

        records.sort(key=lambda item: item["elapsed"])
        if self.running:
            self._stop_stream("Đã ngắt FSR thật để chạy log")
        self._stop_logging()
        self.stop_playback(silent=True)
        self.clear_charts()
        self.playback_records = records
        self.playback_index = 0
        self.playback_path = Path(selected).resolve()
        self.chart_unit = records[0]["unit"]
        self.playback_status.set(f"Đang chạy: {self.playback_path.name}")
        self._playback_step()

    def _playback_step(self):
        self.playback_after_id = None
        if self.playback_index >= len(self.playback_records):
            name = self.playback_path.name if self.playback_path else "log"
            self.playback_status.set(f"Đã chạy xong: {name}")
            return

        record = self.playback_records[self.playback_index]
        matrix = record["values"]
        side = record["side"]
        unit = record["unit"]
        raw_values = record.get("raw_values")
        if isinstance(raw_values, list):
            try:
                self.last_raw_matrices[side] = validate_matrix(raw_values)
            except ValueError:
                pass
        self.draw_matrix(matrix, side, unit)
        self._append_chart_sample(side, matrix, record["elapsed"], unit)
        self.playback_index += 1

        if self.playback_index < len(self.playback_records):
            next_record = self.playback_records[self.playback_index]
            delay_seconds = max(0.0, next_record["elapsed"] - record["elapsed"])
            delay_ms = max(1, min(2000, round(delay_seconds * 1000)))
            self.playback_after_id = self.root.after(delay_ms, self._playback_step)
        else:
            self.playback_status.set(f"Đã chạy xong: {self.playback_path.name}")

    def stop_playback(self, silent=False):
        if self.playback_after_id is not None:
            try:
                self.root.after_cancel(self.playback_after_id)
            except tk.TclError:
                pass
        was_running = self.playback_after_id is not None
        self.playback_after_id = None
        self.playback_records = []
        self.playback_index = 0
        if not silent:
            self.playback_status.set("Đã dừng phát log" if was_running else "Chưa chạy log")

    def delete_log_file(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Chọn FSR log cần xóa",
            initialdir=str(self._default_log_directory()),
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
        )
        if not selected:
            return
        path = Path(selected).resolve()
        if not messagebox.askyesno(
            "Xóa FSR log",
            f"Xóa vĩnh viễn file này?\n\n{path}",
            parent=self.root,
        ):
            return

        if self.log_path == path and self.log_handle is not None:
            self._stop_logging("Đã đóng log trước khi xóa")
        if self.playback_path == path:
            self.stop_playback(silent=True)
        try:
            path.unlink()
        except OSError as exc:
            messagebox.showerror("Không xóa được log", str(exc))
            return
        self.log_status.set(f"Đã xóa: {path.name}")
        self.playback_status.set("Chưa mở log")

    def refresh_com_ports(self):
        boxes = (self.com_box_1, self.com_box_2)
        variables = (self.com_port_1, self.com_port_2)
        if list_ports is None:
            for box in boxes:
                box["values"] = ()
            for variable in variables:
                variable.set("")
            self.status.set("Thiếu pyserial – chạy: py -m pip install pyserial")
            return

        current_devices = [
            self._selected_com_device(variable, allow_empty=True)
            for variable in variables
        ]
        all_ports = list(list_ports.comports())
        ports = sorted(
            selectable_fsr_ports(all_ports),
            key=lambda port: self._com_sort_key(port.device),
        )
        display_values = [
            f"{port.device} - {port.description or 'Serial device'}"
            for port in ports
        ]
        for box in boxes:
            box["values"] = display_values

        if not display_values:
            self.status.set("Không quét thấy cổng COM")
            return

        by_device = {item.split(" - ", 1)[0]: item for item in display_values}
        preferred_devices = [port.device for port in ports]

        selected = []
        for current in current_devices:
            if current in by_device and current not in selected:
                selected.append(current)
            else:
                selected.append("")

        for index in range(2):
            if selected[index]:
                continue
            candidate = next(
                (device for device in preferred_devices if device not in selected),
                None,
            )
            if candidate:
                selected[index] = candidate

        for variable, device in zip(variables, selected):
            variable.set(by_device.get(device, device))

        chosen = ", ".join(device for device in selected if device) or "chưa chọn"
        ignored = max(0, len(all_ports) - len(ports))
        ignored_text = f"; bỏ qua {ignored} cổng Bluetooth chiều vào" if ignored else ""
        self.status.set(
            f"Tìm thấy {len(display_values)} cổng FSR chiều ra; tự chọn {chosen}{ignored_text}"
        )

    def _refresh_com_ports_from_event(self, _event=None):
        if not self.running:
            self.refresh_com_ports()

    @staticmethod
    def _com_sort_key(device):
        match = re.fullmatch(r"COM(\d+)", device.strip(), flags=re.IGNORECASE)
        return (0, int(match.group(1))) if match else (1, device.casefold())

    def _selected_com_device(self, variable, allow_empty=False):
        value = variable.get().strip()
        if not value:
            if allow_empty:
                return ""
            raise ValueError("Chưa chọn cổng COM")
        return value.split(" - ", 1)[0].strip()

    def _serial_settings(self):
        if serial is None:
            raise ValueError("Chưa cài pyserial")

        devices = [
            self._selected_com_device(self.com_port_1, allow_empty=True),
            self._selected_com_device(self.com_port_2, allow_empty=True),
        ]
        if not any(devices):
            raise ValueError("Chưa chọn cổng COM cho FSR")
        if devices[0] and devices[0] == devices[1]:
            raise ValueError("FSR 1 và FSR 2 đang chọn cùng một cổng COM")

        available = {
            str(getattr(port, "device", ""))
            for port in selectable_fsr_ports(list_ports.comports())
        }
        missing = [device for device in devices if device and device not in available]
        if missing:
            raise ValueError(
                "Cổng không còn sẵn sàng hoặc là cổng Bluetooth chiều vào: "
                + ", ".join(missing)
                + ". Hãy bấm Quét lại."
            )

        baudrate = int(self.baudrate.get())
        if baudrate <= 0:
            raise ValueError("Baudrate phải lớn hơn 0")

        rows_text = self.matrix_rows.get().strip()
        columns_text = self.matrix_columns.get().strip()
        rows = int(rows_text) if rows_text else None
        columns = int(columns_text) if columns_text else None
        if (rows is None) != (columns is None):
            raise ValueError("Phải nhập cả số hàng và số cột")
        if rows is not None and (rows <= 0 or columns <= 0):
            raise ValueError("Số hàng và số cột phải lớn hơn 0")

        settings = []
        fallback_sides = ("left", "right")
        for channel_id, (device, fallback_side) in enumerate(
            zip(devices, fallback_sides), start=1
        ):
            if device:
                settings.append(
                    (channel_id, device, baudrate, rows, columns, fallback_side)
                )
        return settings

    def _connection_settings(self):
        ip = self.target_ip.get().strip()
        if not ip:
            raise ValueError("IP đích không được rỗng")
        port = int(self.target_port.get())
        if not 1 <= port <= 65535:
            raise ValueError("Port không hợp lệ")
        rate = float(self.rate_hz.get())
        if rate <= 0 or rate > 200:
            raise ValueError("Tần số không hợp lệ")
        return ip, port, rate

    def _packet_settings(self):
        return (
            self.device_id.get().strip() or "fsr-device-01",
            self.side.get(),
            self._selected_unit,
        )

    def _manual_matrix(self):
        try:
            return validate_matrix(json.loads(self.matrix_text.get("1.0", tk.END)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON không hợp lệ: {exc.msg}") from exc

    def preview_manual_matrix(self):
        try:
            side = self.side.get()
            raw_matrix = self._manual_matrix()
            matrix = matrix_for_unit(raw_matrix, self._selected_unit)
            self.last_raw_matrices[side] = [row[:] for row in raw_matrix]
            self.draw_matrix(
                matrix,
                side,
                self._selected_unit,
            )
            self._append_chart_sample(side, matrix, unit=self._selected_unit)
        except ValueError as exc:
            messagebox.showerror("Lỗi", str(exc))

    def send_manual_once(self):
        try:
            raw_matrix = self._manual_matrix()
            matrix = matrix_for_unit(raw_matrix, self._selected_unit)
            ip, port, _ = self._connection_settings()
            packet_settings = self._packet_settings()
            status = self._send_matrix_udp(matrix, ip, port, packet_settings)
            self.status.set(status)
            side = self.side.get()
            self.last_raw_matrices[side] = [row[:] for row in raw_matrix]
            self.draw_matrix(matrix, side, self._selected_unit)
            now = time.monotonic()
            self._append_chart_sample(side, matrix, unit=self._selected_unit)
            self._write_log_sample(
                side,
                raw_matrix,
                raw_matrix,
                matrix,
                self._selected_unit,
                now,
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Lỗi", str(exc))

    def _send_matrix_udp(self, matrix, ip, port, packet_settings):
        matrix = validate_matrix(matrix)
        device_id, side, unit = packet_settings
        with self.send_lock:
            packet = build_packet(device_id, side, unit, self.sequence, matrix)
            encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
            if len(encoded) > 60000:
                raise ValueError("Gói tin quá lớn")
            self.socket.sendto(encoded, (ip, port))
            self.sequence += 1
        return f"{side.upper()} frame #{packet['sequence']} -> {ip}:{port}"

    def toggle_stream(self):
        if self.running:
            self._stop_stream("Đã ngắt 2 FSR")
            return

        try:
            serial_settings_list = self._serial_settings()
            ip, port, rate = self._connection_settings()
            packet_settings = self._packet_settings()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Lỗi", str(exc))
            return

        self.stop_playback(silent=True)
        self.clear_charts()
        self.running = True
        self.smoothed_matrices.clear()
        self.last_raw_matrices.clear()
        self.detected_sides.clear()
        self.connected_channels.clear()
        self.frame_counts = {1: 0, 2: 0}
        self.active_channels = {settings[0] for settings in serial_settings_list}
        self.workers = []
        self.module_code.set("Đang chờ LL/RR...")
        self.bt_button_text.set("Đang kết nối...")

        devices = ", ".join(settings[1] for settings in serial_settings_list)
        self.status.set(f"Đang kết nối {devices}...")
        for channel_id, device, baudrate, rows, columns, fallback_side in serial_settings_list:
            self._channel_status_var(channel_id).set(f"Đang mở {device}...")
            worker = threading.Thread(
                target=self._hardware_loop,
                args=(
                    channel_id,
                    (device, baudrate, rows, columns, fallback_side),
                    (ip, port, rate),
                    packet_settings,
                ),
                daemon=True,
                name=f"fsr-serial-{channel_id}",
            )
            self.workers.append(worker)
            worker.start()

    def _channel_status_var(self, channel_id):
        return self.channel_status_1 if channel_id == 1 else self.channel_status_2

    def _stop_stream(self, status_text=None):
        self.running = False
        self.smoothed_matrices.clear()
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.active_channels.clear()
        self.connected_channels.clear()
        self.workers = []
        self.bt_button_text.set("Kết nối 2 FSR")
        self.module_code.set("--")
        self.channel_status_1.set("Đã ngắt")
        self.channel_status_2.set("Đã ngắt")
        self._set_connection_panel_collapsed(False)
        if self.log_handle is not None:
            self._stop_logging()
        if status_text:
            self.status.set(status_text)

    def _hardware_loop(self, channel_id, serial_settings, udp_settings, packet_settings):
        device, baudrate, rows, columns, fallback_side = serial_settings
        ip, port, rate = udp_settings
        min_period = 1.0 / rate
        last_send_time = 0.0
        last_ui_time = 0.0
        buffer_tokens = []
        detected_side = None
        ser = None

        try:
            ser = serial.Serial()
            ser.port = device
            ser.baudrate = baudrate
            ser.bytesize = serial.EIGHTBITS
            ser.parity = serial.PARITY_NONE
            ser.stopbits = serial.STOPBITS_ONE
            ser.timeout = DEFAULT_SERIAL_TIMEOUT
            ser.rtscts = False
            ser.dsrdtr = False
            for open_attempt in range(3):
                try:
                    ser.open()
                    break
                except (serial.SerialException, OSError):
                    if open_attempt == 2 or not self.running:
                        raise
                    time.sleep(1.0)
            # Bluetooth SPP does not need modem-control toggles. Some Windows
            # drivers disconnect briefly when DTR/RTS is forced, which looked
            # like the COM number was jumping between reconnect attempts.
            time.sleep(0.3)

            with self.serial_lock:
                self.serial_connections[channel_id] = ser
            ser.reset_input_buffer()
            self.root.after(0, self._on_connected, channel_id, device)

            while self.running:
                if ser.in_waiting > 2048:
                    ser.reset_input_buffer()
                    buffer_tokens.clear()
                    continue

                raw_line = ser.readline()
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                tokens = line.split()
                if not tokens:
                    continue

                if tokens[0].upper() in ("RR", "LL"):
                    raw_module = tokens[0].upper()

                    detected_side = "left" if raw_module == "RR" else "right"
                    buffer_tokens = tokens[1:]

                    actual_leg = 'Left' if raw_module == 'RR' else 'Right'
                    display_text = f"{raw_module} ({actual_leg})"

                    self.root.after(0, self.module_code.set, display_text)
                else:
                    buffer_tokens.extend(tokens)

                target_count = (rows * columns) if (rows and columns) else 48
                if len(buffer_tokens) > target_count * 8:
                    buffer_tokens = buffer_tokens[-target_count * 2:]
                if len(buffer_tokens) < target_count:
                    continue

                frame_tokens = buffer_tokens[:target_count]
                buffer_tokens = buffer_tokens[target_count:]
                try:
                    values = [float(value) for value in frame_tokens]
                    active_side = detected_side or fallback_side
                    matrix, frame_side = parse_hardware_frame(
                        values, active_side, rows, columns
                    )
                    incoming_raw_matrix = [row[:] for row in matrix]
                    raw_matrix = self._apply_ema_filter(channel_id, matrix)
                    selected_unit = self._selected_unit
                    matrix = matrix_for_unit(raw_matrix, selected_unit)
                    self.last_raw_matrices[frame_side] = [row[:] for row in raw_matrix]
                    current_packet_settings = (
                        packet_settings[0], frame_side, selected_unit
                    )
                except (ValueError, TypeError) as exc:
                    self.root.after(
                        0,
                        self._channel_status_var(channel_id).set,
                        f"Lỗi frame: {exc}",
                    )
                    continue

                now = time.monotonic()
                self.frame_counts[channel_id] += 1
                self._write_log_sample(
                    frame_side,
                    incoming_raw_matrix,
                    raw_matrix,
                    matrix,
                    selected_unit,
                    now,
                )

                if now - last_send_time >= min_period:
                    status = self._send_matrix_udp(
                        matrix, ip, port, current_packet_settings
                    )
                    last_send_time = now

                if now - last_ui_time >= 0.04:
                    self.root.after(
                        0,
                        self._update_after_frame,
                        channel_id,
                        frame_side,
                        matrix,
                        selected_unit,
                        status,
                    )
                    last_ui_time = now

        except (serial.SerialException, OSError, ValueError) as exc:
            if self.running:
                self.root.after(
                    0, self._stream_failed, channel_id, device, str(exc)
                )
        finally:
            with self.serial_lock:
                current = self.serial_connections.get(channel_id)
                if current is ser:
                    self.serial_connections.pop(channel_id, None)
            if ser is not None:
                try:
                    ser.close()
                except (serial.SerialException, OSError):
                    pass
            self.root.after(0, self._channel_finished, channel_id)

    def _on_connected(self, channel_id, device):
        self.connected_channels.add(channel_id)
        self._channel_status_var(channel_id).set(f"{device}: chờ LL/RR")
        self.bt_button_text.set("Ngắt 2 FSR")
        self.status.set(f"Đã mở {device}; đang chờ dữ liệu")
        if self.active_channels and self.active_channels.issubset(self.connected_channels):
            self._set_connection_panel_collapsed(True)
            if self.main_notebook is not None and self.total_chart_tab is not None:
                self.main_notebook.select(self.total_chart_tab)

    def _on_module_detected(self, channel_id, raw_module, device):
        side = "right" if raw_module == "RR" else "left"
        self.detected_sides[channel_id] = side
        side_label = "Chân phải" if side == "right" else "Chân trái"
        self._channel_status_var(channel_id).set(f"{device}: {raw_module} - {side_label}")

        labels = []
        for current_channel in sorted(self.detected_sides):
            current_side = self.detected_sides[current_channel]
            code = "RR" if current_side == "right" else "LL"
            labels.append(f"FSR {current_channel}: {code}")
        duplicate = len(self.detected_sides) > 1 and len(set(self.detected_sides.values())) < len(
            self.detected_sides
        )
        self.module_code.set(" | ".join(labels) + (" (TRÙNG CHÂN)" if duplicate else ""))
        if duplicate:
            self.status.set("Cảnh báo: cả hai cổng đang gửi cùng LL hoặc cùng RR")

    def _update_after_frame(self, channel_id, frame_side, matrix, unit, status):
        if not self.running:
            return
        side_code = "LL" if frame_side == "left" else "RR"
        count = self.frame_counts[channel_id]
        self._channel_status_var(channel_id).set(f"{side_code}: đã nhận {count} frame")
        self.status.set(status)
        self.draw_matrix(matrix, frame_side, unit)
        self._append_chart_sample(frame_side, matrix, unit=unit)

    def _stream_failed(self, channel_id, device, error_message):
        self.connected_channels.discard(channel_id)
        self._set_connection_panel_collapsed(False)
        self._channel_status_var(channel_id).set(f"{device}: l\u1ed7i m\u1edf c\u1ed5ng")
        self.status.set(f"L\u1ed7i {device}: {error_message}")
        messagebox.showwarning(
            f"FSR {channel_id} kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c",
            f"Kh\u00f4ng m\u1edf \u0111\u01b0\u1ee3c {device}. C\u1ed5ng FSR c\u00f2n l\u1ea1i v\u1eabn ti\u1ebfp t\u1ee5c "
            f"n\u1ebfu k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c.\n\nChi ti\u1ebft: {error_message}\n\n"
            "H\u00e3y \u0111\u00f3ng Tera Term/Serial Monitor ho\u1eb7c \u1ee9ng d\u1ee5ng kh\u00e1c \u0111ang gi\u1eef c\u1ed5ng.",
        )

    def _channel_finished(self, channel_id):
        self.active_channels.discard(channel_id)
        self.connected_channels.discard(channel_id)
        if self.running and not self.active_channels:
            self.running = False
            self.bt_button_text.set("Kết nối 2 FSR")
            self.status.set("Không còn cổng FSR nào đang chạy")
            self._set_connection_panel_collapsed(False)
            if self.log_handle is not None:
                self._stop_logging()

    def draw_matrix(self, matrix, side=None, unit=None):
        matrix = validate_matrix(matrix)
        unit = unit or self._selected_unit
        min_force, max_force = color_range_for_unit(unit)
        side = side if side in ("left", "right") else self.side.get()
        canvas = self.canvas_left if side == "left" else self.canvas_right
        summary = self.summary_left if side == "left" else self.summary_right
        state = self.preview_state[side]

        rows = len(matrix)
        columns = len(matrix[0])
        width = max(canvas.winfo_width(), 210)
        height = max(canvas.winfo_height(), 300)

        if (
            state["shape"] != (rows, columns)
            or state["size"] != (width, height)
            or len(state["rects"]) != rows * columns
        ):
            canvas.delete("all")
            state["rects"] = []
            state["texts"] = []
            state["shape"] = (rows, columns)
            state["size"] = (width, height)

            cell_width = width / columns
            cell_height = height / rows
            for y in range(rows):
                for x in range(columns):
                    x0, y0 = x * cell_width, y * cell_height
                    x1, y1 = x0 + cell_width, y0 + cell_height
                    state["rects"].append(
                        canvas.create_rectangle(
                            x0, y0, x1, y1, fill="#111827", outline="#374151"
                        )
                    )
                    state["texts"].append(
                        canvas.create_text(
                            (x0 + x1) / 2,
                            (y0 + y1) / 2,
                            text="",
                            fill="#d1d5db",
                            font=("Consolas", 8),
                        )
                    )

        cell_width = width / columns
        cell_height = height / rows
        index = 0
        for row in matrix:
            for value in row:
                canvas.itemconfig(
                    state['rects'][index],
                    fill=get_force_color(value, min_force, max_force),
                )
                if cell_width >= 20 and cell_height >= 14:
                    text_color = (
                        "#111827"
                        if value >= (min_force + max_force) / 3
                        else "#ffffff"
                    )
                    value_text = f'{value:.2f}' if unit == 'newton' else f'{value:g}'
                    canvas.itemconfig(
                        state['texts'][index], text=value_text, fill=text_color
                    )
                else:
                    canvas.itemconfig(state["texts"][index], text="")
                index += 1

        total, cop_x, cop_y = matrix_summary(matrix)
        cop_text = "--" if cop_x is None else f"({cop_x:.2f}, {cop_y:.2f})"
        side_code = "LL" if side == "left" else "RR"
        summary.set(
            f'{side_code} | {rows}×{columns} | Tổng: {total:.2f} '
            f'{unit_label(unit)}\nCoP: {cop_text}'
        )

    def close(self):
        self.running = False
        self.stop_playback(silent=True)
        self._stop_logging("Đã đóng log")
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.socket.close()
        self.root.destroy()



if __name__ == "__main__":
    window = tk.Tk()
    app = FSRTransmitterApp(window)
    window.mainloop()
