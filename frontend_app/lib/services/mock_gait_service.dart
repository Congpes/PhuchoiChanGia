import 'dart:math';

import '../models/gait_data.dart';

class MockGaitService {
  static const int gaitPoints = 101;
  static const double recordDurationSec = 10;

  final _random = Random(42);

  List<double> generateKneeCurve({
    required double peakFlexion,
    required double minExtension,
    double noise = 2,
  }) {
    return List.generate(gaitPoints, (i) {
      final t = i / (gaitPoints - 1);
      final swing = sin(t * pi * 2 - pi / 2);
      final base = minExtension + (peakFlexion - minExtension) * ((swing + 1) / 2);
      return (base + (_random.nextDouble() - 0.5) * noise).clamp(5, 85);
    });
  }

  List<double> generateAnkleCurve({
    required double dorsiPeak,
    required double plantarPeak,
  }) {
    return List.generate(gaitPoints, (i) {
      final t = i / (gaitPoints - 1);
      final wave = sin(t * pi * 2);
      final base = (dorsiPeak + plantarPeak) / 2 + wave * (plantarPeak - dorsiPeak) / 2;
      return (base + (_random.nextDouble() - 0.5) * 1.5).clamp(-20, 30);
    });
  }

  ScanResult buildScan({
    required String id,
    required String label,
    double leftKneePeak = 62,
    double rightKneePeak = 48,
    double leftAnkleRange = 18,
    double rightAnkleRange = 14,
  }) {
    return ScanResult(
      id: id,
      label: label,
      durationSec: recordDurationSec,
      recordedAt: DateTime.now(),
      leftKnee: GaitCycleCurve(
        label: 'Gối trái',
        angles: generateKneeCurve(peakFlexion: leftKneePeak, minExtension: 8),
      ),
      rightKnee: GaitCycleCurve(
        label: 'Gối phải',
        angles: generateKneeCurve(peakFlexion: rightKneePeak, minExtension: 10),
      ),
      leftAnkle: GaitCycleCurve(
        label: 'Cổ chân trái',
        angles: generateAnkleCurve(dorsiPeak: 5, plantarPeak: leftAnkleRange),
      ),
      rightAnkle: GaitCycleCurve(
        label: 'Cổ chân phải',
        angles: generateAnkleCurve(dorsiPeak: 3, plantarPeak: rightAnkleRange),
      ),
    );
  }

  ScanResult buildBaseline(LegSide healthyLeg) {
    final isLeftHealthy = healthyLeg == LegSide.left;
    return buildScan(
      id: 'baseline',
      label: 'Baseline chân lành',
      leftKneePeak: isLeftHealthy ? 62 : 50,
      rightKneePeak: isLeftHealthy ? 50 : 62,
    );
  }

  ScanResult buildEvaluationScan({
    required LegSide healthyLeg,
    required ProstheticSide prostheticLeg,
    bool improved = false,
  }) {
    final deficit = improved ? 6.0 : 14.0;
    final isProstheticRight = prostheticLeg == ProstheticSide.right;
    final isProstheticLeft = prostheticLeg == ProstheticSide.left;

    return buildScan(
      id: improved ? 'scan2' : 'scan1',
      label: improved ? 'Quét xác minh' : 'Quét đánh giá',
      leftKneePeak: isProstheticLeft ? 62 - deficit : 62,
      rightKneePeak: isProstheticRight ? 62 - deficit : 62,
    );
  }

  List<AdjustmentRecommendation> analyze({
    required ScanResult? baseline,
    required ScanResult scan,
    required LegSide healthyLeg,
    required ProstheticSide prostheticLeg,
  }) {
    if (prostheticLeg == ProstheticSide.unknown) return [];

    final healthy = healthyLeg == LegSide.left ? scan.leftKnee : scan.rightKnee;
    final prosthetic = prostheticLeg == ProstheticSide.left
        ? scan.leftKnee
        : scan.rightKnee;

    final baselineHealthy = baseline != null
        ? (healthyLeg == LegSide.left ? baseline.leftKnee : baseline.rightKnee)
        : null;

    final refPeak = baselineHealthy?.maxAngle ?? healthy.maxAngle;
    final delta = refPeak - prosthetic.maxAngle;

    final recs = <AdjustmentRecommendation>[];

    if (delta.abs() >= 8) {
      recs.add(AdjustmentRecommendation(
        leg: prostheticLeg == ProstheticSide.left ? LegSide.left : LegSide.right,
        issue: 'Thiếu góc gập gối',
        deltaDegrees: delta,
        suggestion: prostheticLeg == ProstheticSide.right
            ? 'Gợi ý nới khớp gối chân phải (giả) ~${delta.round()}°'
            : 'Gợi ý nới khớp gối chân trái (giả) ~${delta.round()}°',
        severity: delta >= 15
            ? RecommendationSeverity.critical
            : RecommendationSeverity.warning,
      ));
    }

    final symmetryDelta = (scan.leftKnee.maxAngle - scan.rightKnee.maxAngle).abs();
    if (symmetryDelta >= 10) {
      recs.add(AdjustmentRecommendation(
        leg: scan.leftKnee.maxAngle < scan.rightKnee.maxAngle
            ? LegSide.left
            : LegSide.right,
        issue: 'Bất đối xứng nhịp bước',
        deltaDegrees: symmetryDelta,
        suggestion: 'Kiểm tra alignment socket và phân bố trọng lượng',
        severity: RecommendationSeverity.info,
      ));
    }

    if (recs.isEmpty) {
      recs.add(const AdjustmentRecommendation(
        leg: LegSide.right,
        issue: 'Dáng đi ổn định',
        deltaDegrees: 0,
        suggestion: 'Không cần tinh chỉnh lớn — có thể quét lại để xác minh',
        severity: RecommendationSeverity.info,
      ));
    }

    return recs;
  }

  String compareScans(ScanResult before, ScanResult after, ProstheticSide prostheticLeg) {
    final beforeKnee = prostheticLeg == ProstheticSide.left
        ? before.leftKnee.maxAngle
        : before.rightKnee.maxAngle;
    final afterKnee = prostheticLeg == ProstheticSide.left
        ? after.leftKnee.maxAngle
        : after.rightKnee.maxAngle;
    final gain = afterKnee - beforeKnee;

    if (gain >= 8) {
      return 'Cải thiện rõ: gập gối +${gain.toStringAsFixed(0)}° so với lần quét trước.';
    }
    if (gain >= 3) {
      return 'Cải thiện nhẹ (+${gain.toStringAsFixed(0)}°). Nên quét thêm hoặc tinh chỉnh tiếp.';
    }
    if (gain <= -2) {
      return 'Chưa cải thiện — kiểm tra lại hướng chỉnh khớp.';
    }
    return 'Gần như không đổi — thử điều chỉnh thêm hoặc hướng dẫn bệnh nhân tập.';
  }
}
