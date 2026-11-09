"""Recalculate HNSW search results from public numeric evidence only."""
import gzip
import hashlib
import json
from pathlib import Path

import math
import statistics

SUBJECTS = ('published', 'before', 'candidate', 'hnswlib', 'faiss-hnsw')
EF_VALUES = (16, 32, 64, 128, 256)
RESOURCE_SCOPE = ('Current process around the original search function, including '
    'percentile aggregation and observation overhead; excludes raw output, '
    'index construction, oracle and warmup.')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def plan(mode):
    require(mode in ('preflight', 'full'), 'unknown HNSW mode')
    cells = []
    for trial in range(1 if mode == 'preflight' else 3):
        subjects = SUBJECTS[trial:] + SUBJECTS[:trial]
        for subject in subjects:
            cells.append(dict(id=f'trial{trial}-{subject}', trial=trial, subject=subject,
                engine=subject if subject in ('hnswlib', 'faiss-hnsw') else 'alopex-hnsw',
                rows=32 if mode == 'preflight' else 9171, dimension=128,
                query_vectors=4 if mode == 'preflight' else 200, k=10,
                seed=42, m=16, ef_construction=200, ef_values=list(EF_VALUES),
                min_queries=4 if mode == 'preflight' else 10000,
                min_seconds=0.0 if mode == 'preflight' else 2.0))
    return cells


def validate_predictions(predicted, truth, acceptable, *, rows, k=10):
    require(type(predicted) is list and len(predicted) == len(truth) == len(acceptable)
        and len(truth) > 0, 'query result coverage differs')
    strict = tied = 0
    for result, expected, allowed in zip(predicted, truth, acceptable):
        for values, exact in ((result, True), (expected, True), (allowed, False)):
            require(type(values) is list and (len(values) == k if exact else len(values) >= k),
                'top-k cardinality differs')
            require(all(type(v) is int and 0 <= v < rows for v in values)
                and len(set(values)) == len(values), 'invalid or duplicate neighbor ID')
        require(set(expected) <= set(allowed), 'tie oracle omits exact neighbors')
        strict += len(set(result) & set(expected))
        tied += len(set(result) & set(allowed))
    return dict(recall_at_10=strict / (k * len(truth)),
        tie_aware_recall_at_10=tied / (k * len(truth)))


def verify_point(cell, row, predictions, truth, acceptable):
    require(row['engine'] == cell['engine'] and row['ef_search'] in cell['ef_values']
        and row['run'] == 1 and row['dataset_size'] == cell['rows']
        and row['dimension'] == cell['dimension'], 'search identity differs')
    count, duration, samples = row['query_count'], row['duration_seconds'], row['query_latencies_us']
    require(type(count) is int and count >= cell['min_queries']
        and finite(duration) and duration > 0 and duration >= cell['min_seconds'], 'search work incomplete')
    require(type(samples) is list and len(samples) == count
        and all(finite(s) and s > 0 for s in samples), 'query latency samples invalid')
    ordered = sorted(samples)
    calculated = dict(queries_per_second=count/duration, latency_us=duration*1e6/count,
        query_latency_p50_us=statistics.median(samples),
        query_latency_p95_us=ordered[max(0, (95*count+99)//100-1)],
        query_latency_p99_us=ordered[max(0, (99*count+99)//100-1)])
    for key, expected in calculated.items():
        require(finite(row[key]) and math.isclose(row[key], expected, rel_tol=1e-12, abs_tol=1e-12),
            'search summary differs from raw')
    for phase in ('before', 'after'):
        actual = validate_predictions(predictions[phase], truth, acceptable, rows=cell['rows'], k=cell['k'])
        for key, value in actual.items():
            require(finite(row[key]) and math.isclose(row[key], value, rel_tol=1e-12, abs_tol=1e-12),
                'recall changed or differs from saved results')
    # Exact ordering may vary for distance ties; retain both metrics and predictions.
    # Low recall is a real result, not a process failure or grounds to erase a row.
    native = row['native_search_latency_us']
    require((native is None and cell['engine'] != 'alopex-hnsw') or
        (cell['engine'] == 'alopex-hnsw' and finite(native) and native >= 0), 'native timing missing')
    residual = row['python_binding_residual_us']
    require((native is None and residual is None) or
        (native is not None and finite(residual) and residual == max(0.0, row['latency_us']-native)), 'legacy residual differs')
    return calculated


def same_recall_point(rows, threshold):
    """Choose only settings where every trial reaches the declared recall."""
    require(threshold in (0.95, 0.99), 'unsupported recall target')
    require(len(rows) == 15, 'three-trial search matrix incomplete')
    groups = {}
    for row in rows:
        key = row['ef_search']
        require(key in EF_VALUES and row['trial'] in (0, 1, 2), 'unexpected search point')
        groups.setdefault(key, []).append(row)
        require(finite(row['latency_us']) and row['latency_us'] > 0
            and finite(row['query_latency_p50_us']) and row['query_latency_p50_us'] > 0
            and finite(row['queries_per_second']) and row['queries_per_second'] > 0
            and finite(row['recall_at_10']) and 0 <= row['recall_at_10'] <= 1, 'invalid search point')
    require(set(groups) == set(EF_VALUES) and all(len(g) == 3 and
        {r['trial'] for r in g} == {0, 1, 2} for g in groups.values()), 'duplicate or absent trial')
    qualified = [(-statistics.median(r['queries_per_second'] for r in group), ef)
        for ef, group in groups.items() if all(r['recall_at_10'] >= threshold for r in group)]
    if not qualified:
        return None
    negative_qps, ef = min(qualified)
    return dict(ef_search=ef, latency_us=statistics.median(r['query_latency_p50_us'] for r in groups[ef]),
        mean_latency_us=statistics.median(r['latency_us'] for r in groups[ef]),
        queries_per_second=-negative_qps, recall_threshold=threshold,
        minimum_trial_recall=min(r['recall_at_10'] for r in groups[ef]))


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

def compare(rows):
    require(len(rows)==75,'full fixed HNSW matrix required')
    indexed={}
    for row in rows:
        key=row['subject'],row['trial'],row['ef_search']
        require(key not in indexed and key[0] in SUBJECTS and key[1] in (0,1,2) and key[2] in EF_VALUES,
            'unexpected or duplicate HNSW cell')
        for field in ('query_latency_p50_us','latency_us','queries_per_second'):
            require(type(row[field]) in (float,int) and math.isfinite(row[field]) and row[field]>0,'invalid HNSW time')
        require(type(row['recall_at_10']) in (float,int) and math.isfinite(row['recall_at_10'])
            and 0<=row['recall_at_10']<=1,'invalid HNSW recall')
        indexed[key]=row
    expected={(s,t,e) for s in SUBJECTS for t in range(3) for e in EF_VALUES}
    require(set(indexed)==expected,'HNSW point missing')
    def point(subject,ef):return [indexed[subject,t,ef] for t in range(3)]
    def pair(reference,ref_ef,candidate_ef,recall_threshold=.99):
        old,new=point(reference,ref_ef),point('candidate',candidate_ef)
        result=decision([r['query_latency_p50_us'] for r in old],[r['query_latency_p50_us'] for r in new])
        result.update(reference=reference,reference_ef=ref_ef,candidate_ef=candidate_ef,
            reference_minimum_recall=min(r['recall_at_10'] for r in old),
            candidate_minimum_recall=min(r['recall_at_10'] for r in new),
            throughput_ratio=statistics.median(r['queries_per_second'] for r in new)/statistics.median(r['queries_per_second'] for r in old),
            time_target_met=result['latency_ratio']<=1.,
            source='per-trial query p50; median across three trials; throughput separate')
        result['throughput_target_met']=result['throughput_ratio']>=1.
        # Numeric timing evidence does not override the search accuracy requirement.
        result['recall_99_met']=min(result['reference_minimum_recall'],result['candidate_minimum_recall'])>=.99
        result['recall_target_met']=min(result['reference_minimum_recall'],result['candidate_minimum_recall'])>=recall_threshold
        result['search_improvement_proven']=result['improvement_proven'] and result['recall_target_met']
        return result
    same_ef=[pair(reference,ef,ef) for ef in EF_VALUES for reference in SUBJECTS if reference!='candidate']
    winners={str(threshold):{subject:same_recall_point([r for r in rows if r['subject']==subject],threshold)
        for subject in SUBJECTS} for threshold in (.95,.99)}
    matched=[]
    for threshold,choices in winners.items():
        for reference in SUBJECTS:
            if reference=='candidate':continue
            old,new=choices[reference],choices['candidate']
            if old is None or new is None:
                matched.append(dict(reference=reference,recall_threshold=float(threshold),status='recall_unmet',
                    candidate_point=new,reference_point=old));continue
            matched.append(dict(pair(reference,old['ef_search'],new['ef_search'],float(threshold)),recall_threshold=float(threshold)))
    return dict(schema='alopex.hnsw-search-comparison/v1',same_ef=same_ef,same_recall=matched,winners=winners,
        definitions=dict(primary='median of trial query p50s; not elapsed/query',
            recall='every trial must reach target; no successful point synthesized when none qualifies',
            selection='greatest median QPS among qualified ef settings',
            noise='3 max trial MAD <= 5% baseline median',
            resources='current process incl. percentile aggregation; report separately from search timing'))


CPU=('user_cpu_seconds','system_cpu_seconds')
IO=('read_bytes','write_bytes','cancelled_write_bytes')
METRICS=('engine','ef_search','run','dataset_size','dimension','query_count','duration_seconds',
    'query_latencies_us','queries_per_second','latency_us','query_latency_p50_us',
    'query_latency_p95_us','query_latency_p99_us','recall_at_10','tie_aware_recall_at_10',
    'native_search_latency_us','python_binding_residual_us')


def resource(value):
    points={label:dict(cpu={k:numeric(value[label][k]) for k in CPU},
        io={k:numeric(value[label]['io'][k]) for k in IO}) for label in ('before','after')}
    delta={k:numeric(value['delta'][k]) for k in CPU+IO}
    for kind,keys in (('cpu',CPU),('io',IO)):
        for key in keys:
            require(delta[key]==points['after'][kind][key]-points['before'][kind][key],'counter difference invalid')
            if kind=='io':require(all(type(x)is int for x in (delta[key],points['before'][kind][key],points['after'][kind][key])),'noninteger I/O')
    rss={label:{k:numeric(value['rss'][label][k]) for k in ('rss_bytes','high_water_bytes')}
        for label in ('before_reset','after_reset','after')}
    require(all(type(n)is int for point in rss.values() for n in point.values()),'noninteger RSS')
    require(all(v['high_water_bytes']>=v['rss_bytes'] for v in rss.values()),'RSS counters invalid')
    start,end=rss['after_reset']['high_water_bytes'],rss['after']['high_water_bytes']
    peak=value['rss']['kernel_reported_peak_rss_bytes']
    require(type(peak)is int and peak==max(start,end),'RSS peak differs')
    require(value['rss']['kernel_high_water_decreased'] is (end<start),'RSS decrease flag differs')
    return dict(**points,delta=delta,rss=dict(**rss,kernel_reported_peak_rss_bytes=peak,kernel_high_water_decreased=end<start))


def select(cell,record,truth):
    require(type(cell['trial'])is int and cell['trial'] in range(3) and cell['subject'] in SUBJECTS,'invalid coordinate')
    canonical=next(c for c in plan('full') if (c['subject'],c['trial'])==(cell['subject'],cell['trial']))
    measurement={k:record['measurement'][k] for k in METRICS}
    predictions={p:record['predictions'][p] for p in ('before','after')}
    verify_point(canonical,measurement,predictions,truth['truth'],truth['acceptable'])
    # Schema selection alone is insufficient for unchecked containers: validate
    # the numeric native observations and their relationship to the summary.
    native=[{k:row[k] for k in ('nodes_visited','distance_computations','search_time_us')}
        for row in record['native_diagnostics']]
    if cell['subject'] in ('hnswlib','faiss-hnsw'):
        require(native==[],'unexpected native counters')
    else:
        require(len(native)==200 and all(type(n)is int and n>=0 for row in native for n in row.values()),'invalid native counters')
        require(all(row['nodes_visited']>0 and row['distance_computations']>0 for row in native),'native path missing')
        require(statistics.median(row['search_time_us'] for row in native)==measurement['native_search_latency_us'],'native summary differs')
    require(record['resources']['index']==EF_VALUES.index(measurement['ef_search']),'resource coordinate differs')
    return dict(subject=cell['subject'],trial=cell['trial'],measurement=measurement,
        predictions=predictions,native_diagnostics=native,resources=resource(record['resources']))


def validate_public(row,truth):
    value=row['resources']
    private=dict(before=dict(**value['before']['cpu'],io=value['before']['io']),
        after=dict(**value['after']['cpu'],io=value['after']['io']),delta=value['delta'],rss=value['rss'],
        index=EF_VALUES.index(row['measurement']['ef_search']))
    require(select(row,dict(row,resources=private),truth)==row,'unexpected public field')


def summarize(points,truth):
    require(len(points)==75,'full point inventory required')
    for point in points:validate_public(point,truth)
    rows=[dict(subject=p['subject'],trial=p['trial'],**{k:v for k,v in p['measurement'].items() if k!='query_latencies_us'}) for p in points]
    comparison=compare(rows)
    costs={}
    for subject in SUBJECTS:
        costs[subject]={}
        for ef in EF_VALUES:
            selected=sorted((p for p in points if p['subject']==subject and p['measurement']['ef_search']==ef),key=lambda p:p['trial'])
            trials=[dict(trial=p['trial'],**p['resources']['delta'],rss_peak_bytes=p['resources']['rss']['kernel_reported_peak_rss_bytes']) for p in selected]
            costs[subject][str(ef)]=dict(trials=trials,medians={k:statistics.median(t[k] for t in trials) for k in CPU+IO+('rss_peak_bytes',)})
    return dict(comparison=comparison,resources=costs,measured_queries=sum(p['measurement']['query_count'] for p in points))


def verify(directory):
    manifest=json.loads((directory/'manifest.json').read_bytes())
    require(manifest['schema']=='alopex.public-hnsw-search/v1' and manifest['points']==75,'invalid public manifest')
    raw=(directory/'truth.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest()==manifest['truth_sha256'],'truth identity differs')
    truth=json.loads(raw);require(set(truth)=={'truth','acceptable'},'unexpected oracle field')
    require(len(truth['truth'])==len(truth['acceptable'])==200,'oracle query count differs')
    entries=manifest['raw_files'];require(len(entries)==75,'raw inventory differs')
    expected={f'raw/{s}-trial{t}-ef{e}.json.gz' for s in SUBJECTS for t in range(3) for e in EF_VALUES}
    require({r['path'] for r in entries}==expected,'raw path differs')
    points=[]
    for item in entries:
        data=(directory/item['path']).read_bytes()
        require(len(data)==item['size'] and hashlib.sha256(data).hexdigest()==item['sha256'],'raw identity differs')
        with gzip.open(directory/item['path'],'rb') as stream:raw=stream.read(64_000_001)
        require(len(raw)<=64_000_000,'raw exceeds bound');point=json.loads(raw)
        require(item['path']==f"raw/{point['subject']}-trial{point['trial']}-ef{point['measurement']['ef_search']}.json.gz",'point identity differs')
        points.append(point)
    result=summarize(points,truth);data=(directory/'comparison.json').read_bytes()
    require(hashlib.sha256(data).hexdigest()==manifest['comparison_sha256'] and json.loads(data)==result,'public recalculation differs')
    return dict(status='verified',points=len(points),measured_queries=result['measured_queries'])


if __name__=='__main__':print(json.dumps(verify(Path(__file__).resolve().parent)))
