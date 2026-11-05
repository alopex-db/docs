"""Optional Linux SQL operation resource observations, outside latency timers.

Raw-file writes, result validation, fixture setup and connection creation must
occur outside begin/end. Memory values are boundary observations and lifetime
high-water marks, never an operation's sampled peak. Server rows remain separate
because RSS can contain shared pages. Counters cover the observed stable process
tree. Any PID/thread allocation invalidates the interval rather than silently
omitting transient processes absent from both endpoint snapshots.
"""
import json
import hashlib
import os
from pathlib import Path
import resource
import sys

ENV = "ALOPEX_PERF_SQL_RESOURCE_MANIFEST"


def _stat(path):
    fields = path.read_text().rsplit(")", 1)[1].split()
    if fields[0] == "Z":
        raise RuntimeError("Resource process exited")
    return {"start_ticks": int(fields[19]), "user_ticks": int(fields[11]),
            "system_ticks": int(fields[12]),
            "reaped_user_ticks": int(fields[13]),
            "reaped_system_ticks": int(fields[14])}


def _server(root_pid, root_start, proc=Path("/proc")):
    pending, rows = [root_pid], {}
    while pending:
        pid = pending.pop()
        if pid in rows:
            continue
        if len(rows) >= 64:
            raise RuntimeError("Server process count exceeds resource observation bound")
        base = proc / str(pid)
        before = _stat(base / "stat")
        executable = (base / "exe").stat()
        exe_identity = [executable.st_dev, executable.st_ino, executable.st_size, executable.st_mtime_ns]
        if pid == root_pid and before["start_ticks"] != root_start:
            raise RuntimeError("Resource server PID was reused")
        status = dict(line.split(":", 1) for line in (base / "status").read_text().splitlines())
        try:
            io = dict(line.split(":", 1) for line in (base / "io").read_text().splitlines())
        except FileNotFoundError as error:
            raise RuntimeError("Server /proc I/O counters unavailable; resource observation cannot be qualified") from error
        tasks = list((base / "task").iterdir())
        if len(tasks) > 128:
            raise RuntimeError("Server thread count exceeds resource observation bound")
        children = set()
        for task in tasks:
            children.update(map(int, (task / "children").read_text().split()))
        pending.extend(children)
        for key in ("VmRSS", "VmHWM"):
            if status[key].split()[1] != "kB":
                raise RuntimeError("Unexpected Linux memory counter unit")
        after = _stat(base / "stat")
        if after["start_ticks"] != before["start_ticks"]:
            raise RuntimeError("Resource server process changed during observation")
        executable = (base / "exe").stat()
        if exe_identity != [executable.st_dev, executable.st_ino, executable.st_size, executable.st_mtime_ns]:
            raise RuntimeError("Resource executable changed during observation")
        rows[pid] = dict(after,
                         exe_identity=exe_identity, threads=sorted(int(task.name) for task in tasks),
                         children=sorted(children),
                         rss_bytes=int(status["VmRSS"].split()[0]) * 1024,
                         lifetime_hwm_bytes=int(status["VmHWM"].split()[0]) * 1024,
                         **{k: int(io[k]) for k in ("read_bytes", "write_bytes", "cancelled_write_bytes")})
    return rows


def server_delta(before, after, ticks_per_second):
    if before.keys() != after.keys():
        raise RuntimeError("Server process membership changed; resource cell is incomplete")
    rows = []
    for pid, start in before.items():
        end = after[pid]
        if start["start_ticks"] != end["start_ticks"]:
            raise RuntimeError("Resource server PID was reused")
        if any(start[key] != end[key] for key in ("exe_identity", "threads", "children")):
            raise RuntimeError("Resource process executable or task membership changed")
        if any(start[k] != end[k] for k in ("reaped_user_ticks", "reaped_system_ticks")):
            raise RuntimeError("Server reaped an unobserved child; resource cell is incomplete")
        row = {"pid": pid, "start_ticks": start["start_ticks"],
               "exe_identity": start["exe_identity"],
               "rss_before_bytes": start["rss_bytes"], "rss_after_bytes": end["rss_bytes"],
               "lifetime_hwm_before_bytes": start["lifetime_hwm_bytes"],
               "lifetime_hwm_after_bytes": end["lifetime_hwm_bytes"]}
        for source, target in (("user_ticks", "user_cpu_seconds"), ("system_ticks", "system_cpu_seconds")):
            value = end[source] - start[source]
            if value < 0:
                raise RuntimeError("CPU counter decreased")
            row[target] = value / ticks_per_second
        for key in ("read_bytes", "write_bytes", "cancelled_write_bytes"):
            row[key] = end[key] - start[key]
            if row[key] < 0:
                raise RuntimeError("I/O counter decreased; resource cell is incomplete")
        rows.append(row)
    return rows


def _allocation():
    value = int(Path('/proc/sys/kernel/ns_last_pid').read_text().strip())
    if value < 0:
        raise RuntimeError('Invalid PID allocation counter')
    return value


def _client():
    pid = os.getpid()
    rows = _server(pid, _stat(Path('/proc/self/stat'))['start_ticks'])
    if len(rows) != 1:
        raise RuntimeError('Client descendants are outside the single-client resource scope')
    return dict(rows[pid], pid=pid)


class OperationResources:
    def __init__(self, root_pid, root_start, *, server_reader=_server,
                 usage_reader=lambda: resource.getrusage(resource.RUSAGE_SELF),
                 client_reader=_client, allocation_reader=_allocation):
        self.pid, self.start = root_pid, root_start
        self.server_reader, self.usage_reader = server_reader, usage_reader
        self.client_reader, self.allocation_reader = client_reader, allocation_reader
        self.ticks = os.sysconf("SC_CLK_TCK")
        self.manifest_sha256 = None
        self.backend = None

    @classmethod
    def from_environment(cls, engine, postgres_backend_pid=None):
        path = os.environ.get(ENV)
        if not path:
            return None
        if sys.platform != "linux":
            raise RuntimeError("SQL resource counters require Linux")
        raw = Path(path).read_bytes()
        manifest = json.loads(raw)
        if manifest["schema"] != "alopex.sql-resource-servers/v1":
            raise RuntimeError("Unknown SQL resource manifest")
        record = manifest["servers"][engine]
        pid, start = record["pid"], record["start_ticks"]
        if type(pid) is not int or pid <= 0 or type(start) is not int or start <= 0:
            raise RuntimeError("Invalid resource server identity")
        if engine == "alopex-server":
            from subject_identity import verify_subject
            identity = verify_subject(require_server=True)["server"]
            if (identity["pid"], identity["start_ticks"]) != (pid, start):
                raise RuntimeError("Resource server differs from qualified subject")
        observer = cls(pid, start)
        rows = observer.server_reader(pid, start)  # Fail before timing if inaccessible.
        if engine == "postgresql" and postgres_backend_pid not in rows:
            raise RuntimeError("PostgreSQL connection is outside the observed server tree")
        observer.backend = postgres_backend_pid if engine == 'postgresql' else None
        observer.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        return observer

    def begin(self):
        # Client usage excludes the server's /proc enumeration on both ends.
        allocation = self.allocation_reader()
        servers = self.server_reader(self.pid, self.start)
        client = self.client_reader()
        if client['pid'] in servers or (self.backend is not None and self.backend not in servers):
            raise RuntimeError('Resource server/client/backend membership mismatch')
        if allocation != self.allocation_reader():
            raise RuntimeError('PID allocation changed during resource snapshot')
        return {'servers': servers, 'client': client, 'allocation': allocation, 'usage': self.usage_reader()}

    def end(self, before):
        client_after = self.usage_reader()
        client_proc_after = self.client_reader()
        server_after = self.server_reader(self.pid, self.start)
        if before['allocation'] != self.allocation_reader():
            raise RuntimeError('PID allocation changed; transient process coverage is incomplete')
        server_before, client_before = before['servers'], before['usage']
        client_proc_before = before['client']
        if self.backend is not None and self.backend not in server_after:
            raise RuntimeError('PostgreSQL backend disappeared from resource observation')
        proc = server_delta({client_proc_before['pid']: client_proc_before},
                            {client_proc_after['pid']: client_proc_after}, self.ticks)[0]
        client = {"user_cpu_seconds": client_after.ru_utime - client_before.ru_utime,
                  "system_cpu_seconds": client_after.ru_stime - client_before.ru_stime,
                  "input_blocks": client_after.ru_inblock - client_before.ru_inblock,
                  "output_blocks": client_after.ru_oublock - client_before.ru_oublock,
                  "lifetime_hwm_before_bytes": client_before.ru_maxrss * 1024,
                  "lifetime_hwm_after_bytes": client_after.ru_maxrss * 1024}
        if any(client[key] < 0 for key in ("user_cpu_seconds", "system_cpu_seconds",
                                           "input_blocks", "output_blocks")):
            raise RuntimeError("Client resource counter decreased; resource cell is incomplete")
        client.update({key: proc[key] for key in ('pid', 'start_ticks', 'exe_identity',
                      'rss_before_bytes', 'rss_after_bytes', 'read_bytes', 'write_bytes', 'cancelled_write_bytes')})
        return {"schema": "alopex.sql-operation-resources/v1", "status": "observed",
                "coverage": "stable_pid_namespace_allocation",
                "manifest_sha256": self.manifest_sha256, "client": client,
                "server_processes": server_delta(server_before, server_after, self.ticks),
                "server_cpu_tick_seconds": 1 / self.ticks,
                "scope": "operation window; client getrusage and stable live server subtree /proc counters; no raw writes, validation, fixture or connection setup",
                "limitations": "server snapshots bracket client timer and include background activity; boundary RSS and lifetime HWM are not operation peaks; RSS is not additive; PID/thread allocation invalidates the interval instead of reconstructing events; server CPU below one tick is unresolved"}
