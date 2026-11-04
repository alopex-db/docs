import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from sql_resources import ENV, OperationResources, _server, _stat, server_delta


def counters(**updates):
    value = dict(start_ticks=123, user_ticks=10, system_ticks=20,
                 reaped_user_ticks=0, reaped_system_ticks=0,
                 rss_bytes=4096, lifetime_hwm_bytes=8192,
                 read_bytes=1024, write_bytes=2048, cancelled_write_bytes=0)
    return dict(value, **updates)


class ResourceTests(unittest.TestCase):
    def test_per_process_cpu_io_and_memory_keep_their_units_and_scope(self):
        before = {1: counters(), 2: counters(start_ticks=456)}
        after = {1: counters(user_ticks=12, system_ticks=21, write_bytes=6144,
                             rss_bytes=2048, lifetime_hwm_bytes=8192),
                 2: counters(start_ticks=456, read_bytes=5120)}
        rows = server_delta(before, after, 100)
        self.assertEqual(rows[0]['user_cpu_seconds'], .02)
        self.assertEqual(rows[0]['system_cpu_seconds'], .01)
        self.assertEqual(rows[0]['write_bytes'], 4096)
        self.assertEqual(rows[1]['read_bytes'], 4096)
        self.assertEqual(rows[0]['rss_after_bytes'], 2048)
        self.assertEqual(rows[0]['lifetime_hwm_after_bytes'], 8192)
        self.assertEqual(len(rows), 2)  # Shared RSS is not summed.

    def test_process_replacement_membership_and_reaped_children_fail_closed(self):
        before = {1: counters()}
        for after in ({}, {1: counters(start_ticks=124)},
                      {1: counters(), 2: counters()},
                      {1: counters(reaped_user_ticks=1)},
                      {1: counters(user_ticks=9)}):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                server_delta(before, after, 100)

    def test_server_observation_is_outside_client_usage_window(self):
        events = []
        calls = 0
        def server(*_):
            events.append('server')
            return {1: counters()}
        def usage():
            nonlocal calls
            calls += 1
            events.append('client')
            return SimpleNamespace(ru_utime=calls, ru_stime=calls / 2,
                                   ru_inblock=calls * 2, ru_oublock=calls * 3,
                                   ru_maxrss=10)
        meter = OperationResources(1, 123, server_reader=server, usage_reader=usage)
        before = meter.begin()
        events.append('operation')
        result = meter.end(before)
        events.append('raw write')
        self.assertEqual(events, ['server', 'client', 'operation', 'client', 'server', 'raw write'])
        self.assertEqual(result['client']['user_cpu_seconds'], 1)
        self.assertEqual(result['client']['input_blocks'], 2)
        self.assertEqual(result['client']['output_blocks'], 3)
        self.assertEqual(result['client']['lifetime_hwm_after_bytes'], 10240)

    def test_missing_server_counters_are_not_zero_cost(self):
        def missing(*_):
            raise PermissionError('counter unavailable')
        meter = OperationResources(1, 123, server_reader=missing)
        with self.assertRaises(PermissionError):
            meter.begin()

    def test_disabled_observer_needs_no_server_or_manifest(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(OperationResources.from_environment('postgresql'))

    def test_postgresql_connection_must_belong_to_observed_server(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'servers.json'
            path.write_text(json.dumps({'schema': 'alopex.sql-resource-servers/v1',
                                        'servers': {'postgresql': {'pid': 1, 'start_ticks': 123}}}))
            with patch.dict(os.environ, {ENV: str(path)}), patch('sql_resources.sys.platform', 'linux'):
                with patch.object(OperationResources, '__init__', return_value=None):
                    with patch.object(OperationResources, 'server_reader', create=True,
                                      return_value={1: counters(), 2: counters()}):
                        with self.assertRaises(RuntimeError):
                            OperationResources.from_environment('postgresql', 3)
                        self.assertIsNotNone(OperationResources.from_environment('postgresql', 2))

    @unittest.skipUnless(Path('/proc/self/io').exists(), 'Host does not expose Linux process I/O counters')
    def test_real_process_counters_have_stable_identity(self):
        pid = os.getpid()
        start = _stat(Path('/proc/self/stat'))['start_ticks']
        before = _server(pid, start)
        after = _server(pid, start)
        rows = server_delta(before, after, os.sysconf('SC_CLK_TCK'))
        self.assertEqual(rows[0]['pid'], pid)
        self.assertGreater(rows[0]['rss_after_bytes'], 0)
        self.assertGreaterEqual(rows[0]['user_cpu_seconds'], 0)
        with self.assertRaises(RuntimeError):
            _server(pid, start + 1)

    def test_proc_parser_preserves_units_and_rejects_missing_io(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / '17'
            (proc / 'task' / '17').mkdir(parents=True)
            fields = ['S'] + ['0'] * 21
            fields[11:15] = ['10', '20', '0', '0']
            fields[19] = '123'
            (proc / 'stat').write_text('17 (name with ) spaces) ' + ' '.join(fields))
            (proc / 'status').write_text('VmRSS:\t4 kB\nVmHWM:\t8 kB\n')
            (proc / 'task' / '17' / 'children').write_text('')
            with self.assertRaisesRegex(RuntimeError, 'I/O counters unavailable'):
                _server(17, 123, root)
            (proc / 'io').write_text('read_bytes: 1024\nwrite_bytes: 2048\ncancelled_write_bytes: 0\n')
            self.assertEqual(_server(17, 123, root), {17: counters()})


class HarnessBoundaryTests(unittest.TestCase):
    def test_write_resources_exclude_warmups_and_raw_writes(self):
        import write_kv_sql as workload
        from test_write_kv_sql import FakeClient
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'raw.ndjson'
            state, observed = {}, []
            class Observer:
                def begin(self):
                    self.before_commits = state['commits']
                    self.before_raw = raw.read_bytes()
                    return 'token'
                def end(self, token):
                    self_test.assertEqual(token, 'token')
                    self_test.assertEqual(state['commits'], self.before_commits + 1)
                    self_test.assertEqual(raw.read_bytes(), self.before_raw)
                    observed.append(1)
                    return {'status': 'observed', 'client': {'output_blocks': 0}}
            self_test = self
            with patch.object(workload, '_connect', side_effect=lambda _: FakeClient(root / 'db', state)), \
                 patch.object(OperationResources, 'from_environment', return_value=Observer()):
                result = workload.run('alopex-server', 'insert-commit', root, raw,
                                      n=2, warmups=1, runs=2)
            self.assertEqual(len(observed), 2)
            self.assertEqual(result['samples'], 2)
            rows = [json.loads(line) for line in raw.read_text().splitlines()]
            self.assertTrue(all(row['resources']['status'] == 'observed' for row in rows))

    def test_resource_failure_retains_latency_and_fails_cell_in_both_runners(self):
        import write_kv_sql as workload
        from test_write_kv_sql import FakeClient
        from test_isolated_sql import module as isolated
        class Observer:
            def begin(self):
                return None
            def end(self, _):
                raise PermissionError('resource counter became unavailable')
        class Remote:
            def execute_sql(self, _):
                return None
            def close(self):
                pass
        alopex = SimpleNamespace(RemoteDatabase=Remote, connect=lambda *a, **k: Remote())
        for runner in ('write', 'isolated'):
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = root / 'raw.ndjson'
                with patch.object(OperationResources, 'from_environment', return_value=Observer()), \
                     patch.object(workload, '_connect', side_effect=lambda _: FakeClient(root / 'db', {})), \
                     patch.dict('sys.modules', {'alopex': alopex}), \
                     patch.dict(os.environ, {'ALOPEX_PERF_SERVER_URL': 'http://localhost'}):
                    with self.assertRaises(PermissionError):
                        if runner == 'write':
                            workload.run('alopex-server', 'insert-commit', root, raw,
                                         n=2, warmups=0, runs=1)
                        else:
                            isolated.measure(None, 'alopex-server', 'drop-sequence', raw)
                rows = [json.loads(line) for line in raw.read_text().splitlines()]
                self.assertEqual(len(rows), 1)
                self.assertGreaterEqual(rows[0]['seconds'], 0)
                self.assertEqual(rows[0]['resources']['status'], 'failed')
                self.assertIn('counter became unavailable', rows[0]['resources']['error'])


if __name__ == '__main__':
    unittest.main()
