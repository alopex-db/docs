#!/usr/bin/env python3
"""Recalculate this public DataFrame report from every allowlisted raw sample."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

CASES=('construct','compute','convert','complete')
SUBJECTS=('published','before','candidate','polars')
METRICS=('user_cpu_seconds','system_cpu_seconds','read_bytes','write_bytes','cancelled_write_bytes')


def require(value,message):
    if not value:raise ValueError(message)


def numeric(value):
    require(type(value) in (int,float) and math.isfinite(value) and value>=0,'invalid numeric metric')


def decision(before,after):
    base,now=statistics.median(before),statistics.median(after)
    base_mad=statistics.median(abs(v-base) for v in before);now_mad=statistics.median(abs(v-now) for v in after)
    noise=3*max(base_mad,now_mad);ratio=now/base;noisy=noise>base*.05
    return dict(baseline_median=base,candidate_median=now,baseline_trial_mad=base_mad,candidate_trial_mad=now_mad,
        noise=noise,latency_ratio=ratio,status='pending_noise' if noisy else 'regression' if ratio>1.05 else 'within_tolerance',
        increase=now>base,improvement_fraction=(base-now)/base,exceeds_regression_threshold=ratio>1.05,
        improvement_proven=not noisy and (base-now)/base>=.05 and base-now>noise and all(c<b for b,c in zip(before,after)),
        paired_ratios=[c/b for b,c in zip(before,after)])


def verify(root):
    manifest=json.loads((root/'manifest.json').read_bytes());summary=json.loads((root/'comparison.json').read_bytes())
    require(manifest['schema']=='alopex.public-dataframe-report/v1' and manifest['cells']==48 and manifest['samples']==1008
        and manifest['rows']==34250 and manifest['warmups_per_cell']==3 and manifest['samples_per_cell']==21 and manifest['trials']==3,
        'fixed comparison dimensions differ')
    require(hashlib.sha256((root/'comparison.json').read_bytes()).hexdigest()==manifest['comparison_sha256'],'comparison hash differs')
    require(set(summary)==set(CASES) and len(manifest['raw_files'])==4,'case coverage differs')
    require(set(manifest['subjects'])=={'published','before','candidate'},'subject inventory differs')
    for source in manifest['subjects'].values():
        require(set(source)=={'source_commit','source_tree','wheel_sha256','assets_sha256'},'unexpected identity field')
        for key,value in source.items():require(re.fullmatch('[0-9a-f]{'+('40' if key.startswith('source_') else '64')+'}',value),'invalid source hash')
    all_rows=[];paths=set()
    for record in manifest['raw_files']:
        name=record['path'];require(name in {'raw/'+c+'.ndjson' for c in CASES} and name not in paths,'unexpected raw file');paths.add(name)
        data=(root/name).read_bytes();require(hashlib.sha256(data).hexdigest()==record['sha256'] and len(data)==record['size'],'raw hash/size differs')
        rows=[json.loads(line) for line in data.splitlines()];require(len(rows)==record['samples']==252,'sample count differs')
        for row in rows:
            require(set(row)=={'case','subject','trial','sample','seconds','delta','rss'} and name=='raw/'+row['case']+'.ndjson'
                and row['subject'] in SUBJECTS and type(row['trial']) is int and row['trial'] in range(3)
                and type(row['sample']) is int and row['sample'] in range(21),'invalid public row')
            numeric(row['seconds']);require(row['seconds']>0,'invalid duration')
            require(set(row['delta'])==set(METRICS),'unexpected counter')
            for key,value in row['delta'].items():
                numeric(value)
                if key.endswith('_bytes'):require(type(value) is int,'noninteger I/O')
            rss=row['rss'];require(set(rss)=={'before_reset','after_reset','after','kernel_reported_peak_rss_bytes','kernel_high_water_decreased'},'unexpected RSS field')
            for key in ('before_reset','after_reset','after'):
                point=rss[key];require(set(point)=={'rss_bytes','high_water_bytes'},'unexpected RSS snapshot field')
                for value in point.values():numeric(value);require(type(value) is int,'noninteger RSS')
                require(point['high_water_bytes']>=point['rss_bytes'],'inconsistent RSS snapshot')
            start,end=rss['after_reset']['high_water_bytes'],rss['after']['high_water_bytes']
            require(type(rss['kernel_high_water_decreased']) is bool and rss['kernel_high_water_decreased']==(end<start)
                and rss['kernel_reported_peak_rss_bytes']==max(start,end),'RSS aggregation differs')
        all_rows.extend(rows)
    coordinates={(r['case'],r['subject'],r['trial'],r['sample']) for r in all_rows}
    require(coordinates=={(c,s,t,n) for c in CASES for s in SUBJECTS for t in range(3) for n in range(21)}
        and len(all_rows)==1008,'missing or duplicate coordinates')
    rebuilt={}
    for case in CASES:
        subjects={}
        for subject in SUBJECTS:
            trials=[]
            for trial in range(3):
                rows=[r for r in all_rows if (r['case'],r['subject'],r['trial'])==(case,subject,trial)]
                medians={key:statistics.median(r['delta'][key] for r in rows) for key in METRICS}
                medians.update(seconds=statistics.median(r['seconds'] for r in rows),rss_peak_bytes=statistics.median(r['rss']['kernel_reported_peak_rss_bytes'] for r in rows))
                trials.append(dict(medians=medians,max_phase_rss_bytes=max(r['rss']['kernel_reported_peak_rss_bytes'] for r in rows)))
            subjects[subject]=dict(trials=trials,median_of_trial_medians={key:statistics.median(t['medians'][key] for t in trials) for key in trials[0]['medians']},
                max_phase_rss_bytes=max(t['max_phase_rss_bytes'] for t in trials))
        candidate=[t['medians']['seconds'] for t in subjects['candidate']['trials']]
        comparisons={name:decision([t['medians']['seconds'] for t in subjects[name]['trials']],candidate) for name in ('published','before','polars')}
        rebuilt[case]=dict(subjects=subjects,comparisons=comparisons,
            reference_goal_met=comparisons['polars']['latency_ratio']<=1 and comparisons['polars']['status']!='pending_noise')
    require(rebuilt==summary,'summary differs from all raw samples')
    return dict(cells=48,samples=len(all_rows),raw_files=len(paths),all_summaries_match=True,release_readiness=False)


if __name__=='__main__':print(json.dumps(verify(Path(__file__).resolve().parent)))
