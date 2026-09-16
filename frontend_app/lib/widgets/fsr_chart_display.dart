/// Measured-force helpers. No visual rebalancing of left/right amplitudes.
class AdaptiveFsrDisplayScale {
  static double peak(Iterable<double> values) {
    var result = 0.0;
    for (final value in values) {
      if (value.isFinite && value > result) result = value;
    }
    return result;
  }
}
