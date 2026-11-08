"""Recalculate the fixed SQLite composite report using only its public numeric raw files."""
import hashlib
import json
import math
from pathlib import Path
import statistics

SUBJECTS = ('published', 'before', 'candidate', 'sqlite')
CASES = ('original-execute','original-plan','checked-execute','checked-plan')
CPU = ('user_cpu_seconds', 'system_cpu_seconds')
IO = ('read_bytes', 'write_bytes', 'cancelled_write_bytes')
RSS = ('rss_bytes', 'high_water_bytes')


def require(value, message):
    if not value:raise ValueError(message)


def numeric(value):
    require(type(value) in (int,float) and math.isfinite(value) and value >= 0, 'invalid numeric field')
    return value


def decision(before, after):
    require(len(before) == len(after) == 3 and all(numeric(v) > 0 for v in before+after), 'invalid trial medians')
    b,c = statistics.median(before),statistics.median(after)
    db,dc = statistics.median(abs(v-b) for v in before),statistics.median(abs(v-c) for v in after)
    noise = 3*max(db,dc);ratio = c/b;noisy = noise > b*.05
    return dict(baseline_median=b,candidate_median=c,baseline_trial_mad=db,candidate_trial_mad=dc,
        noise=noise,latency_ratio=ratio,status='pending_noise' if noisy else 'regression' if ratio > 1.05 else 'within_tolerance',
        increase=c>b,improvement_fraction=(b-c)/b,exceeds_regression_threshold=ratio>1.05,
        improvement_proven=not noisy and (b-c)/b>=.05 and b-c>noise and all(y<x for x,y in zip(before,after)),
        paired_ratios=[y/x for x,y in zip(before,after)])


def sample(cell, row):
    """Select only numeric observations and fixed case coordinates."""
    require(cell['subject'] in SUBJECTS and type(cell['trial']) is int and cell['trial'] in range(3)
        and type(cell['rows']) is int and cell['rows'] == 34250 and cell['case'] in CASES, 'invalid SQLite coordinate')
    index = row['index']
    require(row['phase'] == 'measure' and type(index) is int and index in range(21)
        , 'invalid measurement sample')
    if cell['case'].endswith('-execute'):
        require(row['state_verified'] is True and row['result_verified'] is cell['case'].startswith('checked-'), 'invalid SQL validation')
    resource = row['resources']
    require(resource['index'] == index+3, 'observation index differs')
    before,after,delta,rss = (resource[k] for k in ('before','after','delta','rss'))
    points = {label:dict(cpu={k:numeric(value[k]) for k in CPU},
        io={k:numeric(value['io'][k]) for k in IO}) for label,value in (('before',before),('after',after))}
    selected = {k:numeric(delta[k]) for k in CPU+IO}
    for key in CPU:require(selected[key] == points['after']['cpu'][key]-points['before']['cpu'][key], 'invalid CPU delta')
    for key in IO:
        require(all(type(v) is int for v in (points['before']['io'][key],points['after']['io'][key],selected[key]))
            and selected[key] == points['after']['io'][key]-points['before']['io'][key], 'invalid I/O delta')
    memory = {point:{k:numeric(rss[point][k]) for k in RSS} for point in ('before_reset','after_reset','after')}
    require(all(v['high_water_bytes'] >= v['rss_bytes'] for v in memory.values()), 'invalid RSS counter')
    start,end = memory['after_reset']['high_water_bytes'],memory['after']['high_water_bytes']
    peak = numeric(rss['kernel_reported_peak_rss_bytes'])
    require(peak == max(start,end) and rss['kernel_high_water_decreased'] is (end<start), 'invalid RSS aggregation')
    seconds = numeric(row['seconds']);require(seconds > 0, 'invalid elapsed clock')
    return dict(rows=cell['rows'],subject=cell['subject'],trial=cell['trial'],sample=index,case=cell['case'],
        seconds=seconds,before=points['before'],after=points['after'],delta=selected,
        rss=dict(**memory,kernel_reported_peak_rss_bytes=peak,kernel_high_water_decreased=end<start))


def validate_public(row):
    cell = {k:row[k] for k in ('rows','subject','trial','case')}
    private_shape = dict(index=row['sample'],phase='measure',seconds=row['seconds'],
        state_verified=True,result_verified=row['case'].startswith('checked-'),resources=dict(index=row['sample']+3,
            before=dict(**row['before']['cpu'],io=row['before']['io']),
            after=dict(**row['after']['cpu'],io=row['after']['io']),delta=row['delta'],rss=row['rss']))
    require(sample(cell,private_shape) == row, 'unexpected public field or invalid sample')


def summarize(samples):
    require(len(samples) == 1008, 'incomplete public sample inventory')
    for row in samples:validate_public(row)
    coordinates = {(r['case'],r['subject'],r['trial'],r['sample']) for r in samples}
    expected = {(c,s,t,i) for c in CASES for s in SUBJECTS for t in range(3) for i in range(21)}
    require(coordinates == expected, 'duplicate or missing SQLite sample')
    phases,comparisons = {},{}
    for case in CASES:
        subjects = {}
        for subject in SUBJECTS:
            trials = []
            for trial in range(3):
                rows = [r for r in samples if (r['case'],r['subject'],r['trial']) == (case,subject,trial)]
                elapsed = [r['seconds'] for r in rows];median = statistics.median(elapsed)
                values = dict(seconds=median,**{k:statistics.median(r['delta'][k] for r in rows) for k in CPU+IO})
                values['rss_peak_bytes'] = statistics.median(r['rss']['kernel_reported_peak_rss_bytes'] for r in rows)
                trials.append(dict(medians=values,distribution=dict(min=min(elapsed),max=max(elapsed),
                    mad=statistics.median(abs(x-median) for x in elapsed)),
                    max_phase_rss_bytes=max(r['rss']['kernel_reported_peak_rss_bytes'] for r in rows)))
            subjects[subject] = dict(trials=trials,
                median_of_trial_medians={k:statistics.median(t['medians'][k] for t in trials) for k in trials[0]['medians']})
        phases[case] = subjects
        trials = {s:[t['medians']['seconds'] for t in subjects[s]['trials']] for s in SUBJECTS}
        comparisons[case] = {s:decision(trials[s],trials['candidate']) for s in ('published','before','sqlite')}
    return dict(phases=phases,comparisons=comparisons)


def verify(directory):
    manifest = json.loads((directory/'manifest.json').read_bytes())
    require(manifest['schema'] == 'alopex.public-sqlite-report/v1' and manifest['samples'] == 1008, 'unexpected manifest')
    require(len(manifest['raw_files']) == 4, 'unexpected raw inventory')
    samples = []
    expected_names = {f'raw/{case}.ndjson' for case in CASES}
    require({f['path'] for f in manifest['raw_files']} == expected_names, 'unexpected raw filename')
    for item in manifest['raw_files']:
        path = directory/item['path'];data = path.read_bytes()
        require(len(data) == item['size'] and hashlib.sha256(data).hexdigest() == item['sha256'], 'raw identity differs')
        rows = [json.loads(line) for line in data.splitlines()]
        require(len(rows) == item['samples'] == 252, 'raw sample count differs')
        samples.extend(rows)
    data = (directory/'comparison.json').read_bytes()
    require(hashlib.sha256(data).hexdigest() == manifest['comparison_sha256'], 'comparison identity differs')
    require(summarize(samples) == json.loads(data), 'independent recalculation differs')
    return dict(status='verified',samples=len(samples),raw_files=4)


if __name__ == '__main__':print(json.dumps(verify(Path(__file__).resolve().parent)))
