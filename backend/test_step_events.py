import unittest
import numpy as np

from step_events import camera_step_intervals, pair_step_intervals
from gait_cycle_pipeline import (
    _normalized_interval, analyze_gait_cycles,
    build_camera_gait_cycles, build_synchronized_gait_cycles,
)
from fsr_step_pipeline import FsrStepPipeline, _normalize


def walk(fps=30, pairs=5, period=1.0, amplitude=25):
    t = np.arange(0, pairs * period + 0.7, 1 / fps)
    signals = {}
    for side, offset in (('left', 0.2), ('right', 0.2 + period / 2)):
        y = np.full(len(t), 5.0)
        for i in range(pairs):
            start = offset + i * period
            phase = np.clip((t - start) / (0.45 * period), 0, 1)
            y += amplitude * np.sin(np.pi * phase) ** 2
        signals[side + '_knee'] = y
        signals[side + '_hip'] = y / 2
    return t, signals


class StepEventTests(unittest.TestCase):
    def test_missed_opposite_step_does_not_shift_later_pairs(self):
        left = [(0.0, .4), (1.0, 1.4), (2.0, 2.4)]
        right = [(1.5, 1.9), (2.5, 2.9)]
        for first, second, missing_side in ((left, right, 'left'), (right, left, 'right')):
            audit = {}
            paired = pair_step_intervals(first, second, diagnostics=audit)
            self.assertEqual(len(paired), 2)
            self.assertEqual(paired[0], (first[-2], second[-2]))
            self.assertEqual(audit['unmatchedSteps'], [
                {'side': missing_side, 'start': 0., 'end': .4, 'reason': 'missing_opposite_step'},
            ])

    def test_simultaneous_events_are_both_unmatched_not_shifted(self):
        audit = {}
        paired = pair_step_intervals([(0., .4), (1., 1.4)],
                                     [(0.05, .45), (1.5, 1.9)], diagnostics=audit)
        self.assertEqual(paired, [((1., 1.4), (1.5, 1.9))])
        self.assertEqual([s['reason'] for s in audit['unmatchedSteps']],
                         ['ambiguous_simultaneous_steps'] * 2)

    def test_timeout_and_duplicate_events_cannot_create_extra_pair(self):
        audit = {}
        paired = pair_step_intervals([(0., .4), (4., 4.4), (4., 4.4)],
                                     [(3., 3.4)], diagnostics=audit)
        self.assertEqual(paired, [((4., 4.4), (3., 3.4))])
        self.assertEqual(audit['unmatchedSteps'][0]['reason'], 'opposite_step_timeout')

    def test_missing_camera_step_keeps_raw_interval_and_correct_pair(self):
        t, signals = walk(pairs=3)
        signals['right_knee'][t < 1.3] = 5.
        audit = {}
        cycles = build_camera_gait_cycles(t, signals, window_size=0, progress=audit)
        self.assertEqual(len(cycles), 2)
        self.assertGreater(cycles[0]['left']['start'], 1.)
        self.assertEqual(audit['unmatchedStepCounts']['left'], 1)
        self.assertEqual(audit['unmatchedSteps'][0]['reason'], 'missing_opposite_step')

    def test_all_pairs_option_is_not_truncated_to_seven(self):
        t, signals = walk(pairs=12)
        cycles = build_camera_gait_cycles(t, signals, window_size=0)
        self.assertEqual(len(cycles), 12)
        analysis = analyze_gait_cycles(cycles, window_size=0)
        self.assertEqual(analysis['cycleCount'], 12)
        self.assertEqual(analysis['metrics']['knee']['left']['cycles'], 12)

    def test_five_pairs_at_15_and_30_fps_without_extra_step(self):
        for fps in (15, 30):
            t, signals = walk(fps)
            cycles = build_camera_gait_cycles(t, signals, window_size=50)
            self.assertEqual(len(cycles), 5)
            for expected in range(1, 6):
                end = expected + 0.3
                mask = t <= end
                prefix = build_camera_gait_cycles(t[mask], {k:v[mask] for k,v in signals.items()}, window_size=50)
                self.assertEqual(len(prefix), expected)
                self.assertEqual(prefix[-1]['right']['end'], cycles[expected-1]['right']['end'])

    def test_fast_shallow_steps_and_unequal_amplitudes_are_kept(self):
        t, signals = walk(30, period=0.65, amplitude=6)
        signals['right_knee'] *= 2.7
        cycles = build_camera_gait_cycles(t, signals, window_size=50)
        self.assertEqual(len(cycles), 5)

    def test_one_leg_never_completes_a_pair(self):
        t, signals = walk()
        signals['right_knee'] = np.full(len(t), 5.)
        self.assertEqual(build_camera_gait_cycles(t, signals, window_size=50), [])

    def test_foot_motion_can_detect_step_without_knee_excursion(self):
        t, signals = walk()
        for side in ('left', 'right'):
            wave = (signals[side+'_knee'] - 5) / 25
            signals[side+'_foot_lift'] = wave * .055
            signals[side+'_ankle_reach'] = wave * .12
            signals[side+'_knee'] = np.full(len(t), 5.)
        cycles = build_camera_gait_cycles(t, signals, window_size=50)
        self.assertEqual(len(cycles), 5)

    def test_stationary_noise_and_single_frame_spikes_are_not_steps(self):
        t = np.arange(0, 10, 1/30)
        rng = np.random.default_rng(7)
        y = 5 + rng.normal(0, .45, len(t))
        self.assertEqual(camera_step_intervals(t, y), [])
        y[:] = 5
        y[20] = 70
        self.assertEqual(camera_step_intervals(t, y), [])

    def test_missing_data_does_not_complete_a_step(self):
        t = np.arange(0, 2, 1/30)
        y = np.full(len(t), 5.)
        y[10:20] = 30
        y[20:45] = np.nan
        self.assertEqual(camera_step_intervals(t, y), [])

    def test_raw_peaks_and_corners_are_not_shaped_or_smoothed(self):
        t = np.linspace(0, 1, 101)
        y = np.full(101, 5.)
        y[31], y[70] = 61., 25.
        curve = _normalized_interval(t, y, 0, 1)
        np.testing.assert_allclose(curve, y)
        self.assertEqual(np.argmax(curve), 31)
        fsr = _normalize(y, timestamps=t)
        np.testing.assert_allclose(fsr, y)

    def test_force_resampling_uses_actual_packet_time(self):
        curve = _normalize([0., 100., 0.], timestamps=[0., .1, 1.])
        self.assertEqual(np.argmax(curve), 10)

    def test_one_fsr_pair_recovers_camera_timing_without_second_pair(self):
        t = np.arange(0, 1.7, 1/30)
        signals = {f'{side}_{joint}': np.full(len(t), 5.)
                   for side in ('left', 'right') for joint in ('knee', 'hip')}
        contacts = [{'side':'left','start':.2,'end':.6},
                    {'side':'right','start':.7,'end':1.1}]
        p = {}
        cycles = build_synchronized_gait_cycles(t, signals, [], fsr_contacts=contacts, window_size=7, progress=p)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(p['fsrConfirmedSteps'], 2)
        self.assertEqual(cycles[0]['left']['start'], .2)
        self.assertTrue(cycles[0]['right']['fsrTiming']['recovered'])

    def test_consumed_steps_are_not_reused_when_fsr_connects(self):
        t, signals = walk()
        cycles = build_synchronized_gait_cycles(t, signals, [], window_size=50)
        consumed = {side:cycles[-1][side]['end'] for side in ('left','right')}
        contacts = [{'side':s,'start':cycles[-1][s]['start'],'end':cycles[-1][s]['end']} for s in ('left','right')]
        again = build_synchronized_gait_cycles(t, signals, [], fsr_contacts=contacts,
                                              consumed_until=consumed, window_size=50)
        self.assertEqual(again, [])

    def test_completed_contact_available_before_toe_off(self):
        pipeline = FsrStepPipeline()
        regions = lambda f: {'total':f, 'heel':f*.4, 'midfoot':f*.3, 'forefoot':f*.3}
        for i in range(10):
            pipeline.add_sample('left', i*.02, regions(0))
        for i in range(10, 20):
            pipeline.add_sample('left', i*.02, regions(120))
        self.assertEqual(len(pipeline.contact_events()), 1)
        self.assertEqual(pipeline.contact_events()[0]['end'], .2)
        self.assertEqual(pipeline.all_pairs(), [])

    def test_raw_sample_peak_not_resampled_peak_used_for_statistics(self):
        t, signals = walk()
        cycle = build_camera_gait_cycles(t, signals, window_size=50)[0]
        cycle['left']['rawSamples']['knee'][3]['value'] = 67.1234
        result = analyze_gait_cycles([cycle], window_size=5)
        self.assertEqual(result['statistics']['knee']['left']['peak']['mean'], 67.1234)
        self.assertEqual(result['curveProcessing']['smoothing'], 'none')


if __name__ == '__main__':
    unittest.main()
