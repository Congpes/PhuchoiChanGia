import json
import unittest
from pathlib import Path
from phone_demo_simulation import build_simulation


class SimulationTests(unittest.TestCase):
    def test_provenance_conservation_and_camera_preservation(self):
        path = Path(__file__).parent / 'demo_videos/phone-02/manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        before = json.dumps(manifest)
        result = build_simulation(manifest)
        self.assertEqual(json.dumps(manifest), before)
        self.assertEqual(result['kind'], 'simulation')
        self.assertEqual(result['unit'], 'N_simulated')
        self.assertEqual(len(result['frames']), 480)
        self.assertGreaterEqual(len(result['cameraStepEstimates']), 3)
        for frame in result['frames']:
            if not frame['supportedByCamera']:
                self.assertIsNone(frame['left'])
                self.assertIsNone(frame['right'])
                continue
            total = sum(frame[s]['total'] for s in ('left', 'right'))
            self.assertTrue(720 < total < 850)
            for side in ('left', 'right'):
                matrix = frame[side]['forceValues']
                self.assertTrue(all(v >= 0 for row in matrix for v in row))
                self.assertAlmostEqual(sum(map(sum, matrix)), frame[side]['total'], places=3)
        self.assertIsNone(result['frames'][0]['left'])
        self.assertGreater(sum(f['supportedByCamera'] for f in result['frames']), 100)
        supported = [f for f in result['frames'] if f['supportedByCamera']]
        self.assertLess(max(max(f['left']['total'], f['right']['total']) for f in supported), 520)
        self.assertGreater(len(result['pairs']), 0)
        for pair in result['pairs']:
            self.assertLess(pair['startTime'], pair['endTime'])
            for side in ('left', 'right'):
                self.assertEqual(pair[side]['footClearance']['source'], 'illustrative_assumption_not_measured')
                profiles = pair[side]['illustrativePhases']
                for profile in profiles.values():
                    self.assertEqual(len(profile), 101)
                    self.assertTrue(all(v >= 0 for v in profile))
                self.assertAlmostEqual(sum(v[0] for v in profiles.values()), 0)
                for curve in pair[side]['curves'].values():
                    self.assertEqual(len(curve), 101)
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
