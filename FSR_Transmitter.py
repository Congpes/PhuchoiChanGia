import json
import queue
import re
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

DEFAULT_TARGET_IP = "127.0.0.1"
DEFAULT_TARGET_PORT = 8765
DEFAULT_SEND_RATE_HZ = 20
DEFAULT_BAUDRATE = 9600
DEFAULT_SERIAL_TIMEOUT = 0.5
MIN_FORCE = 30.0
MAX_FORCE = 5500.0

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
    DEADZONE = 30.0
    if value < DEADZONE or value < min_val:
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
        self.root.geometry("1180x720")
        self.root.minsize(980, 620)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.serial_connections = {}
        self.serial_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.sequence = 0
        self.running = False
        self.workers = []
        self.active_channels = set()
        self.detected_sides = {}
        self.frame_counts = {1: 0, 2: 0}

        self.preview_state = {
            "left": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
            "right": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
        }

        self.target_ip = tk.StringVar(value=DEFAULT_TARGET_IP)
        self.target_port = tk.StringVar(value=str(DEFAULT_TARGET_PORT))
        self.device_id = tk.StringVar(value="fsr-device-01")
        self.side = tk.StringVar(value="right")
        self.unit = tk.StringVar(value="raw_adc")
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

        self._build_ui()
        self.refresh_com_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        bluetooth = ttk.LabelFrame(container, text="Bluetooth Serial - nhận đồng thời 2 chân", padding=10)
        bluetooth.pack(fill=tk.X)

        ttk.Label(bluetooth, text="FSR 1 (tự nhận LL/RR)").grid(
            row=0, column=0, padx=(0, 5), sticky="w"
        )
        self.com_box_1 = ttk.Combobox(
            bluetooth, textvariable=self.com_port_1, width=35, state="normal"
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
            bluetooth, textvariable=self.com_port_2, width=35, state="normal"
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

        connection = ttk.LabelFrame(container, text="Đích nhận UDP", padding=10)
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

        body = ttk.Frame(container)
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

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Xem ma trận", command=self.preview_manual_matrix).pack(side=tk.LEFT)
        ttk.Button(controls, text="Gửi 1 frame", command=self.send_manual_once).pack(side=tk.LEFT, padx=8)
        ttk.Label(controls, textvariable=self.status).pack(side=tk.RIGHT)
        empty_matrix = [[0.0] * 4 for _ in range(12)]
        self.root.after(80, self.draw_matrix, empty_matrix, "left")
        self.root.after(80, self.draw_matrix, empty_matrix, "right")

    def refresh_com_ports(self):
        boxes = (self.com_box_1, self.com_box_2)
        variables = (self.com_port_1, self.com_port_2)
        if list_ports is None:
            for box in boxes:
                box["values"] = ()
            for variable in variables:
                variable.set("")
            self.status.set("Thiếu pyserial")
            return

        current_devices = [
            self._selected_com_device(variable, allow_empty=True)
            for variable in variables
        ]
        ports = sorted(
            list(list_ports.comports()),
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
        # Windows tạo cả cổng Bluetooth chiều vào và chiều ra. Cổng LOCALMFG&0002
        # là cổng đi ra tới module, nên ưu tiên chúng khi tự chọn.
        outgoing_devices = [
            port.device
            for port in ports
            if "LOCALMFG&0002" in (getattr(port, "hwid", "") or "").upper()
        ]
        preferred_devices = outgoing_devices if outgoing_devices else [port.device for port in ports]

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
        self.status.set(f"Tìm thấy {len(display_values)} cổng; tự chọn {chosen}")

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
            self.unit.get(),
        )

    def _manual_matrix(self):
        try:
            return validate_matrix(json.loads(self.matrix_text.get("1.0", tk.END)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON không hợp lệ: {exc.msg}") from exc

    def preview_manual_matrix(self):
        try:
            self.draw_matrix(self._manual_matrix(), self.side.get())
        except ValueError as exc:
            messagebox.showerror("Lỗi", str(exc))

    def send_manual_once(self):
        try:
            matrix = self._manual_matrix()
            ip, port, _ = self._connection_settings()
            packet_settings = self._packet_settings()
            status = self._send_matrix_udp(matrix, ip, port, packet_settings)
            self.status.set(status)
            self.draw_matrix(matrix, self.side.get())
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

        self.running = True
        self.detected_sides.clear()
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
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.active_channels.clear()
        self.workers = []
        self.bt_button_text.set("Kết nối 2 FSR")
        self.module_code.set("--")
        self.channel_status_1.set("Đã ngắt")
        self.channel_status_2.set("Đã ngắt")
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
            ser.dtr = True
            ser.rts = True
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
                    detected_side = "right" if raw_module == "RR" else "left"
                    buffer_tokens = tokens[1:]
                    self.root.after(
                        0, self._on_module_detected, channel_id, raw_module, device
                    )
                else:
                    buffer_tokens.extend(tokens)

                target_count = (rows * columns) if (rows and columns) else 48
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
                    current_packet_settings = (
                        packet_settings[0], frame_side, packet_settings[2]
                    )
                except (ValueError, TypeError) as exc:
                    self.root.after(
                        0,
                        self._channel_status_var(channel_id).set,
                        f"Lỗi frame: {exc}",
                    )
                    continue

                now = time.monotonic()
                remaining = min_period - (now - last_send_time)
                if remaining > 0:
                    time.sleep(remaining)

                status = self._send_matrix_udp(
                    matrix, ip, port, current_packet_settings
                )
                last_send_time = time.monotonic()
                self.frame_counts[channel_id] += 1

                if now - last_ui_time >= 0.04:
                    self.root.after(
                        0,
                        self._update_after_frame,
                        channel_id,
                        frame_side,
                        matrix,
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
        self._channel_status_var(channel_id).set(f"{device}: chờ LL/RR")
        self.bt_button_text.set("Ngắt 2 FSR")
        self.status.set(f"Đã mở {device}; đang chờ dữ liệu")

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

    def _update_after_frame(self, channel_id, frame_side, matrix, status):
        if not self.running:
            return
        side_code = "LL" if frame_side == "left" else "RR"
        count = self.frame_counts[channel_id]
        self._channel_status_var(channel_id).set(f"{side_code}: đã nhận {count} frame")
        self.status.set(status)
        self.draw_matrix(matrix, frame_side)

    def _stream_failed(self, channel_id, device, error_message):
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
        if self.running and not self.active_channels:
            self.running = False
            self.bt_button_text.set("Kết nối 2 FSR")
            self.status.set("Không còn cổng FSR nào đang chạy")

    def draw_matrix(self, matrix, side=None):
        matrix = validate_matrix(matrix)
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
                canvas.itemconfig(state["rects"][index], fill=get_force_color(value))
                if cell_width >= 20 and cell_height >= 14:
                    text_color = (
                        "#111827"
                        if value >= (MIN_FORCE + MAX_FORCE) / 3
                        else "#ffffff"
                    )
                    canvas.itemconfig(
                        state["texts"][index], text=f"{value:g}", fill=text_color
                    )
                else:
                    canvas.itemconfig(state["texts"][index], text="")
                index += 1

        total, cop_x, cop_y = matrix_summary(matrix)
        cop_text = "--" if cop_x is None else f"({cop_x:.2f}, {cop_y:.2f})"
        side_code = "LL" if side == "left" else "RR"
        summary.set(
            f"{side_code} | {rows}×{columns} | Tổng: {total:.0f}\nCoP: {cop_text}"
        )

    def close(self):
        self.running = False
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
