"""Recalculate the public #681 writer report using only Python's standard library."""
import hashlib
import json
from pathlib import Path
import re
import statistics

PHASES = ('seed', 'index_build', 'cold_transaction_1', 'cold_transaction_2', 'warm',
          'writer_begin', 'first_insert', 'second_insert', 'rollback')
TIMED = tuple(p for p in PHASES if p not in ('warm', 'rollback'))
SOURCE_FIELDS = {'source_commit', 'source_tree', 'binary_sha256', 'parser_sha256',
                 'example_source_sha256', 'cargo_lock_sha256'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compare(before, candidate):
    require(len(before) == len(candidate) == 5, 'five samples required')
    b, c = map(statistics.median, (before, candidate))
    db = statistics.median(abs(x - b) for x in before)
    dc = statistics.median(abs(x - c) for x in candidate)
    noise = 3 * max(db, dc)
    return dict(before=before, candidate=candidate, baseline_median=b, candidate_median=c,
                baseline_mad=db, candidate_mad=dc, noise=noise, difference=c - b, ratio=c / b,
                improvement_at_least_ten_percent=b - c >= b * .1 and b - c > noise,
                increase_exceeds_noise=c - b > noise)


def recompute(raw):
    require(set(raw) == {'schema', 'stages'} and raw['schema'] == 'alopex.hnsw-writer-public/v1', 'schema')
    require([s['rows'] for s in raw['stages']] == [1000, 10000, 100000], 'stage inventory')
    result = {}
    for stage in raw['stages']:
        require(set(stage) == {'rows', 'run', 'controller', 'assets', 'subjects', 'samples', 'public_result_sha256'}, 'stage fields')
        require(type(stage['run']) is int and stage['run'] > 0, 'run identity')
        require(re.fullmatch('[a-f0-9]{40}', stage['controller']), 'controller identity')
        require(re.fullmatch('[a-f0-9]{64}', stage['public_result_sha256']), 'result identity')
        require(set(stage['assets']) == set(stage['subjects']) == {'before', 'candidate'}, 'subjects')
        for subject in ('before', 'candidate'):
            require(re.fullmatch('[a-f0-9]{64}', stage['assets'][subject]), 'asset identity')
            require(set(stage['subjects'][subject]) == SOURCE_FIELDS, 'source fields')
            for key, value in stage['subjects'][subject].items():
                require(re.fullmatch('[a-f0-9]{' + ('40' if key in ('source_commit', 'source_tree') else '64') + '}', value), 'source identity')
        expected = [(i, name) for i in range(5)
                    for name in (('before', 'candidate') if i % 2 == 0 else ('candidate', 'before'))]
        require([(r['sample'], r['subject']) for r in stage['samples']] == expected, 'sample order or coverage')
        grouped = {'before': [], 'candidate': []}
        decreases = []
        for row in stage['samples']:
            require(set(row) == {'sample', 'subject', 'elapsed_ns', 'kernel_rss', 'cold_cache', 'graph_bytes', 'source_records'}, 'sample fields')
            require(set(row['source_records']) == {'events_sha256', 'summary_sha256'} and
                    all(re.fullmatch('[a-f0-9]{64}', h) for h in row['source_records'].values()), 'raw record identity')
            require(set(row['elapsed_ns']) == set(TIMED) and
                    all(type(v) is int and v > 0 for v in row['elapsed_ns'].values()), 'timed coverage')
            require(type(row['graph_bytes']) is int and 0 < row['graph_bytes'] <= 256 * 1024**2, 'cache fit')
            cache = row['cold_cache']
            require(set(cache) == {'start', 'first', 'second'}, 'cache observation coverage')
            for values in cache.values():
                require(set(values) == {'entries', 'hits', 'misses'} and
                        all(type(v) is int and v >= 0 for v in values.values()), 'cache counters')
            require(cache['start']['entries'] == 0 and cache['first']['misses'] > cache['start']['misses'], 'initial load')
            first, second = cache['first'], cache['second']
            if row['subject'] == 'candidate':
                require(first['entries'] == second['entries'] == 1 and second['misses'] == first['misses']
                        and second['hits'] > first['hits'], 'candidate cache reuse')
            else:
                require(first['entries'] == second['entries'] == 0 and second['misses'] > first['misses'], 'baseline cache behavior')
            require(set(row['kernel_rss']) == set(PHASES), 'RSS coverage')
            peaks = {}
            for phase, observation in row['kernel_rss'].items():
                require(set(observation) == {'before_reset', 'after_reset', 'after', 'reported_peak_bytes'}, 'RSS fields')
                for when in ('before_reset', 'after_reset', 'after'):
                    value = observation[when]
                    require(set(value) == {'rss_bytes', 'high_water_bytes'} and
                            all(type(v) is int for v in value.values()) and
                            value['high_water_bytes'] >= value['rss_bytes'] > 0, 'RSS values')
                reset = observation['after_reset']['high_water_bytes']
                end = observation['after']['high_water_bytes']
                peak = max(reset, end)
                require(type(observation['reported_peak_bytes']) is int and observation['reported_peak_bytes'] == peak, 'RSS peak aggregation')
                if end < reset:
                    decreases.append({'subject': row['subject'], 'sample': row['sample'], 'phase': phase})
                peaks[phase] = peak
            grouped[row['subject']].append({'elapsed_ns': row['elapsed_ns'], 'kernel_peak_rss_bytes': peaks})
        comparisons = {metric: {phase: compare([s[metric][phase] for s in grouped['before']],
                                                [s[metric][phase] for s in grouped['candidate']])
                               for phase in phases}
                       for metric, phases in [('elapsed_ns', TIMED), ('kernel_peak_rss_bytes', PHASES)]}
        result[str(stage['rows'])] = {'comparisons': comparisons, 'kernel_high_water_decreases': decreases}
    return result


def markdown(raw, computed):
    lines = ['# HNSW初回書込みの段階比較', '',
             '最初のINSERTは、1,000・10,000・100,000行の各段階で時間と区間RSSが改善しました。'
             '一方、10万行では準備時間が10.56%、索引構築時間が8.12%増加しています。'
             '周辺区間の増加と未分離の処理が残るため、#681全体の受入は未完了です。', '',
             '対象は各段階384次元、修正前・候補各5標本の計30標本です。'
             '同じ段階内で実行順を交互にし、全標本を集計しました。'
             'これは書込み側の比較であり、[検索の退行結果](../run-42450985865/report.md)を解消する証拠にはなりません。', '',
             '## 最初のINSERTで時間とRSSが減少', '',
             '| 行数 | 修正前 ms | 候補 ms | 時間短縮 | 修正前 RSS MB | 候補 RSS MB | RSS減少 |',
             '| ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for stage in raw['stages']:
        values = computed[str(stage['rows'])]['comparisons']
        t, m = values['elapsed_ns']['first_insert'], values['kernel_peak_rss_bytes']['first_insert']
        lines.append(f"| {stage['rows']:,} | {t['baseline_median']/1e6:.3f} | {t['candidate_median']/1e6:.3f} | {(1-t['ratio'])*100:.2f}% | {m['baseline_median']/1e6:.3f} | {m['candidate_median']/1e6:.3f} | {(1-m['ratio'])*100:.2f}% |")
    lines += ['', 'RSSはプロセス全体についてkernelが報告した値です。各区間のreset直後と終了時のVmHWMの最大を使います。'
              '正確な割当量やHNSW単体のメモリ量を示すものではありません。MBは1,000,000 bytesです。', '',
              '## cacheの保持を全標本で確認', '',
              '初回transactionは空のcacheからロードし、候補は2回目のtransactionでhitが増え、missは増えませんでした。'
              '修正前は各transaction後のentriesが0で、2回目にもmissが増えています。'
              '各標本のentries・hits・missesはraw.jsonに収録しています。', '',
              '## 準備・構築を含む全区間の結果', '',
              '各値は5標本の中央値です。ばらつきの幅は `3 × max(MAD_before, MAD_candidate)` とし、'
              'MADは中央値からの絶対偏差の中央値を表します。10%以上の短縮・減少に加えて差がこの幅を超えた場合を改善とします。'
              '増加が同じ幅を超えた場合は増加として残します。統計的な信頼区間ではありません。']
    for stage in raw['stages']:
        lines += ['', f"### {stage['rows']:,}行", '', f"[実行run {stage['run']}](https://github.com/alopex-db/alopex/actions/runs/{stage['run']})。制御commit: `{stage['controller']}`。", '']
        for metric, scale, unit in [('elapsed_ns', 1e6, 'ms'), ('kernel_peak_rss_bytes', 1e6, 'MB')]:
            lines += [f'| 区間 ({unit}) | 修正前 | 候補 | 3 MAD | 増減 | 判定 |', '| --- | ---: | ---: | ---: | ---: | --- |']
            for phase, v in computed[str(stage['rows'])]['comparisons'][metric].items():
                status = '増加' if v['increase_exceeds_noise'] else '10%以上改善' if v['improvement_at_least_ten_percent'] else '変化未確定'
                lines.append(f"| {phase} | {v['baseline_median']/scale:.6f} | {v['candidate_median']/scale:.6f} | {v['noise']/scale:.6f} | {(v['ratio']-1)*100:+.2f}% | {status} |")
            lines.append('')
        count = len(computed[str(stage['rows'])]['kernel_high_water_decreases'])
        lines += [f'終了時のVmHWMがreset直後より小さかった区間は{count}件です。両方の元の値を保持し、最大を集計しました。']
    lines += ['', '## ソースと計測範囲', '',
              '| 対象 | 製品commit |', '| --- | --- |']
    for subject, label in [('before', '修正前'), ('candidate', '候補')]:
        commits = {stage['subjects'][subject]['source_commit'] for stage in raw['stages']}
        require(len(commits) == 1, 'product source differs across stages')
        lines.append(f'| {label} | `{next(iter(commits))}` |')
    lines += ['', '製品tree、release binary、parser、計測example、Cargo.lock、資産manifestのhashをraw.jsonへ収録しました。'
              '比較時点の候補の結果であり、後続修正や配布資産の認定を代替しません。', '',
              '`seed`はデータ準備、`index_build`は索引構築、`cold_transaction_1/2`はcold状態からのtransaction、'
              '`writer_begin`は書込みtransactionの開始、`first_insert/second_insert`はその中のINSERTです。'
              '`warm`と`rollback`はRSSだけを観測しました。SQL commit・rollbackの時間とINSERT内部のfork/staging別時間は分離していません。', '',
              '10万行の先行run [42422429017](https://github.com/alopex-db/alopex/actions/runs/42422429017)はRSS観測器の誤った単調増加条件で停止し、'
              '[42424994599](https://github.com/alopex-db/alopex/actions/runs/42424994599)は索引構築中にtimeoutしました。'
              'いずれも完了標本0で、成功比較へ混ぜていません。最終runは計測範囲と各5標本を維持し、1ケースの時間枠を900秒から1800秒へ変更しました。'
              '性能の改善基準は変更していません。', '',
              '## 元のカウンターから再計算する', '',
              'このディレクトリで次を実行すると、全30標本、7計時区間・9 RSS区間、cache契約、manifestを照合し、comparison.jsonと本文を再生成して一致を確認します。', '',
              '```sh', 'python3 -B hnsw_writer_report.py', '```', '',
              '`raw.json`に全標本の時間、reset前・reset後・終了時のRSS/VmHWM、cacheカウンターを収録しています。'
              '元のevents/summaryのhashと結び付け、`comparison.json`には5標本の値・中央値・MAD・判定を保存しています。', '',
              '次は準備・索引構築と資源増加の原因・影響を評価し、未分離区間を測定します。'
              '最終候補との対応付けを含めて[#681](https://github.com/alopex-db/alopex/issues/681)で受入を続けます。', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_bytes())
    require(set(manifest) == {'files'} and set(manifest['files']) == {'raw.json', 'comparison.json', 'report.md', 'hnsw_writer_report.py'}, 'manifest inventory')
    for name, digest in manifest['files'].items():
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, 'manifest hash')
    raw = json.loads((root / 'raw.json').read_bytes())
    calculated = recompute(raw)
    require(calculated == json.loads((root / 'comparison.json').read_bytes()), 'comparison differs')
    require(markdown(raw, calculated) == (root / 'report.md').read_text(), 'report differs')
    print('verified: 30 samples, 210 timed phases, 270 RSS phases; all reported results reproduced')
