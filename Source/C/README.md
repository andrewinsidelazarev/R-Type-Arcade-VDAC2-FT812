# C backend Python -> TS-Config / FT812

`generated/rtype_python_compiled.c`, `generated/rtype_python_hq_templates.*`,
`generated/rtype_python_draw_vm.*`, `generated/rtype_python_draw_state.*`,
`generated/rtype_python_render_order.*` и `generated/rtype_python_draw_plan.*`
создаются только транслятором из Python, который запускает корневой
`run_python.cmd`. Ручная игровая логика в сгенерированные файлы не добавляется.

`rtype_python_draw_vm.c` — выбранный компактный lowering того же DrawPlan IR.
Действия и условия хранятся как сжатая DAG-программа (34 действия, 79 узлов,
815 байт логических таблиц), а не как вручную написанный switch. Закреплённый
SDCC даёт `_CODE = 0x1195` (4501 байт), `_DATA = 0`, то есть 11883 байта
остаются в одной 16-КиБ странице до target adapter/runtime. VM получает каждый
объект через source-derived provider в один 28-байтовый working view; копия
всех 96 slots на кадр не создаётся. Loader вызывается один раз на объект в
preflight и один раз при emission, а его ошибка в preflight происходит до
resolver/emitter/output.

`rtype_python_render_order.c` хранит буквальный порядок Python-списка
`M72EnemyWorld.enemies`, а не порядок адресов 96 физических slots. Его
checkpoint seed и все шесть видов мутаций списка извлечены из активного AST;
неизвестная седьмая мутация останавливает генерацию. `append`, атомарный
`extend`, стабильный survivor-filter/remove и same-slot replacement сохраняют
позиции Python. Состояние занимает 191 байт, закреплённый SDCC-код — 1489
байт. Это устраняет системную ошибку Z-index после FIFO-переиспользования
slot, но live hooks остаются заблокированы до подключения draw-state sidecar.

`rtype_python_draw_state.c` — persistent sidecar для всех 96 физических
slots. В каждом slot хранится 24-байтовый набор ровно тех полей, которые
читает source-derived DrawPlan, и однобайтовый concrete-class id; четыре
`isinstance`-байта разворачиваются из сгенерированной AST class-graph таблицы
только в один 28-байтовый working view, запрошенный VM. Полное состояние
занимает 2496 байт и не копируется каждый кадр. Ручного object-type switch
нет. `bind`, `clear`, `replace_same_slot`, атомарный `patch`, field/setter-site
API и loader сначала проверяют все границы/значения; отказ не меняет sidecar
или output view. Host-C oracle прогоняет случайный порядок всех 73 Enemy-
классов через compact VM и сверяет весь поток с Python IR.

AST-аудит сейчас дал 368 прямых/неявных записей в 13 draw-полей, 17
вычисляемых `active_palette` getter-ов, пять консервативных dynamic-`setattr`
blockers и 14 lifecycle-сайтов pool bind/release/checkpoint/same-slot
replacement (включая внутренние `object_slot`-присваивания).
Для каждого прямого сайта сгенерированы field id и hash32, а полный SHA-256
зафиксирован в JSON. Это схема для буквального lowering, но сами target hooks
ещё отсутствуют, поэтому `live=false`. Закреплённый SDCC даёт sidecar
`_CODE=4957`, `_DATA=0`, состояние 2496 байт; linked VM+order+sidecar,
stack/tstates по-прежнему должны доказываться вместе перед live-включением.

Полный Z-order отдельно фиксируется `pyz80.frame-render-plan.v1`, извлечённым
из активного `Game.render`. В текущем плане `stage.draw_back` (включая
звёздный/задний слой) имеет ordinal 1 сразу после `target.fill`; enemy, Force,
Bits, игрок и оружие идут выше, `stage.draw_front` — перед HUD, а `DIST` —
последний слой. Перестановка фона или добавление неизвестного target-вызова
останавливает трансляцию вместо молчаливого изменения Z-index.

`rtype_python_draw_plan.c` — читаемый развернутый двухпроходный producer и
диагностический семантический оракул. Он получает
нормализованные object/transient views и выдаёт строго упорядоченные
8-байтовые записи `(bank_key, descriptor, anchor_x, anchor_y)`. Его порядок,
ветви, `isinstance`, overlay и transient-записи выведены из
`M72EnemyWorld.draw` и побайтово сверены с Python IR oracle. Любая ошибка
первого прохода оставляет output неизменным. Потоковый entry point выполняет
тот же callback-free preflight, а затем передаёт записи по одной строго в
Python-порядке, поэтому полный массив записей кадра ему не нужен.

`ft812/pyz80_draw_chunker.*` принимает этот поток в буфер, размер которого
задаёт target adapter, и вызывает flush на границах пакетов. Неудачный flush
останавливает обход до копирования следующей записи; уже заполненный пакет
остаётся доступен для диагностики. Таким образом прежнее предположение
«не более 32 записей в кадре» больше не является условием корректности памяти.
Отдельно всё ещё требуется доказать суммарный RAM_DL/временной бюджет кадра.

`ft812/pyz80_draw_fast_chunker.*` — отдельный bounded-мост от выбранной
compact VM к 6-байтовому `PyZ80FtTemplateDrawRecord`. Каждая неизменяемая пара
`(bank_key, descriptor)` разрешается только сгенерированным HQT3 hash через
`PyZ80FT_FindHQTemplate`; ручной mapping нет. Порядок не сортируется, полный
массив кадра не создаётся, а production-submit вызывает
`PyZ80FT_BuildSpriteBatchFast`. Диагностика раздельно фиксирует принятый VM-
префикс и префикс целиком опубликованных пакетов; lookup miss, нулевая/слишком
большая capacity, переполнение счётчиков и отказ submit останавливают поток.
Host-C oracle сравнивает 273 записи (все 40 HQT3 templates и seeded-набор с
отрицательными/одинаковыми координатами) одновременно с Python-ожиданием и
8-байтовым literal bridge. Закреплённый SDCC даёт bridge `_CODE=1828`,
`_DATA=0`; аддитивная верхняя граница VM+bridge равна 6329 байтам.

Изолированный Z80 microbenchmark измеряет 2674 такта на обычную запись и
88007 тактов на 32 записи с одним target-neutral submit, ещё без тела fast
batch. Это измерение, а не разрешение live: реальный object provider, очередь,
frame composition и полный stack/tstate budget не подключены; кроме того,
текущий SDCC-путь сохраняет SP/IX, но использует IY, значит будущий live-call
adapter обязан явно соблюдать resident IY contract.

Оба producer и chunker пока не включены в live SDCC link: транслятор явно
выбирает compact VM, но фиксирует
`live_target_performance_and_size_certified=false`, пока не сгенерированы
source-derived object-layout adapter, граница стека, полный link-size и
целевой сертификат тактов кадра. Сам факт успешной host/SDCC-компиляции не
снимает этот запрет.

Стек compact VM анализируется по assembly закреплённого SDCC, включая CFG,
return-addresses, локальные frames, jump tables и рекурсивный evaluator.
Текущий внутренний максимум — 241 байт для `produce` и 239 для `stream`;
логическая глубина DAG 4 не подменяет этот байтовый расчёт. Полная граница
пока отсутствует: loader, два resolver-а и emitter обязаны предоставить свои
отдельные stack-контракты, после чего анализатор скомпонует общий максимум.

Текущий unrolled producer отдельно измерен тем же закреплённым SDCC:
`_CODE = 0x551C` (21788 байт), то есть уже на 5404 байта больше целой
16-КиБ страницы ещё до FT812 runtime. Этот отрицательный сертификат хранится
в `Build/rtype_python_draw_c_size_status.json` и привязан к SHA-256 исходника и
заголовка. Поэтому live-вариант должен использовать компактное представление
того же IR, а не пытаться молча линковать этот диагностический producer.

`ft812/` содержит универсальную C-границу аппаратного backend:

1. транслятор исполняет только asset/descriptor-часть активного Python и строит
   точные HQ-шаблоны без ручного перечисления игровых объектов;
2. C-lowering сохраняет исходный Z-order `Game.render` в виде одного готового
   потока 32-битных команд FT812;
3. страницы `#ED/#EE` дают две независимые очереди кадров; `#EF` зарезервирована
   под аппаратные шаблоны;
4. resident-код выполняет только переключение MMU и пакетную DMA-передачу;
   масштабирование, выбор bitmap source и отрисовку выполняет FT812.

Многоклеточный Python descriptor не разворачивается Z80 в пару команд на
каждую ячейку. Транслятор заранее строит фазово-точные неизменяемые DL-блоки,
удаляет их дубликаты и кладёт их сразу после HQ pixels в `RAM_G`. Runtime
добавляет только `VERTEX_TRANSLATE_X`, `VERTEX_TRANSLATE_Y` и один
`CMD_APPEND`. Фазы выбираются по Python-положительному `x % 5`, `y % 5`,
поэтому раскрытый FT812-поток совпадает с прямыми `VERTEX2F` и для
отрицательных координат.

Очередь имеет транзакционную границу: `QueueInitialize` один раз публикует
страницу как `FREE`, `QueueAcquire` атомарно переводит только
`FREE → BUILDING`, а `QueueCommit` последней записью публикует `READY`.
При нехватке места целый шаблон отклоняется, частичный sprite в поток не
попадает. `DISPLAY` и `CMD_SWAP` добавляются только `QueueCommit`.

Живой renderer можно переключать только целым кадром после автоматически
доказанного покрытия всех Python draw-примитивов. Отсутствующий descriptor
является ошибкой трансляции; смешивание нового `CMD_APPEND`-кадра со старым
потоком или ручной fallback запрещены, поскольку второй `CMD_DLSTART` разрушит
порядок слоёв.

Проверка display list использует физический предел `HCYCLE * PCLK = 1344`, но
рабочий предел равен 90% — `1209` тактов на строку. Превышение `1209` или
лимита RAM_DL в 2048 слов является ошибкой сборки. Полный кадр может быть
больше usable CMD FIFO: resident DMA обязан делить его на порции не более
4092 байт, не разрывая 32-битную команду FT812.

Whole-frame certificate имеет формат
`pyz80-ft812-frame-fragment-budget-v4`. Он hash-привязан не только к
`Game.render` и всему ASM-дереву, но и к выбранной цепочке compact VM → HQT3
lookup → six-byte fast batch. Помимо RAM_DL и 1209 тактов он требует полного
count/lookup/append preflight до первого `READY` и атомарного commit всего
кадра. Текущий bridge допускает диагностический published prefix, поэтому
сертификат намеренно остаётся `BLOCKED_MISSING_TRANSLATOR_CERTIFICATE`; число
128 является только ёмкостью chunk и никогда не подставляется как предел
кадра.

Каталог `Build` содержит только результаты компиляции и отчёты.
