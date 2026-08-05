"""Standalone FSR matrix transmitter.

Give this single file to the hardware engineer. It has no third-party
dependencies. Replace ``read_matrix_from_hardware`` with the Serial/BLE reader,
or call ``app.submit_hardware_matrix(matrix)`` from existing acquisition code.

Each frame is sent as one UTF-8 JSON UDP datagram.
"""

import json
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk


DEFAULT_TARGET_IP = "127.0.0.1"
DEFAULT_TARGET_PORT = 8765
DEFAULT_SEND_RATE_HZ = 20


def read_matrix_from_hardware():
    """Hardware hook: return a 2-D list, or None when no new frame is ready.

    The hardware engineer should replace this function with the Serial/BLE
    acquisition code. Example return value: [[0, 125], [42, 310]].
    """
    return None


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
        self.root.geometry("920x650")
        self.root.minsize(760, 540)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
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
        self.status = tk.StringVar(value="Sẵn sàng - chưa gửi dữ liệu")
        self.summary = tk.StringVar(value="Kích thước: -- | Tổng: -- | CoP: --")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        connection = ttk.LabelFrame(container, text="Đích nhận UDP", padding=10)
        connection.pack(fill=tk.X)
        fields = [
            ("IP", self.target_ip, 18),
            ("Port", self.target_port, 8),
            ("Device ID", self.device_id, 18),
            ("Tần số (Hz)", self.rate_hz, 8),
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

        editor_frame = ttk.LabelFrame(body, text="Ma trận FSR dạng JSON", padding=10)
        editor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.matrix_text = tk.Text(editor_frame, width=38, wrap=tk.NONE, font=("Consolas", 11))
        self.matrix_text.pack(fill=tk.BOTH, expand=True)
        self.matrix_text.insert("1.0", "[]")

        preview_frame = ttk.LabelFrame(body, text="Xem trước lực từng điểm", padding=10)
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        self.canvas = tk.Canvas(preview_frame, background="#111827", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        ttk.Label(preview_frame, textvariable=self.summary).pack(fill=tk.X, pady=(8, 0))

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Xem ma trận", command=self.preview_manual_matrix).pack(side=tk.LEFT)
        ttk.Button(controls, text="Gửi 1 frame", command=self.send_manual_once).pack(side=tk.LEFT, padx=8)
        self.stream_button = ttk.Button(controls, text="Bắt đầu đọc phần cứng", command=self.toggle_stream)
        self.stream_button.pack(side=tk.LEFT)
        ttk.Label(controls, textvariable=self.status).pack(side=tk.RIGHT)

        note = (
            "Điểm ghép phần cứng: sửa hàm read_matrix_from_hardware() ở đầu file, "
            "hoặc gọi app.submit_hardware_matrix(matrix)."
        )
        ttk.Label(container, text=note, foreground="#555555").pack(fill=tk.X, pady=(10, 0))

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
            self.send_matrix(matrix)
            self.draw_matrix(matrix)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Không gửi được", str(exc))

    def send_matrix(self, matrix):
        matrix = validate_matrix(matrix)
        ip, port, _ = self._connection_settings()
        packet = build_packet(
            self.device_id.get().strip() or "fsr-device-01",
            self.side.get(),
            self.unit.get(),
            self.sequence,
            matrix,
        )
        encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 60000:
            raise ValueError("Frame quá lớn cho một gói UDP")
        self.socket.sendto(encoded, (ip, port))
        self.sequence += 1
        self.status.set(f"Đã gửi frame #{packet['sequence']} - {len(encoded)} bytes tới {ip}:{port}")

    def submit_hardware_matrix(self, matrix):
        """Thread-safe entry point for an external Serial/BLE reader."""
        matrix = validate_matrix(matrix)
        while self.hardware_queue.full():
            try:
                self.hardware_queue.get_nowait()
            except queue.Empty:
                break
        self.hardware_queue.put_nowait(matrix)

    def toggle_stream(self):
        if self.running:
            self.running = False
            self.stream_button.configure(text="Bắt đầu đọc phần cứng")
            self.status.set("Đã dừng đọc phần cứng")
            return
        try:
            self._connection_settings()
        except ValueError as exc:
            messagebox.showerror("Cấu hình không hợp lệ", str(exc))
            return
        self.running = True
        self.stream_button.configure(text="Dừng đọc phần cứng")
        self.worker = threading.Thread(target=self._hardware_loop, daemon=True)
        self.worker.start()

    def _hardware_loop(self):
        while self.running:
            try:
                _, _, rate = self._connection_settings()
                matrix = read_matrix_from_hardware()
                if matrix is None:
                    try:
                        matrix = self.hardware_queue.get(timeout=1.0 / rate)
                    except queue.Empty:
                        continue
                matrix = validate_matrix(matrix)
                self.send_matrix(matrix)
                self.root.after(0, self.draw_matrix, matrix)
            except (ValueError, OSError) as exc:
                self.root.after(0, self.status.set, f"Lỗi: {exc}")
                time.sleep(0.5)

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
        self.socket.close()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    app = FSRTransmitterApp(window)
    window.mainloop()
