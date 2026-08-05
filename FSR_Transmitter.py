"""
Requires: pip install pyserial
"""

import json
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # App can still open and show installation guidance.
    serial = None
    list_ports = None


DEFAULT_TARGET_IP = "127.0.0.1"
DEFAULT_TARGET_PORT = 8765
DEFAULT_SEND_RATE_HZ = 20
DEFAULT_BAUDRATE = 9600
DEFAULT_SERIAL_TIMEOUT = 0.2


def validate_matrix(matrix):
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("Ma trận phải là một danh sách 2 chiều không rỗng")
    if not isinstance(matrix[0], list) or not matrix[0]:
        raise ValueError("Ma trận phải có ít nhất một cột")

    columns = len(matrix[0])
    normalized = []
    for row in matrix:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError("Tất cả các hàng phải có cùng số cột")
        normalized_row = []
        for value in row:
            if not isinstance(value, (int, float)):
                raise ValueError("Mỗi điểm FSR phải là số")
            if value < 0:
                raise ValueError("Giá trị FSR không được âm")
            normalized_row.append(float(value))
        normalized.append(normalized_row)
    return normalized


def parse_hardware_frame(text, expected_rows=None, expected_columns=None):
    """Convert one newline-terminated Bluetooth frame into a matrix."""
    text = text.strip()
    if not text:
        return None

    # Preferred format: JSON matrix, e.g. [[10,20],[30,40]].
    if text.startswith("["):
        try:
            return validate_matrix(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON từ Bluetooth không hợp lệ: {exc.msg}") from exc

    # Compact format: rows separated by ';', values by ',' or whitespace.
    if ";" in text:
        rows = []
        for raw_row in text.split(";"):
            raw_row = raw_row.strip()
            if not raw_row:
                continue
            values = raw_row.replace(",", " ").split()
            rows.append([float(value) for value in values])
        return validate_matrix(rows)

    # Flat frame: dimensions are supplied by the UI.
    values = [float(value) for value in text.replace(",", " ").split()]
    if expected_rows and expected_columns:
        required = expected_rows * expected_columns
        if len(values) != required:
            raise ValueError(
                f"Frame có {len(values)} giá trị, nhưng cần {required} "
                f"cho ma trận {expected_rows}×{expected_columns}"
            )
        matrix = [
            values[row * expected_columns : (row + 1) * expected_columns]
            for row in range(expected_rows)
        ]
        return validate_matrix(matrix)

    raise ValueError(
        "Frame phẳng cần khai báo số hàng và số cột, "
        "hoặc gửi dạng JSON / dùng dấu ';' để ngăn hàng"
    )


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
        self.root.title("FSR Matrix Transmitter - Bluetooth 9600")
        self.root.geometry("980x720")
        self.root.minsize(820, 620)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.serial_connection = None
        self.sequence = 0
        self.running = False
        self.worker = None
        self.hardware_queue = queue.Queue(maxsize=2)

        self.target_ip = tk.StringVar(value=DEFAULT_TARGET_IP)
        self.target_port = tk.StringVar(value=str(DEFAULT_TARGET_PORT))
        self.device_id = tk.StringVar(value="fsr-device-01")
        self.side = tk.StringVar(value="left")
        self.unit = tk.StringVar(value="raw_adc")
        self.rate_hz = tk.StringVar(value=str(DEFAULT_SEND_RATE_HZ))

        self.com_port = tk.StringVar()
        self.baudrate = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        self.matrix_rows = tk.StringVar(value="")
        self.matrix_columns = tk.StringVar(value="")

        self.status = tk.StringVar(value="Sẵn sàng - chưa kết nối Bluetooth")
        self.summary = tk.StringVar(value="Kích thước: -- | Tổng: -- | CoP: --")

        self._build_ui()
        self.refresh_com_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        bluetooth = ttk.LabelFrame(container, text="Bluetooth Serial", padding=10)
        bluetooth.pack(fill=tk.X)

        ttk.Label(bluetooth, text="Cổng COM").grid(row=0, column=0, padx=(0, 5), sticky="w")
        self.com_box = ttk.Combobox(bluetooth, textvariable=self.com_port, width=30, state="readonly")
        self.com_box.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        ttk.Button(bluetooth, text="Quét lại", command=self.refresh_com_ports).grid(
            row=0, column=2, padx=(0, 18)
        )

        ttk.Label(bluetooth, text="Baudrate").grid(row=0, column=3, padx=(0, 5), sticky="w")
        ttk.Combobox(
            bluetooth,
            textvariable=self.baudrate,
            values=("9600", "19200", "38400", "57600", "115200"),
            width=10,
            state="readonly",
        ).grid(row=0, column=4, padx=(0, 18), sticky="w")

        ttk.Label(bluetooth, text="Hàng").grid(row=1, column=0, pady=(10, 0), sticky="w")
        ttk.Entry(bluetooth, textvariable=self.matrix_rows, width=8).grid(
            row=1, column=1, pady=(10, 0), sticky="w"
        )
        ttk.Label(bluetooth, text="Cột").grid(row=1, column=2, pady=(10, 0), sticky="e")
        ttk.Entry(bluetooth, textvariable=self.matrix_columns, width=8).grid(
            row=1, column=3, pady=(10, 0), sticky="w"
        )
        ttk.Label(
            bluetooth,
            text="Chỉ cần nhập Hàng/Cột khi thiết bị gửi một dãy số phẳng.",
            foreground="#555555",
        ).grid(row=1, column=4, pady=(10, 0), sticky="w")
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

        ttk.Label(connection, text="Chân").grid(row=1, column=0, pady=(10, 0), sticky="w")
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
        editor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.matrix_text = tk.Text(editor_frame, width=38, wrap=tk.NONE, font=("Consolas", 11))
        self.matrix_text.pack(fill=tk.BOTH, expand=True)
        self.matrix_text.insert("1.0", "[[0, 0], [0, 0]]")

        preview_frame = ttk.LabelFrame(body, text="Xem trước lực từng điểm", padding=10)
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        self.canvas = tk.Canvas(preview_frame, background="#111827", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        ttk.Label(preview_frame, textvariable=self.summary).pack(fill=tk.X, pady=(8, 0))

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Xem ma trận", command=self.preview_manual_matrix).pack(side=tk.LEFT)
        ttk.Button(controls, text="Gửi 1 frame", command=self.send_manual_once).pack(side=tk.LEFT, padx=8)
        self.stream_button = ttk.Button(
            controls, text="Kết nối và đọc Bluetooth", command=self.toggle_stream
        )
        self.stream_button.pack(side=tk.LEFT)
        ttk.Label(controls, textvariable=self.status).pack(side=tk.RIGHT)

        note = (
            "Thiết bị phải gửi mỗi frame trên một dòng và kết thúc bằng ký tự xuống dòng (\\n). "
            "Ví dụ: [[10,20],[30,40]] hoặc 10,20;30,40"
        )
        ttk.Label(container, text=note, foreground="#555555").pack(fill=tk.X, pady=(10, 0))

    def refresh_com_ports(self):
        if list_ports is None:
            self.com_box["values"] = ()
            self.com_port.set("")
            self.status.set("Thiếu pyserial - chạy: pip install pyserial")
            return

        ports = list(list_ports.comports())
        display_values = [f"{port.device} - {port.description}" for port in ports]
        self.com_box["values"] = display_values
        if display_values:
            current_device = self._selected_com_device(allow_empty=True)
            matching = next(
                (item for item in display_values if item.split(" - ", 1)[0] == current_device),
                None,
            )
            self.com_port.set(matching or display_values[0])
            self.status.set(f"Tìm thấy {len(display_values)} cổng COM")
        else:
            self.com_port.set("")
            self.status.set("Không tìm thấy cổng COM Bluetooth")

    def _selected_com_device(self, allow_empty=False):
        value = self.com_port.get().strip()
        if not value:
            if allow_empty:
                return ""
            raise ValueError("Chưa chọn cổng COM Bluetooth")
        return value.split(" - ", 1)[0].strip()

    def _serial_settings(self):
        if serial is None:
            raise ValueError("Chưa cài pyserial. Hãy chạy: pip install pyserial")
        device = self._selected_com_device()
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
        return device, baudrate, rows, columns

    def _connection_settings(self):
        ip = self.target_ip.get().strip()
        if not ip:
            raise ValueError("IP đích không được rỗng")
        port = int(self.target_port.get())
        if not 1 <= port <= 65535:
            raise ValueError("Port phải nằm trong khoảng 1-65535")
        rate = float(self.rate_hz.get())
        if rate <= 0 or rate > 200:
            raise ValueError("Tần số gửi phải lớn hơn 0 và không quá 200 Hz")
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
            self.draw_matrix(self._manual_matrix())
        except ValueError as exc:
            messagebox.showerror("Ma trận không hợp lệ", str(exc))

    def send_manual_once(self):
        try:
            matrix = self._manual_matrix()
            ip, port, _ = self._connection_settings()
            packet_settings = self._packet_settings()
            status = self._send_matrix_udp(matrix, ip, port, packet_settings)
            self.status.set(status)
            self.draw_matrix(matrix)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Không gửi được", str(exc))

    def _send_matrix_udp(self, matrix, ip, port, packet_settings):
        matrix = validate_matrix(matrix)
        device_id, side, unit = packet_settings
        packet = build_packet(device_id, side, unit, self.sequence, matrix)
        encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 60000:
            raise ValueError("Frame quá lớn cho một gói UDP")
        self.socket.sendto(encoded, (ip, port))
        self.sequence += 1
        return f"Đã gửi frame #{packet['sequence']} - {len(encoded)} bytes tới {ip}:{port}"

    def submit_hardware_matrix(self, matrix):
        """Thread-safe entry point retained for external acquisition code."""
        matrix = validate_matrix(matrix)
        while self.hardware_queue.full():
            try:
                self.hardware_queue.get_nowait()
            except queue.Empty:
                break
        self.hardware_queue.put_nowait(matrix)

    def toggle_stream(self):
        if self.running:
            self._stop_stream("Đã ngắt Bluetooth")
            return

        try:
            serial_settings = self._serial_settings()
            ip, port, rate = self._connection_settings()
            packet_settings = self._packet_settings()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cấu hình không hợp lệ", str(exc))
            return

        self.running = True
        self.stream_button.configure(text="Ngắt Bluetooth")
        self.status.set(f"Đang mở {serial_settings[0]} ở {serial_settings[1]} baud...")
        self.worker = threading.Thread(
            target=self._hardware_loop,
            args=(serial_settings, (ip, port, rate), packet_settings),
            daemon=True,
        )
        self.worker.start()

    def _stop_stream(self, status_text=None):
        self.running = False
        connection = self.serial_connection
        self.serial_connection = None
        if connection is not None:
            try:
                connection.close()
            except (OSError, serial.SerialException if serial else OSError):
                pass
        self.stream_button.configure(text="Kết nối và đọc Bluetooth")
        if status_text:
            self.status.set(status_text)

    def _hardware_loop(self, serial_settings, udp_settings, packet_settings):
        device, baudrate, rows, columns = serial_settings
        ip, port, rate = udp_settings
        min_period = 1.0 / rate
        last_send_time = 0.0

        try:
            self.serial_connection = serial.Serial(
                port=device,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=DEFAULT_SERIAL_TIMEOUT,
            )
            self.serial_connection.reset_input_buffer()
            self.root.after(0, self.status.set, f"Đã kết nối {device} - {baudrate} baud")

            while self.running:
                raw_line = self.serial_connection.readline()
                if not raw_line:
                    continue

                try:
                    line = raw_line.decode("utf-8").strip()
                except UnicodeDecodeError:
                    self.root.after(0, self.status.set, "Bỏ qua frame không phải UTF-8")
                    continue

                if not line:
                    continue

                try:
                    matrix = parse_hardware_frame(line, rows, columns)
                except (ValueError, TypeError) as exc:
                    self.root.after(0, self.status.set, f"Frame Bluetooth lỗi: {exc}")
                    continue

                now = time.monotonic()
                remaining = min_period - (now - last_send_time)
                if remaining > 0:
                    time.sleep(remaining)

                status = self._send_matrix_udp(matrix, ip, port, packet_settings)
                last_send_time = time.monotonic()
                self.root.after(0, self._update_after_frame, matrix, status)

        except (serial.SerialException, OSError, ValueError) as exc:
            if self.running:
                self.root.after(0, self._stream_failed, str(exc))
        finally:
            connection = self.serial_connection
            self.serial_connection = None
            if connection is not None:
                try:
                    connection.close()
                except (serial.SerialException, OSError):
                    pass

    def _update_after_frame(self, matrix, status):
        if not self.running:
            return
        self.status.set(status)
        self.draw_matrix(matrix)

    def _stream_failed(self, error_message):
        self.running = False
        self.stream_button.configure(text="Kết nối và đọc Bluetooth")
        self.status.set(f"Lỗi Bluetooth: {error_message}")
        messagebox.showerror("Mất kết nối Bluetooth", error_message)

    def draw_matrix(self, matrix):
        matrix = validate_matrix(matrix)
        self.canvas.delete("all")
        self.canvas.update_idletasks()
        width = max(self.canvas.winfo_width(), 300)
        height = max(self.canvas.winfo_height(), 300)
        rows = len(matrix)
        columns = len(matrix[0])
        cell_width = width / columns
        cell_height = height / rows
        maximum = max(max(row) for row in matrix) or 1.0

        for y, row in enumerate(matrix):
            for x, value in enumerate(row):
                ratio = min(value / maximum, 1.0)
                red = int(255 * ratio)
                green = int(210 * (1.0 - abs(ratio - 0.5) * 2.0))
                blue = int(80 * (1.0 - ratio))
                color = f"#{red:02x}{green:02x}{blue:02x}"
                x0, y0 = x * cell_width, y * cell_height
                x1, y1 = x0 + cell_width, y0 + cell_height
                self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="#374151")
                if cell_width >= 32 and cell_height >= 24:
                    self.canvas.create_text(
                        (x0 + x1) / 2,
                        (y0 + y1) / 2,
                        text=f"{value:g}",
                        fill="white" if ratio > 0.45 else "#d1d5db",
                        font=("Consolas", 9),
                    )

        total, cop_x, cop_y = matrix_summary(matrix)
        cop_text = "--" if cop_x is None else f"({cop_x:.2f}, {cop_y:.2f})"
        self.summary.set(f"Kích thước: {rows}×{columns} | Tổng: {total:.2f} | CoP: {cop_text}")

    def close(self):
        self.running = False
        connection = self.serial_connection
        self.serial_connection = None
        if connection is not None:
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
