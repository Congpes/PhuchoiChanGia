"""Explicit synthetic FSR, never a measured scan or calibration reference."""
import math
import numpy as np
from scipy.signal import find_peaks


def build_simulation(manifest):
    fps = manifest['cameraPreview']['fps']
    candidates = []
    for side in ('left', 'right'):
        values = manifest['cameraPreview']['signals'][side + 'Knee']['filtered']
        # Missing camera observations must never create peak candidates.
        valid = np.array([v is not None for v in values])
        a = np.array([v if v is not None else 0 for v in values])
        peaks, _ = find_peaks(a, prominence=15, distance=int(.7 * fps))
        for i in peaks:
            if valid[max(0, i-3):i+4].all():
                candidates.append({'side': side, 'time': round(i/fps, 4),
                                   'source': 'camera_knee_peak_estimate'})
    anchors = []
    for item in sorted(candidates, key=lambda x: x['time']):
        if not anchors or (item['side'] != anchors[-1]['side'] and
                           .3 <= item['time']-anchors[-1]['time'] <= .9):
            anchors.append(item)
    if len(anchors) < 3:
        raise ValueError('Insufficient alternating camera knee peaks')
    times = np.array([a['time'] for a in anchors])
    body_weight = 80 * 9.80665
    frames = []
    for t in np.arange(0, manifest['durationSec'], 1/60):
        # Anchor means knee flexion maximum, not a measured heel strike.
        phase = np.interp(t, times, np.arange(len(times))*math.pi)
        active = times[0] <= t <= times[-1]
        blend = min(1., max(0., (t-times[0])/.35), max(0., (times[-1]-t)/.35)) if active else 0.
        blend = blend*blend*(3-2*blend)
        # Keep the illustrative insole load near the two-leg standing share.
        # The video has no force plate, so avoid implying a full-body-weight
        # single-leg peak from knee motion alone.
        share = .5 - .10*math.cos(phase) * (1 if anchors[0]['side']=='left' else -1)
        share = .5 + blend*(share-.5)
        total = body_weight*(1+.04*blend*math.cos(2*phase))
        camera_index = min(int(t * fps), len(manifest['cameraPreview']['signals']['leftKnee']['raw']) - 1)
        supported = bool(active and all(
            manifest['cameraPreview']['signals'][side + 'Knee']['raw'][camera_index] is not None
            for side in ('left', 'right')))
        frame = {'time': round(float(t), 4), 'supportedByCamera': supported}
        if not supported:
            frame.update(left=None, right=None)
            frames.append(frame)
            continue
        for side, fraction in [('left', share), ('right', 1-share)]:
            force = total*fraction
            progress = (phase/math.pi/2 + (0 if side=='left' else .5)) % 1
            center = 5.5 + 3.5*math.cos(2*math.pi*progress)
            weights = np.array([[math.exp(-((r-center)/2.8)**2-((c-1.5)/1.3)**2)
                                 for c in range(4)] for r in range(12)])
            matrix = weights/weights.sum()*force
            frame[side] = {'total': round(float(force), 4), 'forceValues': matrix.round(6).tolist()}
        frames.append(frame)
    pairs = []
    signals = manifest['cameraPreview']['signals']
    for i in range(0, len(anchors)-3, 2):
        pair = {'pairIndex': len(pairs)+1, 'source': 'camera_knee_peak_estimate',
                'startTime': anchors[i]['time'], 'endTime': anchors[i+3]['time']}
        for j in (i, i+1):
            side = anchors[j]['side']
            start, end = anchors[j]['time'], anchors[j+2]['time']
            samples = [f for f in frames if start <= f['time'] <= end]
            curves = {}
            if samples:
                for region, bounds in {'total': (0,12), 'heel': (9,12), 'midfoot': (4,9), 'forefoot': (0,4)}.items():
                    values = [sum(sum(row) for row in f[side]['forceValues'][bounds[0]:bounds[1]]) if f['supportedByCamera'] else np.nan for f in samples]
                    interpolated = np.interp(np.linspace(start,end,101), [f['time'] for f in samples], values)
                    curves[region] = [float(v) if np.isfinite(v) else None for v in interpolated]
            for metric in ('knee', 'hip'):
                raw = signals[side + metric.title()]['raw']
                first, last = int(math.ceil(start*fps)), int(math.floor(end*fps))
                values = raw[first:last+1]
                if len(values) >= 5:
                    interpolated = np.interp(np.linspace(start,end,101), np.arange(first,last+1)/fps, [v if v is not None else np.nan for v in values])
                    curves[metric] = [float(v) if np.isfinite(v) else None for v in interpolated]
            phase = np.linspace(0, 1, 101)
            # Standalone teaching profiles: assumptions, not video measurements.
            phase_total = body_weight * np.sin(np.pi * phase) ** .65 * (1 + .12*np.cos(4*np.pi*phase))
            weights = np.stack([np.exp(-((phase-.16)/.22)**2),
                                np.exp(-((phase-.48)/.28)**2),
                                np.exp(-((phase-.8)/.22)**2)])
            weights /= weights.sum(axis=0)
            phase_curves = {region: (phase_total*weights[k]).tolist()
                            for k, region in enumerate(('heel','midfoot','forefoot'))}
            pair[side] = {'startTime': start, 'endTime': end, 'curves': curves,
                          'illustrativePhases': phase_curves,
                          'footClearance': {'peakCm': 8.0, 'mtcCm': 1.5, 'source': 'illustrative_assumption_not_measured'},
                          'supplementalProvenance': 'Phase timing, force profile and foot clearance are illustrative assumptions, not extracted from video.'}
        pairs.append(pair)
    return {'kind': 'simulation', 'label': 'FSR · 80 kg',
            'weightKg': 80, 'unit': 'N_simulated', 'durationSec': manifest['durationSec'],
            'cameraAnglesModified': False, 'synchronizationStatus': 'unverified',
            'method': 'Alternating camera knee-flexion peaks guide illustrative load transfer; not measured contact events. Missing camera observations and times outside anchors are unavailable. Magnitude and plantar distribution are model assumptions, not inferred measurements.',
            'pairs': pairs, 'cameraSignals': signals, 'cameraFps': fps,
            'cameraStepEstimates': anchors, 'frames': frames}
