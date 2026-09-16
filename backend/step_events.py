"""Causal camera step events: raw cues in, one completed movement out.

No curve filtering, symmetric look-ahead, peak relocation or gait-template fit.
Debounce confirms events only; it never modifies the measured angle samples.
"""
from collections import deque
import math


def camera_step_intervals(timestamps, knee_angles, foot_lift=None, ankle_reach=None,
                          *, min_step_seconds=0.18, max_step_seconds=2.5,
                          min_flexion_excursion=4.0, progress=None):
    times = list(timestamps)
    knee = list(knee_angles)
    foot = list(foot_lift) if foot_lift is not None else []
    reach = list(ankle_reach) if ankle_reach is not None else []

    def value(values, index):
        try:
            v = float(values[index])
            return v if math.isfinite(v) else None
        except (IndexError, TypeError, ValueError):
            return None

    idle = deque()
    active = None
    intervals = []
    last_time = None
    latest = None
    observed = []
    required = max(3.0, float(min_flexion_excursion))
    for i, raw_time in enumerate(times):
        try:
            t = float(raw_time)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(t) or (last_time is not None and t <= last_time):
            continue
        k, f, r = value(knee, i), value(foot, i), value(reach, i)
        if k is None and (f is None or r is None):
            continue
        if last_time is not None and t - last_time > 0.30:
            active = None
            idle.clear()
        last_time = t
        if k is not None:
            observed.append(k)
        current = (t, k, f, r)
        if active is None:
            idle.append(current)
            while len(idle) > 1 and t - idle[0][0] > 0.45:
                idle.popleft()
            base_k = min((p for p in idle if p[1] is not None),
                         key=lambda p: (p[1], -p[0]), default=None)
            base_f = min((p for p in idle if p[2] is not None),
                         key=lambda p: (p[2], -p[0]), default=None)
            knee_rise = k - base_k[1] if k is not None and base_k else 0.0
            foot_rise = f - base_f[2] if f is not None and base_f else 0.0
            reach_change = abs(r - base_f[3]) if r is not None and base_f and base_f[3] is not None else 0.0
            knee_on = knee_rise >= required
            foot_on = foot_rise >= 0.012 and reach_change >= 0.025
            if not (knee_on or foot_on):
                continue
            base = base_f if foot_on else base_k
            active = {'start': base[0], 'base_k': base[1], 'base_f': base[2],
                      'peak_k': k, 'peak_f': f, 'frames': 1, 'foot': foot_on,
                      'return_at': None, 'return_frames': 0, 'supported_frames': 1}
            idle.clear()
            continue

        active['frames'] += 1
        if k is not None:
            active['peak_k'] = max(k, active['peak_k'] if active['peak_k'] is not None else k)
        if f is not None:
            active['peak_f'] = max(f, active['peak_f'] if active['peak_f'] is not None else f)
        duration = t - active['start']
        if duration > max_step_seconds:
            active = None
            idle.append(current)
            continue
        knee_return = (k is not None and active['base_k'] is not None
                       and active['peak_k'] - active['base_k'] >= required
                       and k <= active['base_k'] + max(1.0, 0.15 * (active['peak_k'] - active['base_k'])))
        foot_return = (active['foot'] and f is not None and active['base_f'] is not None
                       and f <= active['base_f'] + 0.004)
        returned = foot_return if active['foot'] else knee_return
        supported = (
            f is not None and active['base_f'] is not None and f - active['base_f'] >= 0.012
            if active['foot'] else
            k is not None and active['base_k'] is not None and k - active['base_k'] >= required
        )
        if supported:
            active['supported_frames'] += 1
        if returned and active['supported_frames'] < 2:
            active = None
            idle.append(current)
            continue
        if returned and duration >= min_step_seconds and active['frames'] >= 3:
            if active['return_at'] is None:
                active['return_at'] = t
            active['return_frames'] += 1
            if active['return_frames'] >= 2:
                intervals.append((active['start'], active['return_at']))
                latest = active['return_at']
                active = None
                idle.append(current)
        else:
            active['return_at'] = None
            active['return_frames'] = 0
    if progress is not None:
        progress.update({'stepEvents': len(intervals), 'extensionEvents': len(intervals),
                         'completedCycles': len(intervals), 'latestEventAt': latest,
                         'activeStep': active is not None,
                         'observedExcursionDeg': max(observed) - min(observed) if observed else 0.0,
                         'requiredExcursionDeg': required,
                         'method': 'causal_raw_knee_or_foot_return'})
    return intervals


def pair_step_intervals(left_intervals, right_intervals, *, diagnostics=None,
                        max_gap_seconds=2.5, min_gap_seconds=0.12):
    """Pair adjacent opposite-side events, never across a repeated same side.

    L1, L2, R2 leaves L1 incomplete and pairs L2/R2. Ambiguous simultaneous
    detections invalidate BOTH events, rather than leaving one to steal the
    next step. Timing is an observed event, not proof of anatomical identity.
    Unmatched intervals remain available for audit, not used in pair statistics.
    """
    events = sorted(set((float(end), side, (float(start), float(end)))
                    for side, intervals in (('left', left_intervals), ('right', right_intervals))
                    for start, end in intervals
                    if math.isfinite(start) and math.isfinite(end) and end > start))
    pending = None
    pairs = []
    unmatched = []

    def retain(event, reason):
        _, side, (start, end) = event
        unmatched.append({'side': side, 'start': start, 'end': end, 'reason': reason})

    for end, side, interval in events:
        current = (end, side, interval)
        if pending is None:
            pending = current
            continue
        previous_end, previous_side, previous_interval = pending
        if side == previous_side or end - previous_end > max_gap_seconds:
            retain(pending, 'missing_opposite_step' if side == previous_side else 'opposite_step_timeout')
            pending = current
        elif end - previous_end < min_gap_seconds:
            retain(pending, 'ambiguous_simultaneous_steps')
            retain(current, 'ambiguous_simultaneous_steps')
            pending = None
        else:
            pairs.append((interval, previous_interval) if side == 'left' else (previous_interval, interval))
            pending = None
    if pending is not None:
        retain(pending, 'waiting_for_opposite_step')
    if diagnostics is not None:
        diagnostics.update({
            'pairingMethod': 'adjacent_opposite_events_no_skipped_side',
            'unmatchedSteps': unmatched,
            'unmatchedStepCounts': {side: sum(item['side'] == side for item in unmatched)
                                    for side in ('left', 'right')},
        })
    return pairs
