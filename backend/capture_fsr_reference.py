"""Standalone lossless-frame capture while the demo backend serial is disabled.

Creates a candidate reference, not a calibrated/validated gait result.
Touch STOP inside the output directory to finish; safety limit is 10 minutes.
"""
import json
import threading
import time
from pathlib import Path
import serial
from serial.tools import list_ports
from fsr_serial import configured_serial_ports, FsrSerialFrameParser, read_fsr_serial_chunk
from fsr_force import matrix_to_newton, matrix_total, region_totals
from measurement_smoothing import FsrMedianFilter


def run():
    root = Path(__file__).parent / 'recordings' / 'fsr_references' / time.strftime('%Y%m%d-%H%M%S')
    root.mkdir(parents=True, exist_ok=False)
    started = time.time()
    origin = time.monotonic()
    ports = configured_serial_ports(list_ports.comports())
    lock = threading.Lock()
    opening = threading.Lock()
    stop = threading.Event()
    state = {'directory': str(root), 'startedAt': started, 'status': 'recording',
             'counts': {'left': 0, 'right': 0}, 'lastReceivedAt': {}, 'totalsN': {}, 'errors': {}}
    manifest = {'kind': 'candidate_fsr_reference', 'cameraSynchronized': False,
                'instruction': 'Stand about 3 seconds, then walk 5-7 steps; actual boundaries require review',
                'leftMirroredOnly': True, 'rawPreserved': True,
                'filter': 'per-cell median 5; raw ADC retained',
                'timing': 'host receive time, not device acquisition time',
                'calibration': 'existing conversion; pending calibration verification', 'ports': ports}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    def worker(port):
        filt = FsrMedianFilter()
        with (root / ('port_' + port + '.jsonl')).open('x', encoding='utf-8', buffering=1) as stream:
            while not stop.is_set():
                try:
                    with opening:
                        connection = serial.Serial(port, 9600, timeout=.5)
                    with connection:
                        parser = FsrSerialFrameParser()
                        while not stop.is_set():
                            for side, raw in parser.feed_bytes(read_fsr_serial_chunk(connection)):
                                now = time.time()
                                elapsed = time.monotonic() - origin
                                filtered = filt.apply(side, raw, elapsed)
                                force, unit, source = matrix_to_newton(filtered, 'raw_adc')
                                sample = {'side': side, 'port': port, 'time': elapsed,
                                          'receivedAt': now, 'timestampValid': False,
                                          'rawAdcValues': raw, 'values': filtered,
                                          'forceValues': force, 'unit': unit, 'forceSource': source,
                                          'total': matrix_total(force), 'regions': region_totals(force)}
                                stream.write(json.dumps(sample) + '\n')
                                with lock:
                                    state['counts'][side] += 1
                                    state['lastReceivedAt'][side] = now
                                    state['totalsN'][side] = sample['total']
                                    state['errors'].pop(port, None)
                except Exception as exc:
                    with lock:
                        state['errors'][port] = str(exc)
                    stream.write(json.dumps({'event': 'error', 'receivedAt': time.time(), 'error': str(exc)}) + '\n')
                    stop.wait(1)
    threads = [threading.Thread(target=worker, args=(p,), daemon=True) for p in ports]
    for thread in threads:
        thread.start()
    print(str(root), flush=True)
    try:
        while time.monotonic() - origin < 600 and not (root / 'STOP').exists():
            with lock:
                (root / 'status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
            stop.wait(.5)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=3)
        state['status'] = 'stopped'
        state['stoppedAt'] = time.time()
        (root / 'status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')


if __name__ == '__main__':
    run()
