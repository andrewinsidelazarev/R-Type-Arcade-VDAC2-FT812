"""Изолированный профиль патченного Unreal: дампы не затрагивают общий запуск."""
from pathlib import Path
import argparse
import re

from translator_paths import ROOT, BUILD
DEST=BUILD/'NativeCheck'
SOURCE=Path('E:/zx/unreal_x64')

def main():
    global DEST
    parser=argparse.ArgumentParser()
    parser.add_argument('--visible',action='store_true',help='Отдельный профиль просмотра на рабочем столе')
    args=parser.parse_args()
    if args.visible: DEST=BUILD/'Preview'
    DEST.mkdir(parents=True,exist_ok=True)
    config=(SOURCE/'Unreal.ini').read_text(encoding='cp1251')
    config=re.sub(r'(?mi)^DIR=.*$',lambda _: 'DIR='+str(DEST),config)
    # ROM остаются по проверенному физическому пути; диски для этого демо не нужны.
    config=re.sub(r'(?mi)^(\w+)=rom\\',lambda m:m[1]+'='+str(SOURCE/'rom')+'\\',config)
    for key in ('SDCARD','Image0','Image1'):
        config=re.sub(r'(?mi)^'+key+r'=.*$',key+'=',config)
    config=re.sub(r'(?mi)^HideConsole=.*$','HideConsole='+('0' if args.visible else '1'),config)
    (DEST/'Unreal.ini').write_text(config,encoding='cp1251')
    print(DEST/'Unreal.ini')

if __name__=='__main__': main()
