"""FSR force-unit normalization used by realtime and saved analyses."""

from __future__ import annotations

from typing import Iterable
import math


def apply_cell_calibration(matrix, side, profile=None):
    """Apply a specimen-specific profile to legacy Newton estimates.

    Missing cells stay uncalibrated. Never use on raw ADC or already corrected
    packets. This does not claim full-range accuracy or perform live shoe tare.
    """
    values = [list(map(float, row)) for row in matrix]
    if profile is None or side != profile.get('side'):
        return values
    cells = profile.get('cells', [])
    if len(cells) != len(values) or any(len(c) != len(v) for c, v in zip(cells, values)):
        raise ValueError('Calibration shape does not match matrix')
    for row, parameters in zip(values, cells):
        for column, cell in enumerate(parameters):
            if cell is None:
                continue
            baseline, gain = float(cell['baseline_n']), float(cell['gain'])
            if not math.isfinite(baseline) or baseline < 0 or not math.isfinite(gain) or gain <= 0:
                raise ValueError('Invalid cell calibration parameters')
            value = max(0.0, row[column] - baseline)
            if 'points_n' not in cell:
                row[column] = value * gain
                continue
            # Optional three anchors in baseline-subtracted legacy N -> target N.
            # Do not multiply by the old gain again inside the measured range.
            try:
                points = [(float(x), float(y)) for x, y in cell['points_n']]
            except (TypeError, ValueError) as exc:
                raise ValueError('Invalid cell calibration anchors') from exc
            if (len(points) != 3 or points[0] != (0.0, 0.0)
                    or any(not math.isfinite(v) for point in points for v in point)
                    or any(x1 <= x0 or y1 <= y0
                           for (x0, y0), (x1, y1) in zip(points, points[1:]))):
                raise ValueError('Calibration anchors must start at zero and increase')
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if value <= x1:
                    row[column] = y0 + (value - x0) * (y1 - y0) / (x1 - x0)
                    break
            else:
                # Unvalidated extrapolation: retain previous gain beyond last
                # anchor, continuously; never saturate/snap to the test weight.
                x1, y1 = points[-1]
                row[column] = y1 + (value - x1) * gain
    return values


def analog_to_weight_smooth(adc: float) -> float:
    """Convert one raw ADC value to the existing estimated gram calibration."""
    value = float(adc)
    if value >= 4950.0:
        return 0.0
    if value > 680.0:
        return max(0.0, -0.0868 * value + 434.03)
    return 132728.45 * value ** (-0.889) if value > 0 else 0.0


def gram_to_newton(gram: float) -> float:
    return max(0.0, float(gram) * 9.80665 / 1000.0)


def adc_to_newton(adc: float) -> float:
    return gram_to_newton(analog_to_weight_smooth(adc))


def matrix_to_newton(
    matrix: Iterable[Iterable[float]],
    unit: str | None,
) -> tuple[list[list[float]], str, str]:
    """Normalize a received FSR matrix and return values, display unit, source.

    A packet labelled raw_adc is calibrated with the legacy formula, gram is
    converted with standard gravity, and newton is retained as sent.  The
    response names estimated values explicitly until sensor-level calibration
    is available.
    """
    normalized_unit = str(unit or "raw_adc").strip().lower()
    values = [[float(value) for value in row] for row in matrix]
    if normalized_unit == "newton":
        return [[max(0.0, value) for value in row] for row in values], "N", "packet"
    if normalized_unit == "gram":
        force_values = [[gram_to_newton(value) for value in row] for row in values]
    else:
        force_values = [[adc_to_newton(value) for value in row] for row in values]
    return force_values, "N_estimated", "formula_estimate"


def region_totals(matrix: Iterable[Iterable[float]]) -> dict:
    """Return force totals for the agreed 12×4 forefoot/midfoot/heel bands."""
    rows = [list(map(float, row)) for row in matrix]

    def total(first_row: int, last_row: int) -> float:
        return round(
            sum(sum(row) for row in rows[first_row : last_row + 1]),
            4,
        )

    return {
        "heel": total(9, 11),
        "midfoot": total(4, 8),
        "forefoot": total(0, 3),
        "total": round(sum(sum(row) for row in rows), 4),
    }


def matrix_total(matrix: Iterable[Iterable[float]]) -> float:
    return round(sum(sum(float(value) for value in row) for row in matrix), 4)
