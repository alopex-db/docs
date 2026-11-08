"""Recalculate the public WAL report without installing or running Alopex."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from collections import Counter

SHAPES = (('kv', 16), ('kv', 2048), ('sql', 16), ('sql', 2048))
TIMES = ('prepare_ns', 'open_ns', 'schema_ns', 'index_ns', 'prior_ns', 'begin_ns', 'stage_ns', 'commit_ns')
METRICS = TIMES + ('peak_rss_bytes', 'wal_bytes', 'spool_bytes', 'fixture_bytes', 'allocated_bytes')
COUNTERS = ('ru_utime', 'ru_stime', 'ru_nvcsw', 'ru_nivcsw', 'read_bytes', 'write_bytes', 'cancelled_write_bytes')
RSS = ('VmRSS', 'RssAnon', 'RssFile', 'RssShmem')
ROLLUP = ('Rss', 'Pss_Anon', 'Pss_File', 'Pss_Shmem', 'Anonymous')
SOURCES = ('source_commit', 'source_tree', 'manifest_sha256', 'wheel_sha256', 'native_sha256', 'controller')


def require(value, message):
    if not value:
        raise ValueError(message)


def fields(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'field inventory')


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'numeric value')


def integer(value):
    require(type(value) is int and value >= 0, 'integer value')


def identity(value, length=64):
    require(type(value) is str and re.fullmatch('[a-f0-9]{' + str(length) + '}', value), 'source identity')


def cells(rounds):
    return [(r, surface, size, subject) for r in range(rounds) for surface, size in SHAPES
            for subject in (('before', 'candidate') if r % 2 == 0 else ('candidate', 'before'))]


def cell(row):
    fields(row, ('round', 'surface', 'value_bytes', 'subject'))
    integer(row['round']); integer(row['value_bytes'])
    require(row['surface'] in ('kv', 'sql') and row['subject'] in ('before', 'candidate'), 'cell labels')
    return tuple(row[k] for k in ('round', 'surface', 'value_bytes', 'subject'))


def check_run(run):
    integer(run['run']); identity(run['controller'], 40)
    for key in ('artifact_sha256', 'evidence_sha256', 'configuration_sha256'):
        identity(run[key])
    fields(run['products'], ('before', 'candidate'))
    for product in run['products'].values():
        fields(product, SOURCES + ('run', 'artifact_id', 'artifact_sha256'))
        integer(product['run']); integer(product['artifact_id'])
        for key in SOURCES:
            identity(product[key], 40 if key in ('source_commit', 'source_tree', 'controller') else 64)
        identity(product['artifact_sha256'])


def recompute(raw):
    fields(raw, ('schema', 'cost_runs', 'diagnostic_runs'))
    require(raw['schema'] == 'alopex.wal-commit-public/v1', 'schema')
    require([r['run'] for r in raw['cost_runs']] == [42438307642, 42490656351], 'cost runs')
    require([r['run'] for r in raw['diagnostic_runs']] == [42487505305, 42490399767], 'diagnostic runs')
    common = ('run', 'controller', 'artifact_sha256', 'evidence_sha256', 'configuration_sha256', 'products', 'samples')
    result = {'cost_runs': {}, 'diagnostic_runs': {}}
    for run in raw['cost_runs']:
        fields(run, common); check_run(run)
        require([cell(r['cell']) for r in run['samples']] == cells(6), 'complete ordered cost matrix')
        for row in run['samples']:
            fields(row, ('cell', 'writer', 'readers', 'commit_counters', 'memory', 'source_hashes'))
            fields(row['writer'], METRICS)
            for value in row['writer'].values(): integer(value)
            require(0 < row['writer']['peak_rss_bytes'] <= 1073741824 and
                    row['writer']['fixture_bytes'] <= 1048576, 'fixture and RSS limits')
            require(len(row['readers']) == 2, 'two reopens required')
            for reader in row['readers']:
                fields(reader, ('verified', 'open_ns', 'wal_bytes', 'spool_bytes', 'fixture_bytes', 'allocated_bytes'))
                require(reader['verified'] is True, 'reader result')
                for key, value in reader.items():
                    if key != 'verified': integer(value)
                require(reader['fixture_bytes'] <= 1048576, 'reader fixture limit')
            fields(row['commit_counters'], COUNTERS)
            for key, value in row['commit_counters'].items():
                (number if key in ('ru_utime', 'ru_stime') else integer)(value)
            fields(row['memory'], ('before_identity', 'after_identity_and_native_digest', 'lifetime_high_water_bytes'))
            for phase in ('before_identity', 'after_identity_and_native_digest'):
                observation = row['memory'][phase]
                fields(observation, ('rss_bytes', 'high_water_bytes'))
                for value in observation.values(): integer(value)
                require(0 < observation['rss_bytes'] <= observation['high_water_bytes'], 'RSS observation')
            integer(row['memory']['lifetime_high_water_bytes'])
            fields(row['source_hashes'], ('writer', 'reader1', 'reader2', 'observation', 'memory'))
            for value in row['source_hashes'].values(): identity(value)
        medians = {}; comparisons = {}; context = {}
        for surface, size in SHAPES:
            groups = {}
            for subject in ('before', 'candidate'):
                rows = [r for r in run['samples'] if cell(r['cell'])[1:] == (surface, size, subject) and r['cell']['round'] > 0]
                require(len(rows) == 5, 'five measured samples required')
                values = {key: statistics.median(r['writer'][key] for r in rows) for key in METRICS}
                values['commit_mad_ns'] = statistics.median(abs(r['writer']['commit_ns'] - values['commit_ns']) for r in rows)
                medians[f'{subject}-{surface}-{size}'] = values
                groups[subject] = values
                context[f'{subject}-{surface}-{size}'] = dict(
                    commit_ns=[r['writer']['commit_ns'] for r in rows],
                    cpu_seconds=[r['commit_counters']['ru_utime'] + r['commit_counters']['ru_stime'] for r in rows],
                    physical_write_bytes=[r['commit_counters']['write_bytes'] for r in rows],
                    voluntary_switches=[r['commit_counters']['ru_nvcsw'] for r in rows],
                    rss_before_identity=statistics.median(r['memory']['before_identity']['rss_bytes'] for r in rows),
                    rss_after_identity=statistics.median(r['memory']['after_identity_and_native_digest']['rss_bytes'] for r in rows))
            before, after = groups['before'], groups['candidate']
            require(before['commit_ns'] > 0, 'baseline timer')
            ratio = after['commit_ns'] / before['commit_ns']
            noise = 3 * max(before['commit_mad_ns'], after['commit_mad_ns']) / before['commit_ns']
            comparisons[f'{surface}-{size}'] = dict(commit_ratio=ratio, commit_noise_ratio=noise,
                decision='pending_noise' if noise > .05 else ('investigate_increase' if ratio > 1.05 else 'within_five_percent'),
                resource_increases={key: after[key] - before[key] for key in ('peak_rss_bytes', 'wal_bytes', 'spool_bytes') if after[key] > before[key]})
        result['cost_runs'][str(run['run'])] = dict(medians=medians, comparison=comparisons, context=context)
    for run in raw['diagnostic_runs']:
        fields(run, common); check_run(run)
        require([cell(r['cell']) for r in run['samples']] == cells(1), 'complete diagnostic matrix')
        computed = []
        for row in run['samples']:
            fields(row, ('cell', 'calls', 'sync_order', 'before', 'after'))
            for name, measurement in row['calls'].items():
                require(name in {a + '/' + b for a in ('spool', 'directory', 'wal') for b in ('write', 'writev', 'fsync', 'fdatasync')}, 'syscall target')
                fields(measurement, ('count', 'duration_ns'))
                for value in measurement.values(): integer(value)
            require(type(row['sync_order']) is list and all(v in ('spool/fsync', 'directory/fsync', 'wal/fdatasync') for v in row['sync_order']), 'sync order')
            require(dict(Counter(row['sync_order'])) == {key: v['count'] for key, v in row['calls'].items()
                    if key.endswith(('/fsync', '/fdatasync'))}, 'sync event counts')
            if row['cell']['subject'] == 'candidate' and row['cell']['value_bytes'] == 2048:
                require(row['sync_order'] == ['spool/fsync', 'directory/fsync', 'wal/fdatasync'], 'candidate durability order')
                if run['run'] == 42490399767:
                    require(row['calls']['spool/write']['count'] == 2 and row['calls']['spool/writev']['count'] ==
                            (17 if row['cell']['surface'] == 'kv' else 36), 'vectored submissions')
            for boundary in ('before', 'after'):
                fields(row[boundary], ('status_bytes', 'smaps_rollup_bytes'))
                for group, names in (('status_bytes', RSS), ('smaps_rollup_bytes', ROLLUP)):
                    fields(row[boundary][group], names)
                    for value in row[boundary][group].values(): integer(value)
                status = row[boundary]['status_bytes']
                require(status['VmRSS'] == status['RssAnon'] + status['RssFile'] + status['RssShmem'], 'RSS sum')
            delta = {g: {k: row['after'][g][k] - v for k, v in values.items()} for g, values in row['before'].items()}
            computed.append(dict(cell=row['cell'], spool_writes=sum(row['calls'].get('spool/' + name, {}).get('count', 0) for name in ('write', 'writev')), memory_delta=delta))
        result['diagnostic_runs'][str(run['run'])] = computed
    return result


def markdown(raw, computed):
    lines = ['# WAL commitの費用とspool書込み', '',
        'spoolの書込み回数は大値KVで36回から19回、SQLで74回から38回に減りました。'
        '一方、commit時間の固定比較は4条件ともノイズ保留です。同期順序と復旧の確認は完了していますが、'
        '速度改善やメモリ増加の解消は認定していません。', '',
        '基準版に対する重複同期削減後と、さらにframe/payloadをまとめた#817の2回の比較を収録します。'
        '異なるrunの比率差を#817単独の効果とは扱いません。先行結果もそのまま残しています。', '',
        '## 同じfixtureで書込み回数の削減を確認', '',
        '各診断はKV/SQL、値16/2048 bytes、基準/比較対象の8 writerと16 readerです。'
        '初期1件に2件を追加し、全値とSQL索引を新しい読み手で2回確認しました。'
        '最大fixtureは15,693 bytesです。', '',
        '| 診断run | API / 値bytes | 基準spool書込み | 比較対象spool書込み |',
        '| --- | --- | ---: | ---: |']
    for run in raw['diagnostic_runs']:
        values = computed['diagnostic_runs'][str(run['run'])]
        for surface, size in SHAPES:
            pair = {v['cell']['subject']: v for v in values if (v['cell']['surface'], v['cell']['value_bytes']) == (surface, size)}
            lines.append(f"| [{run['run']}](https://github.com/alopex-db/alopex/actions/runs/{run['run']}) | {surface} / {size} | {pair['before']['spool_writes']} | {pair['candidate']['spool_writes']} |")
    lines += ['', '小値ではinline経路によりspoolが不要になります。大値の#817はheader/sealのwrite各1回と、'
        'KV17回・SQL36回のwritevです。spool fsync→directory fsync→WAL fdatasync各1回を維持しました。'
        'traceの所要時間には観測とスケジューリングの影響が入り、性能判定には使いません。', '',
        '## commit時間は両比較とも4条件がノイズ保留', '',
        '各runは48 writer・96 reader、4条件を6組ずつ交互の順序で実行しました。'
        '初回の1組を除いた各5値で中央値とMAD（中央値からの絶対偏差の中央値）を求めます。'
        '`3 × max(MAD_before, MAD_candidate) / baseline_median` が5%を超えるとノイズ保留、'
        'それ以外で時間比が1.05を超えると増加調査、それ以外は5%内です。この幅は統計的な信頼区間ではありません。']
    for run in raw['cost_runs']:
        values = computed['cost_runs'][str(run['run'])]
        lines += ['', f"### [比較{run['run']}](https://github.com/alopex-db/alopex/actions/runs/{run['run']})", '',
            '| API / 値bytes | 基準 ms | 比較対象 ms | 増減 | ノイズ幅 / 基準 | 判定 | RSS増加 bytes |',
            '| --- | ---: | ---: | ---: | ---: | --- | ---: |']
        for surface, size in SHAPES:
            key = f'{surface}-{size}'; b = values['medians']['before-' + key]; c = values['medians']['candidate-' + key]; v = values['comparison'][key]
            lines.append(f"| {surface} / {size} | {b['commit_ns']/1e6:.6f} | {c['commit_ns']/1e6:.6f} | {(v['commit_ratio']-1)*100:+.2f}% | {v['commit_noise_ratio']*100:.2f}% | {v['decision']} | {c['peak_rss_bytes']-b['peak_rss_bytes']:,} |")
    lines += ['', '今回の大値KV中央値−11.07%、SQL＋1.75%は観測値です。ノイズ保留を性能改善の認定へ置き換えません。'
        '小値SQLの比較対象には9.603254 msの標本もあり、除外していません。', '',
        '## RSS差はcommit前から存在する', '',
        'RSS増加はwriter全寿命の最大値の中央値差です。import、資産identity検査、DB準備も含み、'
        'WAL単体の割当量を表しません。以下は今回の各5標本の中央値です。', '',
        '| API / 値bytes | import後RSS差 bytes | identity検査後RSS差 bytes | 物理書込み bytes 基準/比較対象 |',
        '| --- | ---: | ---: | --- |']
    latest = computed['cost_runs']['42490656351']
    for surface, size in SHAPES:
        key = f'{surface}-{size}'; b = latest['context']['before-' + key]; c = latest['context']['candidate-' + key]
        writes = f"{int(statistics.median(b['physical_write_bytes'])):,} / {int(statistics.median(c['physical_write_bytes'])):,}"
        lines.append(f"| {surface} / {size} | {c['rss_before_identity']-b['rss_before_identity']:,} | {c['rss_after_identity']-b['rss_after_identity']:,} | {writes} |")
    boundaries = computed['diagnostic_runs']['42490399767']
    zero = sum(all(v == 0 for group in row['memory_delta'].values() for v in group.values()) for row in boundaries)
    lines += ['', f'今回のtrace診断では{len(boundaries)} writer中{zero}件でcommit直前・直後のRSS内訳とsmaps_rollupの差分が0でした。'
        '区間内の一時的なpeakや割当ゼロの証明にはなりません。版間のRSS差ではfile-backed領域が大きく、'
        '匿名領域の差も残ります。対応するmappingやコード経路は分離していないため、原因は未確定です。'
        'PSSはRSSへ加算しません。commit区間のCPU・物理I/O・context switchの各標本はcomparison.jsonに保持しています。', '',
        '## ソースと原本を固定して再計算する', '',
        '| 費用比較run | 基準commit | 比較対象commit |', '| --- | --- | --- |']
    for run in raw['cost_runs']:
        lines.append(f"| {run['run']} | `{run['products']['before']['source_commit']}` | `{run['products']['candidate']['source_commit']}` |")
    lines += ['', 'raw.jsonは暗号化原本から許可項目だけを抽出した全標本です。96 writer・192 readerの時間・資源値、'
        '16 writerのtrace集計とメモリ境界、製品/制御commit、資産・原本・各標本のhashを収録しました。'
        '元のPID、配置、接続設定やtrace中のパスは収録していません。原本の値・索引・再open、資産hash、'
        '全プロセスwaitと後片付けは独立監査済みです。この公開データだけで非公開の原本そのものを再監査できるわけではありません。', '',
        'このディレクトリで次を実行すると、全標本の範囲・順序・型とmanifestを確認し、中央値・MAD・判定・本文を再計算します。', '',
        '```sh', 'python3 -B wal_commit_report.py', '```', '',
        '先行するnative全読取りのhash検証によるRSS混入はstream読取りへ訂正済みです。'
        '訂正前の大値KV＋16.48%や、訂正後の増加・ノイズ保留も[#682](https://github.com/alopex-db/alopex/issues/682)に保持しています。'
        '診断42490399767では終了確認後のreader統計3件を既定の規則で除外しました。両費用比較の末尾除外は0件です。'
        '生存中の欠測を0で補完していません。', '',
        '次はノイズ保留と資源増加を評価し、最終候補・配布資産へ証拠を対応付けます。'
        'この報告は#817の統合や#682全体・リリースの受入完了を意味しません。', '']
    return '\n'.join(lines)


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_bytes())
    fields(manifest, ('files',))
    fields(manifest['files'], ('raw.json', 'comparison.json', 'report.md', 'wal_commit_report.py'))
    for name, expected in manifest['files'].items():
        identity(expected)
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, 'manifest hash')
    raw = json.loads((root / 'raw.json').read_bytes()); calculated = recompute(raw)
    require(calculated == json.loads((root / 'comparison.json').read_bytes()), 'comparison differs')
    require(markdown(raw, calculated) == (root / 'report.md').read_text(), 'report differs')
    print('verified: 96 writers, 192 readers, 16 traced writers; all public results reproduced')


if __name__ == '__main__':
    verify(Path(__file__).resolve().parent)
