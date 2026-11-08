"""Recalculate the fixed CSV report using only its public numeric raw files."""
import hashlib
import json
import math
from pathlib import Path
import statistics

SUBJECTS = ('published', 'before', 'candidate', 'polars')
EVENTS = ('plan_sample', 'collect_sample', 'sample')
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
    """Select allowed scalar fields; never copy free text or process metadata."""
    require(cell['subject'] in SUBJECTS and type(cell['trial']) is int and cell['trial'] in range(3)
        and type(cell['rows']) is int and cell['rows'] in (3,34250), 'invalid CSV coordinate')
    event = row['event'];iteration = row['iteration']
    require(event in EVENTS and row['phase'] == 'measure' and type(iteration) is int and iteration in range(3,24),
        'invalid measurement sample')
    resource = row['resources']
    require(resource['index'] == EVENTS.index(event)*24+iteration, 'observation index differs')
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
    total = numeric(row['total_ns']);require(type(total) is int and total > 0, 'invalid total clock')
    out = dict(rows=cell['rows'],subject=cell['subject'],trial=cell['trial'],sample=iteration-3,event=event,
        total_ns=total,before=points['before'],after=points['after'],delta=selected,
        rss=dict(**memory,kernel_reported_peak_rss_bytes=peak,kernel_high_water_decreased=end<start))
    if event == 'sample':
        for key in ('first_ns','remaining_ns','outside_original_total_ns','first_chunk_rows'):
            out[key] = numeric(row[key]);require(type(out[key]) is int, 'invalid stream integer')
        require(out['first_ns']+out['remaining_ns'] == total and row['rows'] == cell['rows']
            and 0 < out['first_chunk_rows'] <= cell['rows'], 'invalid complete stream')
        for key in ('cpu_including_close_seconds','input_blocks_including_close','output_blocks_including_close'):
            out[key] = numeric(row[key])
    return out


def validate_public(row):
    require(type(row['sample']) is int and row['sample'] in range(21), 'invalid public sample index')
    cell = {k:row[k] for k in ('rows','subject','trial')}
    private_shape = dict(event=row['event'],iteration=row['sample']+3,phase='measure',total_ns=row['total_ns'],
        resources=dict(index=EVENTS.index(row['event'])*24+row['sample']+3,
            before=dict(**row['before']['cpu'],io=row['before']['io']),
            after=dict(**row['after']['cpu'],io=row['after']['io']),delta=row['delta'],rss=row['rss']))
    if row['event'] == 'sample':
        for key in ('first_ns','remaining_ns','outside_original_total_ns','first_chunk_rows',
            'cpu_including_close_seconds','input_blocks_including_close','output_blocks_including_close'):
            private_shape[key] = row[key]
        private_shape['rows'] = row['rows']
    require(sample(cell,private_shape) == row, 'unexpected public field or invalid sample')


def summarize(samples):
    require(len(samples) == 1512, 'incomplete public sample inventory')
    for row in samples:validate_public(row)
    coordinates = {(r['rows'],r['event'],r['subject'],r['trial'],r['sample']) for r in samples}
    expected = {(n,e,s,t,i) for n in (3,34250) for e in EVENTS for s in SUBJECTS for t in range(3) for i in range(21)}
    require(coordinates == expected, 'duplicate or missing CSV sample')
    phases, comparisons = {}, {}
    for size in (3,34250):
        for event in EVENTS:
            subjects = {}
            metrics = ['total_ns']+(['first_ns','remaining_ns','outside_original_total_ns'] if event == 'sample' else [])
            for subject in SUBJECTS:
                trials = []
                for trial in range(3):
                    rows = [r for r in samples if (r['rows'],r['event'],r['subject'],r['trial']) == (size,event,subject,trial)]
                    values = {key:statistics.median(r[key] for r in rows) for key in metrics}
                    values.update({k:statistics.median(r['delta'][k] for r in rows) for k in CPU+IO})
                    values['rss_peak_bytes'] = statistics.median(r['rss']['kernel_reported_peak_rss_bytes'] for r in rows)
                    distribution = {key:dict(min=min(r[key] for r in rows),max=max(r[key] for r in rows),
                        mad=statistics.median(abs(r[key]-values[key]) for r in rows)) for key in metrics}
                    trials.append(dict(medians=values,distribution=distribution,
                        max_phase_rss_bytes=max(r['rss']['kernel_reported_peak_rss_bytes'] for r in rows)))
                subjects[subject] = dict(trials=trials,
                    median_of_trial_medians={k:statistics.median(t['medians'][k] for t in trials) for k in trials[0]['medians']})
            phases[f'{size}-{event}'] = subjects
            for metric in (('total_ns','first_ns') if event == 'sample' else ('total_ns',)):
                trials = {s:[t['medians'][metric] for t in subjects[s]['trials']] for s in SUBJECTS}
                comparisons[f'{size}-{event}-{metric}'] = {s:decision(trials[s],trials['candidate']) for s in ('published','before','polars')}
    return dict(phases=phases,comparisons=comparisons)


def verify(directory):
    manifest = json.loads((directory/'manifest.json').read_bytes())
    require(manifest['schema'] == 'alopex.public-csv-report/v1' and manifest['samples'] == 1512, 'unexpected manifest')
    require(len(manifest['raw_files']) == 6, 'unexpected raw inventory')
    samples = []
    expected_names = {f'raw/{n}-{e}.ndjson' for n in (3,34250) for e in EVENTS}
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
    return dict(status='verified',samples=len(samples),raw_files=6)


if __name__ == '__main__':print(json.dumps(verify(Path(__file__).resolve().parent)))
