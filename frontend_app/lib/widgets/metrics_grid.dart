import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/gait_data.dart';
import '../providers/session_provider.dart';
import '../theme/app_theme.dart';
import 'gait_chart.dart';

class MetricsGrid extends StatelessWidget {
  const MetricsGrid({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SessionProvider>();
    final session = provider.session;
    final patient = provider.activePatient;
    final scan = session.activeScan;
    final baseline = session.baseline;

    GaitCycleCurve? baselineKneeLeft;
    GaitCycleCurve? baselineKneeRight;
    if (baseline != null && patient != null) {
      baselineKneeLeft = patient.healthyLeg == LegSide.left
          ? baseline.leftKnee
          : null;
      baselineKneeRight = patient.healthyLeg == LegSide.right
          ? baseline.rightKnee
          : null;
    }

    GaitCycleCurve? baselinePelvic;
    if (baseline != null) {
      baselinePelvic = baseline.pelvicTilt;
    }

    return Column(
      children: [
        Expanded(
          child: Row(
            children: [
              Expanded(
                child: GaitChart(
                  title: 'Cổ chân trái (L)',
                  yAxisLabel: 'Ankle flexion',
                  primaryCurve: scan?.leftAnkle,
                  lineColor: AppColors.leftLeg,
                ),
              ),
              Expanded(
                child: GaitChart(
                  title: 'Cổ chân phải (R)',
                  yAxisLabel: 'Ankle flexion',
                  primaryCurve: scan?.rightAnkle,
                  lineColor: AppColors.rightLeg,
                ),
              ),
              Expanded(
                child: GaitChart(
                  title: 'Nghiêng xương chậu (Pelvic Tilt)',
                  yAxisLabel: 'Góc nghiêng hông (°)',
                  primaryCurve: scan?.pelvicTilt,
                  secondaryCurve: baselinePelvic,
                  lineColor: AppColors.accentGreen,
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: Row(
            children: [
              Expanded(
                child: GaitChart(
                  title: 'Gối trái (L)',
                  yAxisLabel: 'Knee flexion',
                  primaryCurve: scan?.leftKnee,
                  secondaryCurve: baselineKneeLeft,
                  lineColor: AppColors.leftLeg,
                ),
              ),
              Expanded(
                child: GaitChart(
                  title: 'Gối phải (R)',
                  yAxisLabel: 'Knee flexion',
                  primaryCurve: scan?.rightKnee,
                  secondaryCurve: baselineKneeRight,
                  lineColor: AppColors.rightLeg,
                ),
              ),
              Expanded(
                child: Container(
                  margin: const EdgeInsets.all(4),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.panel,
                    border: Border.all(color: AppColors.border),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Text(
                        'THÔNG SỐ KHÔNG GIAN - THỜI GIAN',
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: AppColors.textSecondary, letterSpacing: 0.8),
                      ),
                      const SizedBox(height: 12),
                      _buildMiniMetric(
                        Icons.speed,
                        'Nhịp điệu (Cadence)',
                        scan?.cadence != null ? '${scan!.cadence!.toStringAsFixed(0)} bước/phút' : 'Chờ đo lường...',
                        color: AppColors.accent,
                      ),
                      const SizedBox(height: 10),
                      _buildMiniMetric(
                        Icons.straighten,
                        'Độ dài sải chân (Stride Length)',
                        scan?.strideLength != null ? '${scan!.strideLength!.toStringAsFixed(2)} m' : 'Chờ đo lường...',
                        color: AppColors.accentGreen,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildMiniMetric(IconData icon, String label, String value, {required Color color}) {
    return Row(
      children: [
        Icon(icon, size: 20, color: color),
        const SizedBox(width: 8),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
            const SizedBox(height: 2),
            Text(value, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.white)),
          ],
        ),
      ],
    );
  }
}
