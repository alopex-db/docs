"""Tiny fake frames and observers only; no performance measurement."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dataframe_phases_v0816 as workload
from test_dataframe_phases_v0816 import FakeOperations


class ObservationTest(unittest.TestCase):
    def test_callbacks_are_outside_timer_and_before_raw_and_validation(self):
        for case in workload.CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                raw = Path(directory) / 'raw.ndjson'
                events = []

                class Observer:
                    def begin(self, index): events.append('begin')
                    def finish(self, index):
                        assert raw.read_bytes() == b''
                        events.append('finish')
                        return {'index':index, 'observed_bytes':1}

                class Operations(FakeOperations):
                    def snapshot(self, *args, **kwargs):
                        events.append('snapshot')
                        return super().snapshot(*args, **kwargs)

                def clock():
                    events.append('timer')
                    return float(events.count('timer'))

                with patch.object(workload, 'Operations', Operations), patch.object(workload.time, 'perf_counter', side_effect=clock):
                    workload.run('alopex', case, raw, rows=2, warmups=0, runs=1, observer=Observer())
                first, last = [i for i, event in enumerate(events) if event == 'timer']
                self.assertEqual(events[first-1], 'begin')
                self.assertEqual(events[last+1], 'finish')
                if case != 'complete':
                    self.assertGreater(events.index('snapshot'), events.index('finish'))
                else:
                    self.assertLess(first, events.index('snapshot'))
                    self.assertLess(events.index('snapshot'), last)
                record = json.loads(raw.read_text())
                self.assertEqual(record['seconds'], 1)
                self.assertEqual(record['resources'], {'index':0, 'observed_bytes':1})

    def test_warmups_are_observed_and_measurement_indexes_stay_unchanged(self):
        events = []

        class Observer:
            def begin(self, index): events.append(('begin',index))
            def finish(self, index):
                events.append(('finish',index))
                return {'observation_index':index}

        with tempfile.TemporaryDirectory() as directory, patch.object(workload, 'Operations', FakeOperations):
            raw = Path(directory) / 'raw.ndjson'
            workload.run('alopex', 'compute', raw, rows=2, warmups=1, runs=2, observer=Observer())
            records = [json.loads(line) for line in raw.read_text().splitlines()]
        self.assertEqual(events, [(event,index) for index in range(3) for event in ('begin','finish')])
        self.assertEqual([r['index'] for r in records], [0,1])
        self.assertEqual([r['resources']['observation_index'] for r in records], [1,2])

    def test_failed_missing_or_invalid_observation_never_writes_sample(self):
        for failure in ('begin','finish','empty','nonfinite'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                raw = Path(directory) / 'raw.ndjson'

                class Observer:
                    def begin(self, index):
                        if failure == 'begin': raise RuntimeError('unavailable')
                    def finish(self, index):
                        if failure == 'finish': raise RuntimeError('unavailable')
                        return {} if failure == 'empty' else {'counter':float('nan')}

                with patch.object(workload, 'Operations', FakeOperations), self.assertRaises((RuntimeError,ValueError)):
                    workload.run('alopex', 'compute', raw, rows=2, warmups=0, runs=1, observer=Observer())
                self.assertEqual(raw.read_bytes(), b'')

    def test_operation_failure_does_not_finish_observation(self):
        events = []

        class Observer:
            def begin(self, index): events.append('begin')
            def finish(self, index): events.append('finish'); return {'counter':1}

        class Operations(FakeOperations):
            def compute(self, frame): raise RuntimeError('operation failed')

        with tempfile.TemporaryDirectory() as directory, patch.object(workload, 'Operations', Operations):
            raw = Path(directory) / 'raw.ndjson'
            with self.assertRaisesRegex(RuntimeError, 'operation failed'):
                workload.run('alopex', 'compute', raw, rows=2, warmups=0, runs=1, observer=Observer())
            self.assertEqual(raw.read_bytes(), b'')
        self.assertEqual(events, ['begin'])

    def test_default_raw_format_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(workload, 'Operations', FakeOperations):
            raw = Path(directory) / 'raw.ndjson'
            workload.run('alopex', 'construct', raw, rows=2, warmups=0, runs=1)
            self.assertEqual(set(json.loads(raw.read_text())), {'phase','index','seconds'})


if __name__ == '__main__':
    unittest.main()
