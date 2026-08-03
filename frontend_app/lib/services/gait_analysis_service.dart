import '../models/gait_data.dart';

/// Analysis helpers for measurements returned by the FastAPI backend.
/// This service never generates patient or gait data.
class GaitAnalysisService {
  const GaitAnalysisService();

  List<AdjustmentRecommendation> analyze({
    required ScanResult? baseline,
    required ScanResult scan,
    required LegSide healthyLeg,
    required LegSide prostheticLeg,
  }) {
    final healthy = healthyLeg == LegSide.left ? scan.leftKnee : scan.rightKnee;
    final prosthetic = prostheticLeg == LegSide.left ? scan.leftKnee : scan.rightKnee;
    final baselineHealthy = baseline == null
        ? null
        : (healthyLeg == LegSide.left ? baseline.leftKnee : baseline.rightKnee);
    if (healthy.angles.isEmpty || prosthetic.angles.isEmpty) return const [];

    final referencePeak = baselineHealthy != null && baselineHealthy.angles.isNotEmpty
        ? baselineHealthy.maxAngle
        : healthy.maxAngle;
    final delta = referencePeak - prosthetic.maxAngle;
    final recommendations = <AdjustmentRecommendation>[];

    if (delta.abs() >= 8) {
      recommendations.add(AdjustmentRecommendation(
        leg: prostheticLeg,
        issue: 'Thiếu góc gập gối',
        deltaDegrees: delta,
        suggestion: 'Kiểm tra căn chỉnh khớp gối chân giả; sai lệch đo được khoảng ${delta.abs().round()}°.',
        severity: delta.abs() >= 15
            ? RecommendationSeverity.critical
            : RecommendationSeverity.warning,
      ));
    }

    final symmetryDelta = (scan.leftKnee.maxAngle - scan.rightKnee.maxAngle).abs();
    if (symmetryDelta >= 10) {
      recommendations.add(AdjustmentRecommendation(
        leg: scan.leftKnee.maxAngle < scan.rightKnee.maxAngle ? LegSide.left : LegSide.right,
        issue: 'Bất đối xứng biên độ gập gối',
        deltaDegrees: symmetryDelta,
        suggestion: 'Kiểm tra alignment socket và phân bố trọng lượng.',
        severity: RecommendationSeverity.info,
      ));
    }
    return recommendations;
  }

  String compareScans(ScanResult before, ScanResult after, LegSide prostheticLeg) {
    final beforeKnee = prostheticLeg == LegSide.left ? before.leftKnee.maxAngle : before.rightKnee.maxAngle;
    final afterKnee = prostheticLeg == LegSide.left ? after.leftKnee.maxAngle : after.rightKnee.maxAngle;
    final gain = afterKnee - beforeKnee;
    if (gain >= 8) return 'Cải thiện rõ: gập gối +${gain.toStringAsFixed(0)}°.';
    if (gain >= 3) return 'Cải thiện nhẹ: +${gain.toStringAsFixed(0)}°.';
    if (gain <= -2) return 'Chưa cải thiện; cần kiểm tra lại hướng điều chỉnh.';
    return 'Biên độ gập gối gần như không đổi.';
  }
}
