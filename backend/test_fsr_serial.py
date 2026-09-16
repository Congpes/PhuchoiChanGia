import os
import unittest
from unittest.mock import patch

from fsr_serial import (
    FsrSerialFrameParser,
    read_fsr_serial_chunk,
    serial_retry_delay,
    configured_serial_ports,
    hardware_values_to_matrix,
)


class _Port:
    def __init__(self, device, description, hwid):
        self.device = device
        self.description = description
        self.hwid = hwid


class FsrSerialTests(unittest.TestCase):
    def test_timeout_in_middle_of_number_does_not_create_extra_values(self):
        parser = FsrSerialFrameParser()
        payload = ('RR ' + ' '.join(str(100 + i) for i in range(48)) + '\r\n').encode()
        frames = []
        for byte in payload:
            frames += parser.feed_bytes(bytes([byte]))
            self.assertEqual(parser.feed_bytes(b''), [])
        self.assertEqual(frames, [('left', hardware_values_to_matrix(range(100, 148), 'left'))])

    def test_multiple_lines_and_frames_in_one_read(self):
        parser = FsrSerialFrameParser()
        row = ' '.join(map(str, range(48))) + '\n'
        frames = parser.feed_bytes(('LL\r\n' + row + row).encode())
        self.assertEqual(len(frames), 2)
        self.assertTrue(all(side == 'right' for side, _ in frames))

    def test_bad_bytes_are_not_silently_removed_from_numbers(self):
        parser = FsrSerialFrameParser()
        self.assertEqual(parser.feed_bytes(b'LL 12\xff3\n'), [])
        self.assertIsNone(parser.side)
        self.assertEqual(parser.invalid_lines, 1)
        frame = b'RR ' + b' '.join([b'10'] * 48) + b'\n'
        self.assertEqual(len(parser.feed_bytes(frame)), 1)

    def test_unterminated_garbage_is_bounded_and_recovers_at_marker(self):
        parser = FsrSerialFrameParser()
        parser.feed_bytes(b'LL ' + b'1' * 10000)
        self.assertLessEqual(len(parser.pending_bytes), 8192)
        self.assertEqual(parser.feed_bytes(b'23\n'), [])
        self.assertEqual(len(parser.feed_bytes(b'LL ' + b' '.join([b'10'] * 48) + b'\n')), 1)

    def test_non_finite_values_do_not_reach_force_calculation(self):
        parser = FsrSerialFrameParser()
        self.assertEqual(parser.feed_line('RR ' + 'nan ' * 48), [])
        self.assertIsNone(parser.side)

    def test_empty_read_is_not_a_disconnect(self):
        connection = unittest.mock.Mock(in_waiting=0)
        connection.read.return_value = b''
        for _ in range(100):
            self.assertEqual(read_fsr_serial_chunk(connection), b'')
        connection.close.assert_not_called()
        connection.read.assert_called_with(1)

    def test_batch_read_is_bounded_without_purging_data(self):
        connection = unittest.mock.Mock(in_waiting=20000)
        connection.read.return_value = b'RR\n'
        self.assertEqual(read_fsr_serial_chunk(connection), b'RR\n')
        connection.read.assert_called_once_with(4096)
        connection.reset_input_buffer.assert_not_called()

    def test_actual_port_failure_propagates_for_reconnect(self):
        connection = unittest.mock.Mock(in_waiting=10)
        connection.read.side_effect = OSError('device disconnected')
        with self.assertRaises(OSError):
            read_fsr_serial_chunk(connection)

    def test_retries_are_capped_instead_of_opening_in_tight_loop(self):
        self.assertEqual([serial_retry_delay(n, 0.5, 5) for n in range(1, 8)],
                         [0.5, 1.0, 2.0, 4.0, 5, 5, 5])

    def test_four_rows_from_ll_form_one_right_frame(self):
        parser = FsrSerialFrameParser()
        values = list(range(48))
        frames = []
        frames += parser.feed_line('LL ' + ' '.join(map(str, values[:12])))
        frames += parser.feed_line(' '.join(map(str, values[12:24])))
        frames += parser.feed_line(' '.join(map(str, values[24:36])))
        frames += parser.feed_line(' '.join(map(str, values[36:])))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0], 'right')
        self.assertEqual(len(frames[0][1]), 12)
        self.assertEqual(len(frames[0][1][0]), 4)

    def test_only_left_sensor_columns_are_mirrored(self):
        values = list(range(48))
        right = hardware_values_to_matrix(values, 'right')
        left = hardware_values_to_matrix(values, 'left')
        self.assertEqual(right[0], [36.0, 24.0, 12.0, 0.0])
        self.assertEqual(left[0], [0.0, 12.0, 24.0, 36.0])

    def test_rr_marker_is_physical_left(self):
        parser = FsrSerialFrameParser()
        values = ' '.join(map(str, range(48)))
        frames = parser.feed_line(f'RR {values}')
        self.assertEqual(frames[0][0], 'left')

    def test_ll_marker_is_physical_right(self):
        parser = FsrSerialFrameParser()
        values = ' '.join(map(str, range(48)))
        frames = parser.feed_line(f'LL {values}')
        self.assertEqual(frames[0][0], 'right')

    def test_marker_persists_for_continuous_frames_on_one_port(self):
        parser = FsrSerialFrameParser()
        first = parser.feed_line('LL ' + ' '.join(map(str, range(48))))
        second = parser.feed_line(' '.join(map(str, range(48, 96))))
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0][0], 'right')

    def test_startup_fragment_is_ignored(self):
        parser = FsrSerialFrameParser()
        self.assertEqual(parser.feed_line('6'), [])
        self.assertEqual(parser.values, [])

    def test_auto_discovery_uses_bluetooth_outgoing_port(self):
        ports = [
            _Port('COM3', 'Bluetooth serial', 'LOCALMFG&0000'),
            _Port('COM4', 'Bluetooth serial', 'LOCALMFG&0002'),
        ]
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_serial_ports(ports), ['COM4'])

    def test_explicit_ports_override_discovery(self):
        with patch.dict(os.environ, {'FSR_SERIAL_PORTS': 'COM8, COM9'}):
            self.assertEqual(configured_serial_ports([]), ['COM8', 'COM9'])


if __name__ == '__main__':
    unittest.main()
