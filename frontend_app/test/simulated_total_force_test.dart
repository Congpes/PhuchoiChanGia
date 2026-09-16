import 'package:flutter_test/flutter_test.dart';
import 'package:ai_progait/widgets/simulated_total_force_chart.dart';

void main() {
  test('total equals simultaneous sides with filter both on and off', () {
    final frames = List.generate(
        25,
        (i) => {
              'time': i / 60,
              'left': {'total': 10.0 + i * 30},
              'right': {'total': 774.532 - i * 30},
            });
    for (final filter in [false, true]) {
      final series = simultaneousForceSpots(frames, filter);
      for (var i = 0; i < frames.length; i++) {
        expect(series[2][i].x, frames[i]['time']);
        expect(series[2][i].y, closeTo(series[0][i].y + series[1][i].y, 1e-8));
        expect(series[2][i].y, closeTo(784.532, 1e-8));
      }
    }
  });
  test('missing data stays missing instead of fabricating total', () {
    final series = simultaneousForceSpots([
      {'time': 0, 'left': null, 'right': null}
    ], true);
    expect(series[2].single.isNull(), true);
  });
}
