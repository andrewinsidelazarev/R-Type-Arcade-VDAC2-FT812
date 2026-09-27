"""Параллельная покадровая проверка: логика непрерывна в каждом процессе."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from translator_paths import ROOT, BUILD


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,default=min(4,os.cpu_count() or 1))
    parser.add_argument('--frames',type=int,default=1108)
    args=parser.parse_args()
    assert 1<=args.workers<=args.frames
    digest=hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()
    def work(index):
        first=args.frames*index//args.workers+1
        last=args.frames*(index+1)//args.workers
        name=f'scenario_parts/part_{index}.json'
        process=subprocess.run([sys.executable,str(ROOT/'Source/Tools/check_translator_demo_scenario.py'),
            '--frames',str(args.frames),'--render-from',str(first),'--render-to',str(last),'--report-name',name],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        if process.returncode:
            raise RuntimeError(f'Участок {first}..{last}:\n{process.stdout}\n{process.stderr}')
        result=json.loads((BUILD/name).read_text(encoding='utf-8'))
        assert result['spg_sha256']==digest
        print(f'Проверен участок вывода {first}..{last}; логика 1..{args.frames}',flush=True)
        return result
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        reports=list(pool.map(work,range(args.workers)))
    timing=sorted((t for r in reports for t in r['timing']),key=lambda t:t['tick'])
    assert [t['tick'] for t in timing]==list(range(1,args.frames+1))
    result={**reports[0],'render_range':[1,args.frames],'rendered_frames':len(timing),'timing':timing,
        'workers':args.workers,'max_line_cost':max(t['line_peak'] for t in timing),
        'max_stack_bytes':max(r['max_stack_bytes'] for r in reports),
        'worst_logic_tstates':max(t['logic'] for t in timing),
        'worst_render_tstates':max(t['render'] for t in timing),
        'worst_combined_tstates':max(t['logic']+t['render'] for t in timing)}
    assert hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()==digest
    (BUILD/'scenario_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({k:v for k,v in result.items() if k not in ('timing','source_sha256')},flush=True)


if __name__=='__main__': main()
