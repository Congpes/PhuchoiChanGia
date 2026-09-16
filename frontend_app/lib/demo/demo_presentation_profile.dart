import 'dart:math';

import '../models/gait_data.dart';

/// Curated, deterministic values used only by the clearly labelled demo view.
/// They preserve the shape of the recorded sample while presenting a mild,
/// internally consistent left-prosthetic asymmetry for screenshots and demos.
class DemoPresentationProfile {
  const DemoPresentationProfile._();

  static Patient get patient => Patient(
        id: 'demo-patient-left-prosthetic',
        name: 'Bệnh nhân mẫu',
        age: 34,
        heightCm: 168,
        weightKg: 60,
        leftLegLengthCm: 88.5,
        rightLegLengthCm: 89,
        healthyLeg: LegSide.right,
        prostheticLeg: LegSide.left,
        injuryHistory: 'Hai chân lành; dữ liệu tham khảo.',
        treatmentGoals: 'Cải thiện đối xứng tải và độ linh hoạt khi đi bộ.',
      );

  static ScanResult get baseline => _metricsScan(
        id: 'demo-baseline',
        label: 'Mẫu tham chiếu cân bằng',
        leftScale: 0.99,
        loadSymmetry: 99.1,
        cadence: 111,
        strideLength: 0.72,
      );

  static ScanResult get scan => _metricsScan(
        id: 'demo-mild-left-prosthetic',
        label: 'Sai lệch nhẹ',
        leftScale: 0.965,
        loadSymmetry: 97.2,
        cadence: 108,
        strideLength: 0.69,
      );

  static ScanResult _metricsScan({
    required String id,
    required String label,
    required double leftScale,
    required double loadSymmetry,
    required double cadence,
    required double strideLength,
  }) {
    List<double> wave(double minimum, double excursion, {double scale = 1}) {
      return List<double>.generate(101, (index) {
        final phase = index / 100 * 2 * pi;
        final shaped = (1 - cos(phase)) / 2;
        return double.parse(
          (minimum + excursion * shaped * scale).toStringAsFixed(3),
        );
      });
    }

    List<double> pelvis(double amplitude) => List<double>.generate(101, (i) {
          final value = amplitude * sin(i / 100 * 4 * pi);
          return double.parse(value.toStringAsFixed(3));
        });

    return ScanResult(
      id: id,
      label: label,
      durationSec: 38.1,
      leftKnee: GaitCycleCurve(
        label: 'Góc gối · Chân trái',
        angles: wave(4.2, 42.5, scale: leftScale),
      ),
      rightKnee: GaitCycleCurve(
        label: 'Góc gối · Chân phải',
        angles: wave(4, 42.5),
      ),
      leftAnkle: GaitCycleCurve(
        label: 'Góc cổ chân · Chân trái',
        angles: wave(3.2, 15.5, scale: leftScale),
      ),
      rightAnkle: GaitCycleCurve(
        label: 'Góc cổ chân · Chân phải',
        angles: wave(3, 15.5),
      ),
      leftHip: GaitCycleCurve(
        label: 'Góc hông · Chân trái',
        angles: wave(2.8, 20, scale: leftScale),
      ),
      rightHip: GaitCycleCurve(
        label: 'Góc hông · Chân phải',
        angles: wave(2.6, 20),
      ),
      pelvicTilt: GaitCycleCurve(
        label: 'Nghiêng chậu',
        angles: pelvis(leftScale < 0.98 ? 2.2 : 1.6),
      ),
      cadence: cadence,
      strideLength: strideLength,
      plantarLoadSymmetry: loadSymmetry,
      fatigueFlag: 0,
      fatigueSlope: 0.02,
      actualAdjustmentDegrees: 2,
      actualAdjustmentNotes:
          'Theo dõi giảm tải nhẹ chân trái; ưu tiên tinh chỉnh nhỏ và quét xác minh.',
      recordedAt: DateTime(2026, 9, 4, 9, 30),
    );
  }
}
