"""Таблицы ассемблерной отрисовки титула (Source/C/p2c/z80/p2c_z80_title.s) из title.py.

Отрисовка TitleScreen.render на Z80 — проигрыватель таблиц (вывод на кадр ~70 изображений: переведённый
цикл по знакам строк был самой дорогой частью кадра титула). Значения и порядок выводов вычисляет сам
CPython функциями title.py:
  * логотип — _logo_state, _native_x, _native_y и TitleAssets.logos для кадров 0…LAST (с кадра LAST запись
    не меняется);
  * строки — кортеж lines из исходника render и _draw_text: полный вывод строки и число выводов при v
    видимых знаках; видимых знаков max(0, (кадр − первый + 1) · 3);
  * приглашение — вызов _draw_text под prompt_visible из исходника render и константы PROMPT_*;
  * «старт запрошен» — вызов _draw_text под `if self.starting` (вместо приглашения).
Модель проигрывателя (player_blits) сверяется с TitleScreen.render на кадрах 0…VERIFY_FRAMES: любое
расхождение (изменён title.py) останавливает сборку.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

VERIFY_FRAMES = 4096
LINE_SCALE = 3                 # visible = max(0, (frame - first_frame + 1) * 3) в TitleScreen.render


class Recorder:
    """Цель вывода: запись (номер изображения, x, y) каждого blit."""

    def __init__(self, image_of) -> None:
        self.image_of = image_of
        self.blits: list[tuple[int, int, int]] = []

    def blit(self, surface, position) -> None:
        self.blits.append((self.image_of(surface), int(position[0]), int(position[1])))

    def fill(self, color) -> None:
        pass


def render_source_constants(title) -> tuple[list[tuple], tuple, tuple]:
    """Из исходника render: для каждой записи lines — (первый кадр, аргументы _draw_text после assets, где
    число видимых знаков — строка 'visible'), аргументы вывода приглашения и строки «старт запрошен»."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(title.TitleScreen.render)))
    lines = None
    loop = None
    prompt = None
    starting = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Attribute) and node.test.attr == 'starting'
                and isinstance(node.test.value, ast.Name) and node.test.value.id == 'self'):
            call = node.body[0].value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == '_draw_text'):
                raise SystemExit('title.py: под self.starting ожидался вызов _draw_text')
            starting = tuple(ast.literal_eval(argument) for argument in call.args[2:])
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'lines'):
            lines = ast.literal_eval(node.value)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == 'lines':
            loop = node
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name)
                and node.test.func.id == 'prompt_visible'):
            call = node.body[0].value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == '_draw_text'):
                raise SystemExit('title.py: под prompt_visible ожидался вызов _draw_text')
            prompt = tuple(ast.literal_eval(argument) for argument in call.args[2:])
    if lines is None or loop is None or prompt is None or starting is None:
        raise SystemExit('title.py: в TitleScreen.render не найдены lines, цикл по ним, приглашение или строка старта')
    names = [element.id for element in loop.target.elts]
    call = next((item.value for item in loop.body if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call)
                 and isinstance(item.value.func, ast.Name) and item.value.func.id == '_draw_text'), None)
    if call is None or 'first_frame' not in names:
        raise SystemExit('title.py: в цикле по lines ожидался вызов _draw_text и поле first_frame')
    records = []
    for line in lines:
        values = dict(zip(names, line, strict=True))
        arguments = []
        for argument in call.args[2:]:
            if isinstance(argument, ast.Name) and argument.id == 'visible':
                arguments.append('visible')
            elif isinstance(argument, ast.Name) and argument.id in values:
                arguments.append(values[argument.id])
            else:
                arguments.append(ast.literal_eval(argument))
        records.append((values['first_frame'], tuple(arguments)))
    return records, prompt, starting


class TitleTables:
    def __init__(self, title, assets, image_of) -> None:
        self.title = title
        self.assets = assets
        self.image_of = image_of
        self.lines, prompt, starting = render_source_constants(title)
        self.logo_last = self.find_logo_last()
        self.line_data = []
        for first_frame, arguments in self.lines:
            records, counts = self.text_records(arguments)
            self.line_data.append((first_frame, records, counts))
        prompt_recorder = Recorder(image_of)
        title._draw_text(prompt_recorder, assets, *prompt)
        self.prompt_records = prompt_recorder.blits
        starting_recorder = Recorder(image_of)
        title._draw_text(starting_recorder, assets, *starting)
        self.starting_records = starting_recorder.blits
        if title.PROMPT_BLINK_PERIOD & (title.PROMPT_BLINK_PERIOD - 1):
            raise SystemExit('title.py: период мерцания приглашения не степень двойки')

    def logo_blits(self, frame: int) -> list[tuple[int, int, int]]:
        result = []
        for glyph in range(self.title.LOGO_COUNT):
            visible, x, y = self.title._logo_state(frame, glyph)
            if visible:
                result.append((self.image_of(self.assets.logos[glyph]), self.title._native_x(x),
                               self.title._native_y(y)))
        return result

    def find_logo_last(self) -> int:
        final = self.logo_blits(VERIFY_FRAMES)
        last = VERIFY_FRAMES
        while last > 0 and self.logo_blits(last - 1) == final:
            last -= 1
        return last

    def text_records(self, arguments: tuple):
        """Полный вывод строки и число выводов при v = 0…n видимых знаках (вывод при v — начало полного).
        arguments — аргументы _draw_text после assets; 'visible' — место числа видимых знаков."""
        text = arguments[0]
        visible_total = len(text.replace(' ', ''))

        def draw(visible: int) -> list[tuple[int, int, int]]:
            recorder = Recorder(self.image_of)
            self.title._draw_text(recorder, self.assets,
                                  *[visible if value == 'visible' else value for value in arguments])
            return recorder.blits
        full = draw(visible_total)
        counts = []
        for visible in range(visible_total + 1):
            blits = draw(visible)
            if blits != full[:len(blits)]:
                raise SystemExit(f'title.py: вывод строки {text!r} при {visible} знаках — не начало полного')
            counts.append(len(blits))
        return full, counts

    def player_blits(self, frame: int, starting: bool = False) -> list[tuple[int, int, int]]:
        """Модель ассемблерного проигрывателя."""
        result = list(self.logo_blits(min(frame, self.logo_last)))
        for first_frame, records, counts in self.line_data:
            step = frame - first_frame + 1
            visible = 0 if step <= 0 else min(step * LINE_SCALE, 255, len(counts) - 1)
            result += records[:counts[visible]]
        title = self.title
        if starting:
            return result + self.starting_records
        if frame >= title.PROMPT_FIRST_FRAME and ((frame - title.PROMPT_FIRST_FRAME) & (title.PROMPT_BLINK_PERIOD - 1)) \
                < title.PROMPT_VISIBLE_FRAMES:
            result += self.prompt_records
        return result

    def verify(self) -> None:
        screen = self.title.TitleScreen(self.assets)
        for starting in (False, True):
            screen.starting = starting
            for frame in range(VERIFY_FRAMES + 1):
                screen.frame = frame
                recorder = Recorder(self.image_of)
                screen.render(recorder)
                expected = recorder.blits
                if self.player_blits(frame, starting) != expected:
                    raise SystemExit(f'таблицы титула расходятся с TitleScreen.render на кадре {frame}'
                                     f'{" (старт запрошен)" if starting else ""}')

    def constants_asm(self, page: int) -> str:
        """Include констант для p2c_z80_title.s (до области кода)."""
        title = self.title
        return '\n'.join(['; Сгенерировано p2c_title_native.py: константы отрисовки титула из title.py.',
                          f'TITLE_PAGE = {page}',
                          f'TITLE_LOGO_LAST = {self.logo_last}',
                          f'TITLE_LINES = {len(self.line_data)}',
                          f'TITLE_PROMPT_FIRST = {title.PROMPT_FIRST_FRAME}',
                          f'TITLE_PROMPT_MASK = {title.PROMPT_BLINK_PERIOD - 1}',
                          f'TITLE_PROMPT_VISIBLE = {title.PROMPT_VISIBLE_FRAMES}', ''])

    def asm(self) -> str:
        """Include данных таблиц для p2c_z80_title.s (внутри области банка)."""
        out = ['; Сгенерировано p2c_title_native.py: таблицы отрисовки титула из title.py.']

        def records(label: str, items) -> list[str]:
            lines = [f'{label}:']
            for image, x, y in items:
                for value in (image, x, y):
                    if not -32768 <= value <= 65535:
                        raise SystemExit(f'значение {value} таблицы титула вне 16 бит')
                lines.append(f'        .dw     {image}, {x & 0xFFFF}, {y & 0xFFFF}')
            return lines

        # Логотип: адрес записи на кадр 0…LAST; запись — число выводов и выводы (одинаковые записи общие).
        unique: dict[tuple, str] = {}
        index = []
        bodies = []
        for frame in range(self.logo_last + 1):
            key = tuple(self.logo_blits(frame))
            if key not in unique:
                label = f'title_logo_{len(unique)}'
                unique[key] = label
                bodies += [f'{label}:', f'        .db     {len(key)}'] + records(f'{label}_items', key)
            index.append(unique[key])
        out.append('title_logo_index:')
        out += [f'        .dw     {", ".join(index[start:start + 8])}' for start in range(0, len(index), 8)]
        out += bodies
        # Строки: первый кадр, n видимых знаков, адрес счётчиков (n + 1 байт), адрес выводов.
        out.append('title_lines:')
        for number, (first_frame, _records, counts) in enumerate(self.line_data):
            out.append(f'        .dw     {first_frame}')
            out.append(f'        .db     {len(counts) - 1}')
            out.append(f'        .dw     title_line_{number}_counts, title_line_{number}_items')
        for number, (_first, line_records, counts) in enumerate(self.line_data):
            out.append(f'title_line_{number}_counts:')
            out += [f'        .db     {", ".join(str(value) for value in counts[start:start + 16])}'
                    for start in range(0, len(counts), 16)]
            out += records(f'title_line_{number}_items', line_records)
        # min((кадр − первый + 1) · 3, 255) по шагу 0…255.
        out.append('title_scaled:')
        scaled = [min(step * LINE_SCALE, 255) for step in range(256)]
        out += [f'        .db     {", ".join(str(value) for value in scaled[start:start + 16])}'
                for start in range(0, 256, 16)]
        out.append('title_prompt:')
        out.append(f'        .db     {len(self.prompt_records)}')
        out += records('title_prompt_items', self.prompt_records)
        out.append('title_starting:')
        out.append(f'        .db     {len(self.starting_records)}')
        out += records('title_starting_items', self.starting_records)
        return '\n'.join(out) + '\n'
