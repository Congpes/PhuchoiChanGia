import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import numpy as np
import mediapipe as mp
from mediapipe.calculators.tensor import tensors_to_detections_calculator_pb2
from mediapipe.calculators.util import thresholding_calculator_pb2
from mediapipe.framework import calculator_pb2, thread_pool_executor_pb2
from mediapipe.python import packet_getter
from mediapipe.python.solutions import pose as pose_module
from mediapipe.python.solutions.pose import Pose

from pose_runtime import create_cpu_pose


def graph_config(detector):
    config = calculator_pb2.CalculatorGraphConfig()
    config.ParseFromString(detector._graph.binary_config)
    return config


class CpuPoseRuntimeTests(unittest.TestCase):
    def test_executor_bound_preserves_stock_graph_and_pose_options(self):
        # Changing model parameters while bounding workers must fail this test.
        with create_cpu_pose(
            model_complexity=1,
            min_detection_confidence=0.63,
            min_tracking_confidence=0.57,
            graph_threads=0,
        ) as stock:
            stock_config = graph_config(stock)
            self.assertIs(type(stock), Pose)
            for threads in (1, 2, 4):
                with self.subTest(graph_threads=threads), create_cpu_pose(
                    model_complexity=1,
                    min_detection_confidence=0.63,
                    min_tracking_confidence=0.57,
                    graph_threads=threads,
                ) as bounded:
                    config = graph_config(bounded)
                    executors = [item for item in config.executor if not item.name]
                    self.assertEqual(len(executors), 1)
                    executor = executors[0]
                    self.assertEqual(executor.type, "ThreadPoolExecutor")
                    self.assertEqual(
                        executor.options.Extensions[
                            thread_pool_executor_pb2.ThreadPoolExecutorOptions.ext
                        ].num_threads,
                        threads,
                    )
                    config.ClearField("executor")
                    stock_copy = calculator_pb2.CalculatorGraphConfig()
                    stock_copy.CopyFrom(stock_config)
                    stock_copy.ClearField("executor")
                    self.assertEqual(config, stock_copy)
                    nodes = {node.name: node for node in config.node}
                    self.assertAlmostEqual(
                        nodes[
                            "posedetectioncpu__TensorsToDetectionsCalculator"
                        ].options.Extensions[
                            tensors_to_detections_calculator_pb2.TensorsToDetectionsCalculatorOptions.ext
                        ].min_score_thresh,
                        0.63,
                        places=6,
                    )
                    self.assertAlmostEqual(
                        nodes[
                            "poselandmarkbyroicpu__tensorstoposelandmarksandsegmentation__ThresholdingCalculator"
                        ].options.Extensions[
                            thresholding_calculator_pb2.ThresholdingCalculatorOptions.ext
                        ].threshold,
                        0.57,
                        places=6,
                    )
                    self.assertEqual(
                        packet_getter.get_int(bounded._input_side_packets["model_complexity"]),
                        1,
                    )
                    for name, expected in {
                        "smooth_landmarks": False,
                        "enable_segmentation": False,
                        "smooth_segmentation": True,
                        "use_prev_landmarks": True,
                    }.items():
                        self.assertIs(
                            packet_getter.get_bool(bounded._input_side_packets[name]),
                            expected,
                        )

    def test_explicit_bound_keeps_pose_process_and_real_blank_frame_result(self):
        with create_cpu_pose(
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.45,
            graph_threads=1,
        ) as detector:
            self.assertIs(type(detector).process, Pose.process)
            result = detector.process(np.zeros((64, 64, 3), dtype=np.uint8))
            self.assertIsNone(result.pose_landmarks)
            self.assertIsNone(result.pose_world_landmarks)
            self.assertIsNone(result.segmentation_mask)
            executor = graph_config(detector).executor[0]
            self.assertEqual(
                executor.options.Extensions[
                    thread_pool_executor_pb2.ThreadPoolExecutorOptions.ext
                ].num_threads,
                1,
            )

    def test_two_worker_graphs_process_readonly_inputs_independently(self):
        def run_detector(threads):
            with create_cpu_pose(model_complexity=1, min_detection_confidence=.5,
                                 min_tracking_confidence=.45,
                                 graph_threads=threads) as detector:
                source = np.zeros((64, 64, 3), dtype=np.uint8)
                source.flags.writeable = False
                for _ in range(3):
                    result = detector.process(source)
                    self.assertIsNone(result.pose_landmarks)
                self.assertFalse(source.any())
                return True

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(list(workers.map(run_detector, (1, 1))), [True, True])

    def test_invalid_worker_counts_are_rejected_before_starting_a_graph(self):
        for threads in (-1, 5, 1.5, "1", True):
            with self.subTest(graph_threads=threads), self.assertRaises(ValueError):
                create_cpu_pose(
                    model_complexity=1,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.45,
                    graph_threads=threads,
                )

    def test_missing_model_fails_locally_without_downloading(self):
        missing_model = "pose_landmark_heavy.tflite"
        original_is_file = Path.is_file

        def available(path):
            return False if path.name == missing_model else original_is_file(path)

        with patch.object(Path, "is_file", available), patch.object(
            pose_module.download_utils,
            "download_oss_model",
            side_effect=AssertionError("Pose must not download a missing model"),
        ):
            with self.assertRaisesRegex(FileNotFoundError, missing_model):
                create_cpu_pose(
                    model_complexity=2,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.45,
                )

    def test_requested_model_complexity_reaches_the_graph(self):
        for complexity in (0, 2):
            model = ('lite', 'full', 'heavy')[complexity]
            if not (Path(mp.__file__).parent / 'modules' / 'pose_landmark'
                    / f'pose_landmark_{model}.tflite').is_file():
                continue  # Optional models are not shipped by every wheel.
            with self.subTest(model_complexity=complexity), create_cpu_pose(
                model_complexity=complexity,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.45,
            ) as detector:
                self.assertEqual(
                    packet_getter.get_int(detector._input_side_packets["model_complexity"]),
                    complexity,
                )


if __name__ == "__main__":
    unittest.main()
