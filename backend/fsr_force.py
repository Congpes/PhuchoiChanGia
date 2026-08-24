"""FSR force-unit normalization used by realtime and saved analyses."""

from __future__ import annotations

from typing import Iterable


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
