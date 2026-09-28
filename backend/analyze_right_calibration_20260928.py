"""Reproduce the provisional profile from explicitly reviewed load windows.

Run from repository root. Original log is never modified. Windows are seconds
from this capture only; they are NOT a general-purpose automatic load detector.
"""
import hashlib
import json
from pathlib import Path
from statistics import median

from fsr_force import adc_to_newton


# Each row: four (1468g window, stacked-load window) pairs. Excludes ramps,
# unloading and the confirmed extra-weight interval. Null needs recollection.
WINDOWS = [
    [(10,14,16,18), None, (41,46,49,52), (60,63,64,66)],
    [(78,82,85,88), (95,100,104,108), (116,120,123,126), None],
    [(166,170,173,176), (183,187,192,196), (206,213,217,223), (235,239,251,257)],
    [(268,275,280,284), None, None, (409,414,420,423)],
    [(431,435,440,444), (453,457,460,463), (474,480,484,488), (497,501,507,511)],
    [(520,524,531,536), (546,552,557,562), (569,574,580,584), (598,603,608,612)],
    [(620,624,629,632), (641,646,655,660), (670,677,684,689), (699,708,713,718)],
    [(738,746,751,757), (766,771,777,781), (790,799,811,819), (832,838,842,848)],
    [(859,865,869,876), (884,889,892,897), (909,920,928,932), (942,949,955,959)],
    [(967,972,976,981), (989,993,1000,1006), None, None],
    [(1107,1114,1120,1125), (1137,1144,1149,1153), (1161,1170,1175,1179), (1188,1196,1205,1212)],
    [(1222,1228,1236,1243), (1254,1263,1273,1279), (1291,1297,1305,1309), (1319,1326,1330,1335)],
]


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'fsr_logs' / 'chân phải log.jsonl'
    samples = []
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for line in handle:
            digest.update(line)
            record = json.loads(line)
            if record.get('type') == 'fsr_sample' and record.get('side') == 'right':
                raw = record['filtered_raw_values']
                samples.append((record['elapsed'], [adc_to_newton(x) for row in raw for x in row]))
    if digest.hexdigest() != 'd2439c9e64b5fb95dbf7ba319381c6ec7e385dc7ccf58dccaa76373fd924c1a6':
        raise ValueError('Source log changed: these reviewed windows must not be reused on another capture')
    def segment(k, start, end):
        return [v[k] for t, v in samples if start <= t < end]
    cells, audit = [], []
    target = 1.468 * 9.80665
    nominal_stacked = target + 0.3333 * 9.80665
    for k in range(48):
        baseline = median(segment(k, 1, 6))
        w = WINDOWS[k // 4][k % 4]
        entry = {'row': k // 4 + 1, 'column': k % 4 + 1, 'baseline_n': baseline, 'windows_s': w}
        cell = None
        if w is None:
            entry['reason'] = 'Load stages ambiguous / extra weight / repositioning'
        else:
            low, high = segment(k, *w[:2]), segment(k, *w[2:])
            observed = median(low)
            gain = target / (observed - baseline)
            corrected_high = (median(high) - baseline) * gain
            spread = (sorted(low)[int(.9*len(low))] - sorted(low)[int(.1*len(low))]) / (observed-baseline)
            mismatch = corrected_high / nominal_stacked - 1
            entry.update(observed_n=observed, gain=gain, stacked_corrected_n=corrected_high,
                         nominal_stacked_error=mismatch, spread_fraction=spread, samples=len(low))
            # Screening heuristic, NOT a manufacturer specification or validation.
            if spread > .10 or abs(mismatch) > .15:
                entry['reason'] = 'Unstable first plateau or inconsistent stacked-load response (>15% nominal)'
            else:
                cell = {'baseline_n': baseline, 'gain': gain}
                entry['reason'] = 'Provisional one-point fit; independent retest required'
        cells.append(cell)
        entry['enabled'] = cell is not None
        audit.append(entry)
    profile = {'version': 1, 'id': 'right-20260928-provisional', 'side': 'right',
               'status': 'provisional_single_point_not_validated', 'source_sha256': digest.hexdigest(),
               'target_n': target, 'baseline_window_s': [1, 6],
               'warning': 'Only original right specimen and original mounting. Null cells remain legacy. Not shoe tare.',
               'cells': [cells[i:i+4] for i in range(0,48,4)], 'audit': audit}
    output = root / 'calibration' / 'right-20260928-provisional.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(profile, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for e in audit:
        print(f"H{e['row']}C{e['column']} {'TRIAL' if e['enabled'] else 'RETEST'} "
              f"gain={e.get('gain',0):.3f} stacked={e.get('stacked_corrected_n',0):.2f}N")
    print('Provisional cells:', sum(c is not None for c in cells), '/48')


if __name__ == '__main__':
    main()
