import 'package:flutter_test/flutter_test.dart';
import 'package:ai_progait/widgets/chart_labels.dart';
import 'package:ai_progait/widgets/realtime_chart_workspace.dart';

void main() {
  test('chart leg labels do not expose patient classification', () {
    expect(chartLegLabel('left'), 'Chân trái');
    expect(chartLegLabel('right'), 'Chân phải');
  });
  test('force labels shorten Newton without changing other units', () {
    expect(displayForceUnit('N_estimated'), 'N');
    expect(displayForceUnit('N_estimated·s'), 'N·s');
    expect(displayForceUnit('N_demo60'), 'N');
    expect(displayForceUnit('N_demo60·s'), 'N·s');
    expect(displayForceUnit('N (ước tính)'), 'N');
    expect(displayForceUnit('N ước tính'), 'N');
    expect(displayForceUnit('N'), 'N');
    expect(displayForceUnit('Q'), 'Q');
    expect(displayForceUnit('N mô phỏng'), 'N');
  });

  test('camera titles are short but trunk selectors remain distinct', () {
    expect(RealtimeChartType.kneeCycle.label, 'Góc gối');
    expect(RealtimeChartType.hipCycle.label, 'Góc hông');
    expect(RealtimeChartType.trunkCycle.label, 'Góc nghiêng thân');
    expect(RealtimeChartType.lateralTrunkCycle.label, 'Góc nghiêng thân');
    expect(RealtimeChartType.trunkCycle.selectionLabel, 'Nghiêng trước–sau');
    expect(RealtimeChartType.lateralTrunkCycle.selectionLabel,
        'Nghiêng trái–phải');
  });

  test('direction captions describe patient sides and both signs', () {
    expect(cameraChartDirection('lateral_trunk'),
        'Dương: phải · Âm: trái (theo người được đo)');
    expect(cameraChartDirection('trunk'),
        'Dương: nghiêng về phía trước · Âm: nghiêng về phía sau');
  });

  test('reference knee and hip curves keep one shared shape with mild gap', () {
    final result = closeReferenceAngleCurves(
      [8, 18, 28],
      [12, 22, 32],
      leftRatio: .97,
    );
    expect(result.right, [10, 20, 30]);
    expect(result.left[0], closeTo(9.7, 1e-9));
    expect(result.left[1], closeTo(19.4, 1e-9));
    expect(result.left[2], closeTo(29.1, 1e-9));
  });
}
