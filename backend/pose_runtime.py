"""Bound CPU scheduling without changing the pinned MediaPipe Pose models.

MediaPipe 0.10.9 exposes no executor setting on Pose. Its SolutionBase expands
the bundled graph before starting it; the narrow override below changes only
that graph's default executor. Pose still owns every calculator option, side
packet and output conversion. Recheck this hook when upgrading MediaPipe.
"""

from pathlib import Path

import mediapipe as mp
from mediapipe.framework import thread_pool_executor_pb2
from mediapipe.python.solutions.pose import Pose


class _BoundedCpuPose(Pose):
    def __init__(self, *, graph_threads, **kwargs):
        self._cpu_graph_threads = graph_threads
        super().__init__(**kwargs)

    def _initialize_graph_interface(self, *args, **kwargs):
        config = super()._initialize_graph_interface(*args, **kwargs)
        config.ClearField("num_threads")
        executor = next((item for item in config.executor if not item.name), None)
        if executor is None:
            executor = config.executor.add()
        executor.type = "ThreadPoolExecutor"
        executor.options.Extensions[
            thread_pool_executor_pb2.ThreadPoolExecutorOptions.ext
        ].num_threads = self._cpu_graph_threads
        return config


def create_cpu_pose(
    *,
    model_complexity,
    min_detection_confidence,
    min_tracking_confidence,
    graph_threads=0,
):
    """Create a tracking Pose with stock scheduling; opt into 1–4 graph workers.

    XNNPACK interpreter settings stay at their bundled defaults. Missing local
    model assets fail explicitly so choosing Lite/Heavy cannot trigger a
    network download during camera startup.
    """
    if type(graph_threads) is not int or not 0 <= graph_threads <= 4:
        raise ValueError("graph_threads must be an integer from 0 to 4")
    if type(model_complexity) is not int or model_complexity not in (0, 1, 2):
        raise ValueError("model_complexity must be 0, 1, or 2")

    package = Path(mp.__file__).resolve().parent
    model_name = ("lite", "full", "heavy")[model_complexity]
    for relative_path in (
        "modules/pose_landmark/pose_landmark_cpu.binarypb",
        "modules/pose_detection/pose_detection.tflite",
        f"modules/pose_landmark/pose_landmark_{model_name}.tflite",
    ):
        asset = package / relative_path
        if not asset.is_file():
            raise FileNotFoundError(f"Required local MediaPipe asset is missing: {asset}")

    options = dict(
        static_image_mode=False,
        model_complexity=model_complexity,
        smooth_landmarks=False,
        enable_segmentation=False,
        min_detection_confidence=min_detection_confidence,
        min_tracking_confidence=min_tracking_confidence,
    )
    if graph_threads == 0:
        return Pose(**options)
    return _BoundedCpuPose(graph_threads=graph_threads, **options)
