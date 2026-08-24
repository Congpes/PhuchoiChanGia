"""ChArUco-based geometric calibration for the two physical cameras."""

from __future__ import annotations

import json
import math
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np


class StereoCalibrationError(RuntimeError):
    pass


class StereoCalibrationManager:
    def __init__(
        self,
        storage_path: str | Path,
        *,
        squares_x: int = 7,
        squares_y: int = 5,
        square_length_m: float = 0.030,
        marker_length_m: float = 0.022,
        minimum_samples: int = 12,
    ):
        self.storage_path = Path(storage_path)
        self.squares_x = int(squares_x)
        self.squares_y = int(squares_y)
        self.square_length_m = float(square_length_m)
        self.marker_length_m = float(marker_length_m)
        self.minimum_samples = int(minimum_samples)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.board = cv2.aruco.CharucoBoard(
            (self.squares_x, self.squares_y),
            self.square_length_m,
            self.marker_length_m,
            dictionary,
        )
        self.detector = cv2.aruco.CharucoDetector(self.board)
        self._lock = threading.Lock()
        self._samples: list[dict[str, Any]] = []
        self._calibration = self._load()
        self._last_capture_ns: tuple[int, int] | None = None

    def _load(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    def _save(self, calibration: Mapping[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(dict(calibration), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.storage_path)

    def board_png(self, pixels_per_square: int = 300) -> bytes:
        pixels_per_square = int(pixels_per_square)
        board_width = self.squares_x * pixels_per_square
        board_height = self.squares_y * pixels_per_square
        board_image = self.board.generateImage((board_width, board_height), marginSize=0)
        # A4 landscape canvas keeps a generous white border around the board.
        # With 30 mm squares, 300 px/square is exactly 10 px/mm.
        pixels_per_mm = pixels_per_square / (self.square_length_m * 1000.0)
        page_width = int(round(297.0 * pixels_per_mm))
        page_height = int(round(210.0 * pixels_per_mm))
        image = np.full((page_height, page_width), 255, dtype=np.uint8)
        offset_x = (page_width - board_width) // 2
        offset_y = (page_height - board_height) // 2
        image[offset_y:offset_y + board_height, offset_x:offset_x + board_width] = board_image
        encoded, png = cv2.imencode(".png", image)
        if not encoded:
            raise StereoCalibrationError("Cannot generate calibration board image.")
        png_bytes = png.tobytes()
        pixels_per_meter = int(round(pixels_per_mm * 1000.0))
        physical_data = struct.pack(">IIB", pixels_per_meter, pixels_per_meter, 1)
        chunk_type = b"pHYs"
        physical_chunk = (
            struct.pack(">I", len(physical_data))
            + chunk_type
            + physical_data
            + struct.pack(">I", zlib.crc32(chunk_type + physical_data) & 0xFFFFFFFF)
        )
        # PNG signature (8 bytes) followed by the fixed-size IHDR chunk (25 bytes).
        return png_bytes[:33] + physical_chunk + png_bytes[33:]

    def board_info(self) -> dict[str, Any]:
        return {
            "type": "ChArUco DICT_4X4_50",
            "squaresX": self.squares_x,
            "squaresY": self.squares_y,
            "squareLengthMm": round(self.square_length_m * 1000.0, 2),
            "markerLengthMm": round(self.marker_length_m * 1000.0, 2),
            "printWidthMm": round(self.squares_x * self.square_length_m * 1000.0, 2),
            "printHeightMm": round(self.squares_y * self.square_length_m * 1000.0, 2),
            "printPage": "A4 landscape / actual size 100%",
            "minimumSamples": self.minimum_samples,
        }

    def reset_samples(self) -> dict[str, Any]:
        with self._lock:
            self._samples.clear()
            self._last_capture_ns = None
        return self.status()

    def _detect(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            raise StereoCalibrationError("Camera frame is empty.")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        corners, ids, _, _ = self.detector.detectBoard(gray)
        if corners is None or ids is None or len(ids) < 8:
            count = 0 if ids is None else len(ids)
            raise StereoCalibrationError(
                f"Only {count} ChArUco corners detected; at least 8 are required in both cameras."
            )
        return (
            np.asarray(corners, dtype=np.float32).reshape(-1, 2),
            np.asarray(ids, dtype=np.int32).reshape(-1),
        )

    def capture_pair(
        self,
        frame_0: np.ndarray,
        frame_1: np.ndarray,
        captured_ns_0: int,
        captured_ns_1: int,
        *,
        max_skew_ms: float,
    ) -> dict[str, Any]:
        captured_ns_0 = int(captured_ns_0)
        captured_ns_1 = int(captured_ns_1)
        skew_ms = abs(captured_ns_0 - captured_ns_1) / 1_000_000.0
        if skew_ms > float(max_skew_ms):
            raise StereoCalibrationError(
                f"Calibration frames differ by {skew_ms:.1f} ms; limit is {max_skew_ms:.1f} ms."
            )
        if frame_0.shape[:2] != frame_1.shape[:2]:
            raise StereoCalibrationError(
                "Both cameras must use the same frame resolution during calibration."
            )
        pair_id = (captured_ns_0, captured_ns_1)
        with self._lock:
            if pair_id == self._last_capture_ns:
                raise StereoCalibrationError(
                    "Move the board before capturing the next calibration pose."
                )

        corners_0, ids_0 = self._detect(frame_0)
        corners_1, ids_1 = self._detect(frame_1)
        common = sorted(set(ids_0.tolist()).intersection(ids_1.tolist()))
        if len(common) < 8:
            raise StereoCalibrationError(
                f"Only {len(common)} common corners are visible; at least 8 are required."
            )
        with self._lock:
            previous = self._samples[-1] if self._samples else None
        if previous is not None:
            def normalized_motion(previous_corners, previous_ids, current_corners, current_ids):
                previous_map = {
                    int(identifier): np.asarray(point, dtype=float)
                    for identifier, point in zip(previous_ids, previous_corners)
                }
                current_map = {
                    int(identifier): np.asarray(point, dtype=float)
                    for identifier, point in zip(current_ids, current_corners)
                }
                shared = sorted(set(previous_map).intersection(current_map))
                if len(shared) < 8:
                    return math.inf
                scale = np.asarray([frame_0.shape[1], frame_0.shape[0]], dtype=float)
                distances = [
                    np.linalg.norm((current_map[index] - previous_map[index]) / scale)
                    for index in shared
                ]
                return float(np.mean(distances))

            motion_0 = normalized_motion(
                previous["corners0"], previous["ids0"], corners_0, ids_0
            )
            motion_1 = normalized_motion(
                previous["corners1"], previous["ids1"], corners_1, ids_1
            )
            if motion_0 < 0.012 and motion_1 < 0.012:
                raise StereoCalibrationError(
                    "Board pose is too similar to the previous sample; move or tilt it more."
                )
        sample = {
            "imageSize": [int(frame_0.shape[1]), int(frame_0.shape[0])],
            "corners0": corners_0,
            "ids0": ids_0,
            "corners1": corners_1,
            "ids1": ids_1,
            "commonCorners": len(common),
            "syncErrorMs": skew_ms,
        }
        with self._lock:
            self._samples.append(sample)
            self._last_capture_ns = pair_id
            sample_count = len(self._samples)
        return {
            "captured": True,
            "sampleCount": sample_count,
            "minimumSamples": self.minimum_samples,
            "commonCorners": len(common),
            "syncErrorMs": round(skew_ms, 2),
            "readyToSolve": sample_count >= self.minimum_samples,
        }

    @staticmethod
    def _json_matrix(value: np.ndarray) -> list:
        return np.asarray(value, dtype=float).tolist()

    def solve(self, camera_indices: tuple[int, int]) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
        if len(samples) < self.minimum_samples:
            raise StereoCalibrationError(
                f"Capture at least {self.minimum_samples} board poses before solving calibration."
            )
        image_size = tuple(samples[0]["imageSize"])
        if any(tuple(item["imageSize"]) != image_size for item in samples):
            raise StereoCalibrationError("Camera resolution changed during calibration.")

        board_points = np.asarray(self.board.getChessboardCorners(), dtype=np.float32)
        object_0 = [board_points[item["ids0"]].reshape(-1, 3) for item in samples]
        image_0 = [item["corners0"].reshape(-1, 2) for item in samples]
        object_1 = [board_points[item["ids1"]].reshape(-1, 3) for item in samples]
        image_1 = [item["corners1"].reshape(-1, 2) for item in samples]

        rms_0, matrix_0, distortion_0, _, _ = cv2.calibrateCamera(
            object_0, image_0, image_size, None, None
        )
        rms_1, matrix_1, distortion_1, _, _ = cv2.calibrateCamera(
            object_1, image_1, image_size, None, None
        )

        stereo_object = []
        stereo_image_0 = []
        stereo_image_1 = []
        for item in samples:
            map_0 = {
                int(identifier): point
                for identifier, point in zip(item["ids0"], item["corners0"])
            }
            map_1 = {
                int(identifier): point
                for identifier, point in zip(item["ids1"], item["corners1"])
            }
            common = sorted(set(map_0).intersection(map_1))
            if len(common) < 8:
                continue
            stereo_object.append(board_points[common].reshape(-1, 3))
            stereo_image_0.append(
                np.asarray(
                    [map_0[index] for index in common],
                    dtype=np.float32,
                ).reshape(-1, 2)
            )
            stereo_image_1.append(
                np.asarray(
                    [map_1[index] for index in common],
                    dtype=np.float32,
                ).reshape(-1, 2)
            )
        if len(stereo_object) < self.minimum_samples:
            raise StereoCalibrationError(
                "Not enough valid paired views remain for stereo calibration."
            )

        criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
            100,
            1e-6,
        )
        (
            stereo_rms,
            matrix_0,
            distortion_0,
            matrix_1,
            distortion_1,
            rotation,
            translation,
            _,
            _,
        ) = cv2.stereoCalibrate(
            stereo_object,
            stereo_image_0,
            stereo_image_1,
            matrix_0,
            distortion_0,
            matrix_1,
            distortion_1,
            image_size,
            flags=cv2.CALIB_FIX_INTRINSIC,
            criteria=criteria,
        )
        baseline_m = float(np.linalg.norm(translation))
        valid = bool(
            math.isfinite(stereo_rms)
            and stereo_rms <= 1.5
            and rms_0 <= 1.2
            and rms_1 <= 1.2
            and baseline_m > 0.05
        )
        calibration = {
            "version": 1,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cameraIndices": [int(camera_indices[0]), int(camera_indices[1])],
            "imageSize": list(image_size),
            "sampleCount": len(samples),
            "board": self.board_info(),
            "rmsCamera0": float(rms_0),
            "rmsCamera1": float(rms_1),
            "stereoRms": float(stereo_rms),
            "baselineM": baseline_m,
            "valid": valid,
            "cameraMatrix0": self._json_matrix(matrix_0),
            "distortion0": self._json_matrix(distortion_0),
            "cameraMatrix1": self._json_matrix(matrix_1),
            "distortion1": self._json_matrix(distortion_1),
            "rotation": self._json_matrix(rotation),
            "translation": self._json_matrix(translation),
        }
        self._save(calibration)
        with self._lock:
            self._calibration = calibration
        return self.status(camera_indices)

    def compatible(self, camera_indices: tuple[int, int] | None = None) -> bool:
        calibration = self._calibration
        if not calibration or not calibration.get("valid", False):
            return False
        if camera_indices is None:
            return True
        return calibration.get("cameraIndices") == [int(camera_indices[0]), int(camera_indices[1])]

    def status(self, camera_indices: tuple[int, int] | None = None) -> dict[str, Any]:
        with self._lock:
            sample_count = len(self._samples)
            calibration = dict(self._calibration) if self._calibration else None
        compatible = self.compatible(camera_indices)
        summary = None
        if calibration:
            summary = {
                key: calibration.get(key)
                for key in (
                    "createdAt", "cameraIndices", "imageSize", "sampleCount",
                    "rmsCamera0", "rmsCamera1", "stereoRms", "baselineM", "valid",
                )
            }
        return {
            "board": self.board_info(),
            "sampleCount": sample_count,
            "minimumSamples": self.minimum_samples,
            "readyToSolve": sample_count >= self.minimum_samples,
            "calibrated": calibration is not None,
            "compatible": compatible,
            "calibration": summary,
        }

    def triangulate(
        self,
        landmarks_0: Mapping[str, Mapping[str, float]],
        landmarks_1: Mapping[str, Mapping[str, float]],
        *,
        camera_indices: tuple[int, int],
        image_size_0: tuple[int, int],
        image_size_1: tuple[int, int],
    ) -> dict[str, Any]:
        calibration = self._calibration
        if not self.compatible(camera_indices) or calibration is None:
            raise StereoCalibrationError("No compatible stereo calibration is available.")
        calibrated_size = tuple(int(value) for value in calibration["imageSize"])
        if tuple(image_size_0) != calibrated_size or tuple(image_size_1) != calibrated_size:
            raise StereoCalibrationError(
                "Live camera resolution differs from the saved calibration."
            )

        names = sorted(set(landmarks_0).intersection(landmarks_1))
        points_0 = np.asarray(
            [
                [
                    float(landmarks_0[name]["x"]) * image_size_0[0],
                    float(landmarks_0[name]["y"]) * image_size_0[1],
                ]
                for name in names
            ],
            dtype=np.float64,
        )
        points_1 = np.asarray(
            [
                [
                    float(landmarks_1[name]["x"]) * image_size_1[0],
                    float(landmarks_1[name]["y"]) * image_size_1[1],
                ]
                for name in names
            ],
            dtype=np.float64,
        )
        matrix_0 = np.asarray(calibration["cameraMatrix0"], dtype=np.float64)
        distortion_0 = np.asarray(calibration["distortion0"], dtype=np.float64)
        matrix_1 = np.asarray(calibration["cameraMatrix1"], dtype=np.float64)
        distortion_1 = np.asarray(calibration["distortion1"], dtype=np.float64)
        rotation = np.asarray(calibration["rotation"], dtype=np.float64)
        translation = np.asarray(calibration["translation"], dtype=np.float64).reshape(3, 1)
        normalized_0 = cv2.undistortPoints(
            points_0.reshape(-1, 1, 2),
            matrix_0,
            distortion_0,
        ).reshape(-1, 2)
        normalized_1 = cv2.undistortPoints(
            points_1.reshape(-1, 1, 2),
            matrix_1,
            distortion_1,
        ).reshape(-1, 2)
        projection_0 = np.hstack((np.eye(3), np.zeros((3, 1))))
        projection_1 = np.hstack((rotation, translation))
        homogeneous = cv2.triangulatePoints(
            projection_0,
            projection_1,
            normalized_0.T,
            normalized_1.T,
        )
        xyz = (homogeneous[:3] / homogeneous[3]).T

        projected_0, _ = cv2.projectPoints(xyz, np.zeros(3), np.zeros(3), matrix_0, distortion_0)
        rotation_vector, _ = cv2.Rodrigues(rotation)
        projected_1, _ = cv2.projectPoints(
            xyz,
            rotation_vector,
            translation,
            matrix_1,
            distortion_1,
        )
        error_0 = np.linalg.norm(projected_0.reshape(-1, 2) - points_0, axis=1)
        error_1 = np.linalg.norm(projected_1.reshape(-1, 2) - points_1, axis=1)
        reprojection = (error_0 + error_1) / 2.0
        return {
            "points": {name: xyz[index].tolist() for index, name in enumerate(names)},
            "reprojectionErrorPx": float(np.mean(reprojection)),
            "maxReprojectionErrorPx": float(np.max(reprojection)),
            "calibrationStereoRms": float(calibration["stereoRms"]),
        }
