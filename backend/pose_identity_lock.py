import math
import time


class PoseIdentityLock:
    """Keep MediaPipe lower-limb identities continuous across occlusions."""

    _LEFT_LEG = (23, 25, 27, 29, 31)
    _RIGHT_LEG = (24, 26, 28, 30, 32)
    _LOWER_BODY = _LEFT_LEG + _RIGHT_LEG

    def __init__(
        self,
        *,
        switch_margin=0.006,
        min_visibility=0.35,
        max_gap_seconds=0.75,
    ):
        self.switch_margin = float(switch_margin)
        self.min_visibility = float(min_visibility)
        self.max_gap_seconds = float(max_gap_seconds)
        self.reset()

    def reset(self):
        self._previous = None
        self._previous_2 = None
        self._swap_raw_legs = False
        self._last_at = 0.0

    @staticmethod
    def _read_frame(landmarks):
        return [
            [
                float(item.x),
                float(item.y),
                float(item.z),
                float(getattr(item, "visibility", 1.0)),
            ]
            for item in landmarks.landmark
        ]

    @classmethod
    def _swapped_frame(cls, frame):
        result = [item[:] for item in frame]
        for left, right in zip(cls._LEFT_LEG, cls._RIGHT_LEG):
            result[left], result[right] = frame[right][:], frame[left][:]
        return result

    @classmethod
    def _motion_cost(cls, candidate, predicted, previous):
        total = 0.0
        total_weight = 0.0
        for index in cls._LOWER_BODY:
            point = candidate[index]
            target = predicted[index]
            if not all(math.isfinite(value) for value in (*point[:3], *target[:3])):
                continue
            weight = max(0.05, min(1.0, point[3]))
            weight *= max(0.05, min(1.0, previous[index][3]))
            dx = point[0] - target[0]
            dy = point[1] - target[1]
            dz = point[2] - target[2]
            distance = math.sqrt(dx * dx + dy * dy + 0.12 * dz * dz)
            total += weight * min(distance, 0.30)
            total_weight += weight
        return total / max(total_weight, 1e-6)

    @staticmethod
    def _write_point(target, source):
        target.x = source[0]
        target.y = source[1]
        target.z = source[2]
        if hasattr(target, "visibility"):
            target.visibility = source[3]

    def update(self, landmarks, frame_at=None):
        if landmarks is None:
            return None
        now = float(frame_at if frame_at is not None else time.time())
        raw = self._read_frame(landmarks)
        if len(raw) < 33:
            self.reset()
            return landmarks
        if self._last_at and now - self._last_at > self.max_gap_seconds:
            self.reset()

        if self._previous is None:
            corrected = raw
        else:
            predicted = [item[:] for item in self._previous]
            for index in self._LOWER_BODY:
                for axis in range(3):
                    velocity = self._previous[index][axis] - self._previous_2[index][axis]
                    velocity = max(-0.04, min(0.04, velocity))
                    predicted[index][axis] += 0.75 * velocity

            swapped = self._swapped_frame(raw)
            normal_cost = self._motion_cost(raw, predicted, self._previous)
            swapped_cost = self._motion_cost(swapped, predicted, self._previous)
            if swapped_cost + self.switch_margin < normal_cost:
                self._swap_raw_legs = True
            elif normal_cost + self.switch_margin < swapped_cost:
                self._swap_raw_legs = False
            corrected = swapped if self._swap_raw_legs else raw

            # Prefer a short prediction over a low-confidence point that has
            # jumped onto the visible opposite leg.
            for index in self._LOWER_BODY:
                if corrected[index][3] < self.min_visibility:
                    corrected[index][:3] = predicted[index][:3]

        for index in self._LOWER_BODY:
            self._write_point(landmarks.landmark[index], corrected[index])

        self._previous_2 = (
            [item[:] for item in self._previous]
            if self._previous is not None
            else [item[:] for item in corrected]
        )
        self._previous = [item[:] for item in corrected]
        self._last_at = now
        return landmarks
