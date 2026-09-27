"""Проверка живого SPG через файловый диагностический API патченного Unreal."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import time

from translator_paths import ROOT, BUILD
DIAG=BUILD/'NativeCheck'

def snapshot():
    request=DIAG/'dump.req'
    dump=DIAG/'statedump.bin'
    before=dump.stat().st_mtime_ns if dump.exists() else 0
    request.write_text('00\n',encoding='ascii')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        if not request.exists() and dump.exists() and dump.stat().st_mtime_ns!=before:
            data=dump.read_bytes()
            if len(data)==32768:
                # Адреса публичных полей берутся из linker map, не угадываются.
                import re
                symbols={m[2]:int(m[1],16) for m in re.finditer(
                    r'^\s*([0-9A-Fa-f]{8})\s+_(frame|demo_fault|player|wave)\b',
                    (BUILD/'demo.map').read_text(encoding='latin1'),re.M)}
                return dict(time=time.monotonic(),frame=struct.unpack_from('<H',data,symbols['frame'])[0],
                    fault=data[symbols['demo_fault']],tick=struct.unpack_from('<H',data,0x210a)[0],
                    line_cost=struct.unpack_from('<H',data,0x210c)[0],stack_canary=data[0x3c00],
                    charge=struct.unpack_from('<i',data,symbols['player']+16)[0],
                    wave_active=struct.unpack_from('<i',data,symbols['wave']+32)[0])
        time.sleep(.02)
    raise RuntimeError('Патченный Unreal не ответил на запрос дампа')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exercise-input',action='store_true',help='Только для собственного изолированного диагностического запуска')
    parser.add_argument('--wait-ready',action='store_true',help='Дождаться входа свежего экземпляра в игровой цикл')
    args=parser.parse_args()
    sealed=hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()
    samples=[]; release_probes=[]
    try:
        if args.wait_ready:
            deadline=time.monotonic()+20
            while True:
                sample=snapshot()
                if sample['stack_canary']==0xa5 and sample['fault']==0 and 1<=sample['tick']<=1100:
                    break
                if time.monotonic()>=deadline: raise RuntimeError('Нет входа в игровой цикл: '+repr(sample))
                time.sleep(.1)
        for i in range(16):
            if i: time.sleep(2)
            sample=snapshot()
            assert sample['fault']==0,sample
            assert sample['stack_canary']==0xa5,sample
            assert sample['line_cost']<=1209,sample
            samples.append(sample)
            print(sample,flush=True)
            if args.exercise_input:
                # Удержание и отпускание ЛКМ через документированный API эмулятора.
                (DIAG/'vmouse.bin').write_bytes(struct.pack('<BBii',1,1 if i%3==0 else 0,0,0))
                if i%3==1 and sample['charge']>=104:
                    deadline=time.monotonic()+.8
                    while time.monotonic()<deadline:
                        probe=snapshot()
                        if probe['wave_active']:
                            release_probes.append(probe)
                            break
                        time.sleep(.01)
    finally:
        if args.exercise_input:
            (DIAG/'vmouse.bin').write_bytes(struct.pack('<BBii',0,0,0,0))
    advanced=sum((b['tick']-a['tick'])%1100 for a,b in zip(samples,samples[1:]))
    elapsed=samples[-1]['time']-samples[0]['time']
    assert advanced>0,'Игровой счётчик остановился'
    if args.exercise_input:
        assert any(s['charge']>0 for s in samples),'Не наблюдался заряд от тестового ввода'
        assert release_probes,'Не наблюдался выпуск Wave после отпускания ЛКМ'
    assert hashlib.sha256((BUILD/'rtype_vdac2.spg').read_bytes()).hexdigest()==sealed,'Сборка изменена во время проверки'
    report=dict(samples=samples,advanced=advanced,elapsed=elapsed,measured_ticks_per_second=advanced/elapsed,
                loop_crossings=sum(b['tick']<a['tick'] for a,b in zip(samples,samples[1:])),
                exercised_input=args.exercise_input,release_probes=release_probes,spg_sha256=sealed)
    (BUILD/'native_check.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('measured_ticks_per_second',report['measured_ticks_per_second'],flush=True)

if __name__=='__main__': main()
