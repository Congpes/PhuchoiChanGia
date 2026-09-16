/// Presentation only: preserve source units and calibration metadata in data.
String displayForceUnit(String unit) => unit
    .replaceAll('N_demo60', 'N')
    .replaceAll('N mô phỏng', 'N')
    .replaceAll('N_estimated', 'N')
    .replaceAll('N (ước tính)', 'N')
    .replaceAll('N ước tính', 'N');

String chartLegLabel(String side) => side == 'left' ? 'Chân trái' : 'Chân phải';

String cameraChartTitle(String metric) => switch (metric) {
      'knee' => 'Góc gối',
      'hip' => 'Góc hông',
      'trunk' || 'lateral_trunk' => 'Góc nghiêng thân',
      _ => metric,
    };

String cameraChartSelector(String metric) => switch (metric) {
      'trunk' => 'Nghiêng trước–sau',
      'lateral_trunk' => 'Nghiêng trái–phải',
      _ => cameraChartTitle(metric),
    };

String cameraChartDirection(String metric) => switch (metric) {
      'trunk' => 'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau',
      'lateral_trunk' => 'Dương: phải · Âm: trái (theo người được đo)',
      _ => '',
    };

({List<double> left, List<double> right}) closeReferenceAngleCurves(
  List<double> left,
  List<double> right, {
  required double leftRatio,
  double commonScale = 1,
}) {
  final count = left.length < right.length ? left.length : right.length;
  if (count == 0) {
    return (left: List<double>.of(left), right: List<double>.of(right));
  }
  final common = List<double>.generate(count, (index) {
    final leftValue = left[index];
    final rightValue = right[index];
    if (leftValue.isFinite && rightValue.isFinite) {
      return (leftValue + rightValue) / 2;
    }
    if (leftValue.isFinite) return leftValue;
    if (rightValue.isFinite) return rightValue;
    return double.nan;
  });
  return (
    left: common.map((value) => value * commonScale * leftRatio).toList(),
    right: common.map((value) => value * commonScale).toList(),
  );
}
