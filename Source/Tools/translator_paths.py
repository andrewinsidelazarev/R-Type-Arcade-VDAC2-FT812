"""Изолированный каталог сборки: проверка новой версии не трогает запущенную."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = (ROOT / os.environ.get('RTYPE_TRANSLATOR_BUILD', 'Build/TranslatorDemo')).resolve()
if not BUILD.is_relative_to((ROOT / 'Build').resolve()) or BUILD == (ROOT / 'Build').resolve():
    raise ValueError('Каталог транслятора должен быть отдельной папкой внутри Build')
