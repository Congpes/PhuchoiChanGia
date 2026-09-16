import 'dart:convert';
import 'dart:math';

/// A visual scenario, not a calibration or an estimate of actual ground force.
Map<String, dynamic> illustrateForce50Kg(Map<String, dynamic> source) {
  final result = jsonDecode(jsonEncode(source)) as Map<String, dynamic>;
  final regions = result['regions'];
  if (regions is! Map) return result;
  var peakTotal = 0.0;
  for (final side in ['left', 'right']) {
    final curves = [
      for (final region in ['heel', 'midfoot', 'forefoot'])
        (regions[region]?[side]?['mean'] as List?) ?? const []
    ];
    if (curves.any((c) => c.isEmpty)) continue;
    for (var i = 0; i < curves.map((c) => c.length).reduce(min); i++) {
      if (curves.any((c) => c[i] is! num || !(c[i] as num).isFinite)) continue;
      peakTotal = max(peakTotal,
          curves.fold<double>(0, (sum, c) => sum + (c[i] as num).toDouble()));
    }
  }
  if (peakTotal <= 0) return result;
  // Apply one common scale to all regions and both feet, preserving ratios.
  final factor = 50 * 9.80665 / peakTotal;
  for (final region in ['heel', 'midfoot', 'forefoot']) {
    for (final side in ['left', 'right']) {
      final values = regions[region]?[side];
      if (values is! Map) continue;
      for (final field in ['mean', 'sd']) {
        if (values[field] is List) {
          values[field] = (values[field] as List)
              .map((v) => v is num ? v * factor : v)
              .toList();
        }
      }
    }
  }
  result['unit'] = 'N minh họa 50 kg';
  result['illustrationScale'] = factor;
  result['illustrationNote'] =
      'Assumed peak sum of three regions on one foot = 490.3325 N. Not measured or calibrated. Separate stance-normalized feet must not be summed by phase.';
  // Original measured summary is available when the illustration is switched off.
  result.remove('forceSummary');
  result.remove('qualityPolicy');
  return result;
}
