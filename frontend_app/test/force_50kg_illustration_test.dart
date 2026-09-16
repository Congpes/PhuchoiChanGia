import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_progait/demo/force_50kg_illustration.dart';

void main() {
  test('one factor preserves ratios, SD and original while scaling regional sum', () {
    final input = <String, dynamic>{'regions': {
      for (final region in ['heel', 'midfoot', 'forefoot']) region: {
        'left': {'mean': [10, 30, 20], 'sd': [1, 3, 2]},
        'right': {'mean': [20, 60, 40], 'sd': [2, 6, 4]},
      },
    }, 'forceSummary': {'rows': []}};
    final original = jsonEncode(input);
    final output = illustrateForce50Kg(input);
    expect(jsonEncode(input), original);
    final regions = output['regions'] as Map;
    final total = ['heel','midfoot','forefoot'].fold<double>(0, (sum, key) => sum + regions[key]['right']['mean'][1]);
    expect(total, closeTo(490.3325, 1e-6));
    expect(regions['heel']['right']['mean'][1] / regions['heel']['left']['mean'][1], 2);
    expect(regions['heel']['left']['mean'][1] / regions['heel']['left']['sd'][1], closeTo(10, 1e-6));
    expect(output['unit'], 'N minh họa 50 kg');
    expect(output.containsKey('forceSummary'), false);
  });
}
