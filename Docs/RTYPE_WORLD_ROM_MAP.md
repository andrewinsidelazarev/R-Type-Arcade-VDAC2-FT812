# R-Type World — карта ROM и расшифрованных процедур

Это каноническая рабочая карта буквального порта. Каждая новая HEX-расшифровка
сначала добавляется сюда, затем переносится в Python и только после проверки —
в Z80/FT812.

Источник: World ROM из `Arcade/rtype`, собранный образ
`Assets/Converted/Arcade/RTYPE_MAINCPU_REGION.bin` размером `$100000`.

## Адресация образа

| Область V30 | Адрес в CPU | Offset в собранном образе |
|---|---:|---:|
| основной код, `CS=0000` | `$0000…$FFFF` | `CPU address + $0400` |
| ROM-данные, `ES=1000` | `ES:offset` | `$10000 + offset` |
| развёрнутые метаблоки, `DS=3000` | `DS:offset` | `$30000 + offset` |

Пример: процедура V30 `$0467` начинается в файле с offset `$0867`;
таблица Stage 1 `ES:$87FA` — с offset `$187FA`.

## Формат записей расшифровки

Для каждой разобранной части ROM здесь сохраняются:

1. логический адрес V30 и offset в `RTYPE_MAINCPU_REGION.bin`;
2. точные HEX-байты процедуры или сигнатура, если процедура ещё не ограничена;
3. назначение полей RAM/объекта и буквальный алгоритм;
4. источник проверки: дизассемблирование, узкая MAME-трасса или совпадение VRAM;
5. состояние переноса: `decoded`, `Python exact`, `Z80 exact`.

Адрес кадра MAME не является игровой логикой и не переносится в runtime. Он
может быть записан только как контрольная точка для проверки результата ROM-
автомата.

## Главный кадр и скролл

| V30 | File offset | Назначение | Python |
|---:|---:|---|---|
| `$00FE` | `$04FE` | основной VBlank IRQ (IRQ0, вектор `$20`), устанавливает `DS=4000`, `ES=1000` | `Game.update` / `Stage.update` |
| `$02EE` | `$06EE` | raster IRQ (IRQ2, вектор `$22`): `STI`, выводит `$2EB8→port $80` (foreground Y) и `$2EBA→port $82` (foreground X), `IRET` | нижняя часть кадра после строки растра |
| `$00FA/$00FC` | `$04FA/$04FC` | заглушки `STI/IRET` (IRQ1) и `NOP/IRET` (IRQ3…7) | — |
| `$024E` | `$064E` | вызов интегратора `$0467`, затем обход объектов | `M72Scroll.advance` |
| `$02AE` | `$06AE` | очередь новой foreground-полосы; handler `$EA51` | `M72Tilemaps._pump`, layer 0 |
| `$02CE` | `$06CE` | очередь новой background-полосы; handler `$EA73` | `M72Tilemaps._pump`, layer 1 |
| `$0384` | `$0784` | кладёт `(handler, source, destination)` в кольцевую очередь | выполнено прямо в `_pump` |
| `$0443` | `$0843` | пишет scroll-регистры `$80/$82/$84/$86` | свойства `foreground_x/background_x` |
| `$0467` | `$0867` | четыре 24-битных интегратора scroll X/Y | `M72Scroll.advance` |

Порядок одного кадра важен: `$0443` выдаёт текущую координату, затем `$0467`
готовит следующую, после чего `$02AE/$02CE` проверяют переход бита `$40` и при
необходимости подают новую полосу tilemap. Поздняя запись `$82=0` из raster IRQ
относится только к неподвижному HUD.

### RAM скроллера (`DS=4000`)

| RAM | Размер | Значение |
|---:|---:|---|
| `$2EB6` | word | свободно бегущий счётчик VBlank |
| `$2EC0:$2EC2` | 24 bit | foreground X accumulator, Q16.8 |
| `$2EC4:$2EC6` | 24 bit | foreground Y accumulator |
| `$2EC8:$2ECA` | 24 bit | background X accumulator, Q16.8 |
| `$2ECC:$2ECE` | 24 bit | background Y accumulator |
| `$2ED0` | word | foreground X delta текущего кадра, со сменой знака |
| `$2ED2` | word | foreground Y delta |
| `$2ED4` | word | background X delta, со сменой знака |
| `$2ED6` | word | background Y delta |
| `$2EE4` | word | указатель следующей foreground-полосы Stage map |
| `$2EE6` | byte | целевой ring-column foreground |
| `$2EE7` | byte | уже загруженный ring-column foreground |
| `$2EE8` | word | указатель следующей background-полосы Stage map |
| `$2EEA` | byte | целевой ring-column background |
| `$2EEB` | byte | уже загруженный ring-column background |
| `$2EEC:$2EEE` | 24 bit | foreground X velocity |
| `$2EF0:$2EF2` | 24 bit | foreground Y velocity |
| `$2EF4:$2EF6` | 24 bit | background X velocity |
| `$2EF8:$2EFA` | 24 bit | background Y velocity |
| `$2F1A` | byte | raster/HUD scroll mode |
| `$2F4A:$2F4C` | 24 bit | общий progression accumulator, обновляется вместе с foreground X |

### Покадровая фаза `$0467` — MAME evidence 2026-08-12

Snapshot callback срабатывает до записей CPU того же номера кадра. Прямые
дампы `Build/Arcade/MAME/enemy_groundwalker_exact` дали:

| Snapshot | `$2EC0:$2EC2` | `$2F4A:$2F4C` | `$2ED0` |
|---:|---:|---:|---:|
| 1471 | `$017600` | `$077580` | `$FFFF` |
| 1472 | `$017680` | `$077600` | `$0000` |
| 1473 | `$017700` | `$077680` | `$FFFF` |
| 1474 | `$017780` | `$077700` | `$0000` |
| 1475 | `$017800` | `$077780` | `$FFFF` |

Следствия для буквального автомата:

- progression в этой точке отстаёт от foreground accumulator на `$0080`;
- `$2ED0` — отрицательный **уже выполненный** signed 9-bit шаг X, не прогноз
  следующего accumulator;
- если `$0467` не был исполнен, `$2ED0/$2ED4` не очищаются. Snapshot 4398 из
  `terrain_parent_exact` сохраняет `$2ED0=$FFFF` при неизменном progression
  `$0D2C80`. Python обязан использовать это stale RAM-значение для объектов.

Это закреплено `M72ScrollTest.test_object_scroll_state_matches_mame_snapshots`,
`test_missing_integrator_preserves_ram_delta` и wrap-проверкой signed шага.

### NEC V30 opcode `$0F 20`

В runtime есть ровно два достигнутых opcode с prefix `$0F`: `$E8EF` и
`$E909`, оба имеют bytes `0F 20` и являются двухбайтным NEC `ADD4S`.
Следующие bytes `$26 F6…` начинаются соответственно по `$E8F1/$E90B` и не
являются ModR/M. Это подтверждено `MAME 0.288 unidasm -arch nec`.
Генератор ROM-карты переопределяет именно этот V30 opcode поверх x86-16
Capstone и запрещает автопроверкой любой другой необработанный достигнутый
`$0F`; поэтому листинг больше не поглощает начало следующих инструкций.

### Полный индекс прямых DS-ссылок runtime

Ниже перечислены прямые абсолютные operands, найденные recursive traversal.
Индексированные обращения вида `[BX+table]` разбираются в тематических
разделах; эта таблица закрывает все оставшиеся literal DS offsets.

| DS | Размер | Механический контракт ROM |
|---:|---:|---|
| `$0024/$0028` | words | текущие native X/Y главного объекта R-9; читаются targeting, collision, Force и boss handlers |
| `$0039/$003A` | bytes | соответственно pending Wave level `$00…$05` для `$30FF` и однокадровый missile-fire strobe для `$3304` |
| `$003B` | byte | счётчик удержания FIRE/rearm missile: `$222C` увеличивает до `$3F`, а terminal paths `$3507/$35EB/$37D1/$38B5` очищают после завершения paired missile objects |
| `$0062` | word | при default DS — поле `+2` fixed object record `$0060`; внутри `$4FD2…$50C9` DS временно равен `$D000`, и тот же offset является attribute `$008F` первого Beam-meter VRAM tile |
| `$0064/$0068` | words | при default DS — native X/Y object record `$0060` (Force anchor), используемые missile/weapon matrix callbacks; внутри `$4FD2…$50C9` DS=`$D000`, offsets `$0064…` являются Beam-meter tile code/attribute pairs |
| `$006A` | byte | gate, проверяемый missile/weapon scheduler `$311E` |
| `$0098` | byte | общий enable gate 24 вариантов Force/Bit table-dispatch `$3959` |
| `$0099` | byte | однокадровый scratch latch callbacks матрицы `ES:$1B80…$1FFF`: setup entries ставят 1, paired update entries проверяют и очищают; общий reset `$3F22/$405E/$419A` ставит 0 |
| `$008C` | word | циклический write cursor, шаг 2 modulo `$20`, для пары 16-word history arrays X=`$1DA0`, Y=`$1D80` автомата `$2D50` |
| `$008E` | word | циклический read cursor, шаг 2 modulo `$20`, той же пары history arrays; `$2DFA/$2E34` берут прошлые X/Y для расчёта Q8 velocity |
| `$009C` | word | циклический write cursor, шаг 2 modulo `$20`, для зеркальной пары history arrays X=`$1DE0`, Y=`$1DC0` автомата `$2F11` |
| `$009E` | word | циклический read cursor, шаг 2 modulo `$20`, зеркальной пары history arrays; `$2FBB/$2FF5` берут прошлые X/Y для расчёта Q8 velocity |
| `$00A0/$00A2` | words | code/attribute последнего Beam-meter tile |
| `$00D4` | word | второй owner-pointer slot collision records; `$F4E5/$F518` сравнивают его с BP, `$F51E` освобождает |
| `$2040` | word | input word 0: P1/P2 directions и buttons, active-low после чтения port 0 |
| `$2042` | word | input word 1: Start/Coin/Service/DMA-complete, active-low после port 2 |
| `$2044` | word | DSW word после port 4 |
| `$2050/$2052` | words | предыдущий/current samples auxiliary input word, обновляемые `$01F0…$01FA` для edge detection |
| `$2EB4` | word | main IRQ/frame phase counter: увеличивается IRQ-путями `$012F/$0299`, его bits задают cadence input/credit logic |
| `$2EB8/$2EBA` | words | foreground scroll Y/X для raster IRQ `$02EE` (ports `$80/$82` ниже строки растра); `$043B/$043E` защёлкивают `$2EC5/$2EC1`, а при `$2F1A≠0` — `$2EBE` и X=0 |
| `$2EBC` | word | значение port `$06` (строка raster IRQ): `$041B` выводит его, прибавив 1 при bit 0 `$2F1A`; `$0AEA` задаёт `$016F` |
| `$2EBE` | word | foreground Y для VBlank `$0443` и raster latch при `$2F1A≠0`; `$0AF0` задаёт `$0090` |
| `$2EC1/$2EC5` | words | видимые 9-bit foreground X/Y части соответствующих 24-bit accumulators |
| `$2EDC/$2EDE` | words | head/tail 32-byte sound-command ring; bytes находятся в `$2020…$203F` |
| `$2EE0/$2EE2` | words | head/tail 96-entry object/work queue; slots pointers находятся в `$2054…$2113` |
| `$2EFC` | word | byte offset следующей записи sprite RAM; reset `$00C0`, предел `$03C8` |
| `$2EF0:$2EF2` | 24-bit signed | foreground Y velocity; boss transition `$A54A/$A55D` задаёт `$0000C0/$FFFF00` |
| `$2EF4:$2EF6` | 24-bit signed | background X velocity; Stage 3 `$C4E1…$C4F1` sign-extends direction byte в high words `$2EF5:$2EF6` |
| `$2EF8:$2EFA` | 24-bit signed | background Y velocity; `$C4F5…$C505` аналогично sign-extends direction byte в `$2EF9:$2EFA` |
| `$2F00/$2F01` | bytes | два edge counters coin/service-credit inputs; `$03A5` их периодически уменьшает |
| `$2F05` | byte | credit-input repeat timer: 0 либо `$1C` |
| `$2F06` | packed BCD byte | текущий credit count; `$05DC` делает `ADJ4A`, saturation `$99` |
| `$2F08/$2F0A` | words | два coinage display values: при ненулевом `$2F0C` startup path `$0D0B/$0D18` передаёт их в BX двум jobs `$ED3A` с destination descriptors `$0AC4/$0ACA` |
| `$2F0C` | word | P1 coinage/credit threshold used by `$055E/$0586/$05AD` |
| `$2F14` | word | исходное session word, которое пути старта за один и два кредита `$0E0B/$0E56` копируют в текущий P1 counter `$2F32`, а двухкредитный путь также в P2 counter `$2F3A` |
| `$2F18` | byte | sound-command pending/ack flag, ставится `$0124`, снимается `$028F` |
| `$2F19` | byte | packed bitmask двух credit counters, собирается `$05F5…$061D` |
| `$2F1B` | byte | flip/cocktail player-select input used by `$01BC/$0624` |
| `$2F1C` | byte | stop-mode latch из DSW/input decoder `$051F…$055D` |
| `$2F1D` | byte | session-initialized latch: `$0E65` ставит 1 перед очисткой обоих player-state blocks и выбором score buffer |
| `$2F1E` | byte | credit/start state flag, включаемый credit logic и добавляемый в port 2 output |
| `$2F1F` | byte | запрет tilemap queue pump; writer `$129B`, consumer `$E9A0` |
| `$2F20` | byte | current player selector 0/1; выбирает P1/P2 state/checkpoint/resource branches |
| `$2F21` | byte | computed player directional bitmask; bits 0/1/2/3 = horizontal/vertical directions |
| `$2F22` | byte | previous raw direction sample для edge/repeat logic |
| `$2F23/$2F24/$2F25/$2F26` | bytes | четыре per-axis movement/repeat bytes, обнуляемые `$209E…$20A6` и читаемые player handler |
| `$2F28/$2F29/$2F2A` | bytes | 24-bit RNG state, seed `$05,$01,$03`; `$EDE9` выполняет один deterministic step |
| `$2F2B` | word | latched DSW/options word; bits `$0004/$0200/$0400` управляют demo sound/coin mode/player routing |
| `$2F30` | byte | dirty foreground-cell counter; увеличивается всеми direct tile erasers и очищается frame path `$037E` |
| `$2F34/$2F36` | words | два words P1 session/checkpoint state, которые `$0E65` обнуляет вместе с P1 counters `$2F32/$2F38/$2F42/$2F44` |
| `$2F3C/$2F3E` | words | зеркальные два words P2 session/checkpoint state, которые `$0E65` обнуляет вместе с P2 counters `$2F3A/$2F40/$2F43/$2F45` |
| `$2F44/$2F45` | bytes | P1/P2 restart-availability counters: `$0F03` выбирает byte по `$2F20`; ноль ведёт прямо в `$0FB0`, ненулевое значение запускает полный restart path `$0F17…` |
| `$2F46/$2F48` | words | pointers P1/P2 packed score buffers для NEC `ADD4S` `$E8EF/$E909` |
| `$2F4D/$2F4F` | words | cached score-buffer values после `$E98D`, записываемые `$E980/$E986` |
| `$2FBF` | byte | stage-init latch, обнуляемый в конце `$F01B` |
| `$2FC0` | byte | player-death/respawn gate: set `$2333`, clear stage/player reset paths |
| `$2FC2` | byte | continue-mode flag из startup option byte, checked player handler `$2239` |
| `$2FC3` | byte | pending return-to-title/game-over transition; consumed and cleared `$2027…$2033` |
| `$2FCE/$2FCF` | bytes | два соседних per-player session bytes, которым `$0ECC…$0ED1` присваивает 1 непосредственно перед переходом директора в restart-handler `$0F03` |
| `$3060` | word | bootstrap stack/base word: initialized `$00C3`, BP получает `$3060` перед runtime far jump |
| `$3082` | word | scratch save CW внутри palette-list loader `$5541…$554C` |
| `$3084` | byte | startup gate checked `$016F` before input state initialization |
| `$3088/$308A` | words | two linked-list head/tail words updated by startup allocator `$0176…$01AF` |
| `$308C` | byte | bootstrap scratch/config byte, который initial game-director `$06F6` очищает перед sound 0 и переходом в `$0706` |
| `$308E` | word | startup configuration word, read `$0106` |

### Счёт: `$E8BD`, packed BCD и живой HUD

Уничтожение врага не меняет счётчик непосредственно. Его death-handler
создаёт task `$E8BD` и передаёт в `DX` указатель на одну из 16 четырёхбайтных
BCD-наград `ES:$86E4…$8723`. `$E8BD` выбирает P1/P2 по `$2F20`, прибавляет
награду NEC-инструкцией `ADD4S` сначала к общему счёту, затем к stage score,
ограничивает результат значением `09 99 99 99` = 9 999 999 и проверяет
порог дополнительной жизни через `$E98D`.

Полная таблица, прочитанная непосредственно из World ROM:

| Pointer | Bytes | Очки |
|---:|---|---:|
| `$86E4` | `04 00 00 00` | 4 |
| `$86E8` | `00 01 00 00` | 100 |
| `$86EC` | `00 02 00 00` | 200 |
| `$86F0` | `00 03 00 00` | 300 |
| `$86F4` | `00 04 00 00` | 400 |
| `$86F8` | `00 05 00 00` | 500 |
| `$86FC` | `00 06 00 00` | 600 |
| `$8700` | `00 07 00 00` | 700 |
| `$8704` | `00 08 00 00` | 800 |
| `$8708` | `00 10 00 00` | 1 000 |
| `$870C` | `00 15 00 00` | 1 500 |
| `$8710` | `00 20 00 00` | 2 000 |
| `$8714` | `00 50 00 00` | 5 000 |
| `$8718` | `00 80 00 00` | 8 000 |
| `$871C` | `00 00 01 00` | 10 000 |
| `$8720` | `00 50 01 00` | 15 000 |

Подтверждённые Stage-1 вызовы и перенесённые Python-награды:

| Death/collect path | `DX` | Результат |
|---:|---:|---:|
| carrier `$5811`, task call `$581A…$5820` | `$86EC` | 200 |
| pickup `$5947`, task call `$594C…$5952` | `$86F4` | 400 |
| red flyer `$59E5…$59F9` | `$86EC` | 200 |
| walker `$5C83…$5C9D` | `$86EC` | 200 |
| formation child `$5ED0…$5EE4` | `$86EC` | 200 |
| `$60BA` main object `$65E4…$65FE` | `$8704` | 800 |
| large terrain enemy `$777B…$7781` | `$86F8` | 500 |
| tracking mini-boss `$7FFF…$8019` | `$86F8` | 500 |
| animated shooter `$8733…$8747` | `$86E8` | 100 |
| terrain-aware seeker `$8AD1…$8AE5` | `$86F0` | 300 |
| Dobkeratops body `$9D10…$9D16` | `$8714` | 5 000 |

`$E9E7` преобразует четыре BCD bytes в семь символов: `$192F` извлекает
единственный старший decimal nibble, три вызова `$193A` — остальные шесть.
Python хранит общий и stage score теми же четырьмя BCD bytes, награждает только
при weapon-destruction (уход за границы очков не даёт) и выводит семь цифр
глифами M72 tile codes `$30…$39`, palette 6, из офлайн-атласа. Проверка всех
16 ROM-записей, переноса, natural cleanup и saturation входит в unit tests.
Автопилот до VBlank 2000 дал `0003200`: 16 подтверждённых `$86EC` × 200.

### Полный player/Force/Bit/missile RAM-автомат `$0033…$003F`

Это хвост фиксированной записи R-9 `DS:$0020`: `$0033` равен
`player+$13`, `$003F` — `player+$1F`. Другие fixed objects читают эти bytes
как глобальное состояние вооружения. Producers и consumers замыкаются так:

| DS | Поле R-9 | Точный контракт ROM |
|---:|---:|---|
| `$0033` | `+$13` | число Bits: pickup `$08` увеличивает byte через `ES:$281E`; `$2CE5` разрешает первый Bit при `!=0`, `$2EA6` — второй при `>=2`; оба active state снимаются при `(word[$0033]&$00FF)==0` |
| `$0034` | `+$14` | pitch/engine phase R-9 `$00…$27`, neutral `$14`; `$2182…$21B8` меняет по vertical input/возвращает к `$14`, `$21B8…$21DF` выбирает descriptor `ES:$12FA` |
| `$0035` | `+$15` | missile enable/count: pickup `$0C` увеличивает byte; paired launcher `$3304` активен при `!=0` |
| `$0036` | `+$16` | speed tier: pickup `$0A` увеличивает; `$207A` насыщает `>=5` до 4, `$20E3…$2106` выбирает Q8 X/Y deltas из `ES:$11B0`; `$58F6` запускает 16-VBlank indicator именно для этого pickup |
| `$0037` | `+$17` | pending Force upgrades: pickup type `<8` увеличивает; `$216D…$2182` за VBlank уменьшает очередь и повышает `$003E`, пока level `<3` |
| `$0038` | `+$18` | однокадровый ordinary-shot request: `$21E2…$21ED` ставит 1 по fire edge, slots `$04C0/$04E0/$0500` через `$4ED8` потребляют, `$4F07` очищает |
| `$0039` | `+$19` | pending Wave level `$00…$05`: `$23EA` записывает классификацию charge, `$30FF` получает `power=ES:$188C[level]`, `$318E` очищает request |
| `$003A` | `+$1A` | однокадровый missile-fire strobe: `$2077` очищает каждый update; новый fire edge либо `$003B==$3F` ставит 1 по `$221E…$2235`; `$3304` читает вместе с `$0035` |
| `$003B` | `+$1B` | hold/rearm counter FIRE, насыщаемый `$222C…$2233` на `$3F`; terminal paths paired missiles `$3507/$35EB/$37D1/$38B5` сбрасывают в 0 |
| `$003C` | `+$1C` | Force weapon type `$00/$02/$04/$06` из pickup; `$3939` строит индекс callback `8*(level-1)+type` |
| `$003D` | `+$1D` | Beam charge `$00…$80`, +2 за удерживаемый VBlank; `$23EA` превращает в Wave level, `$4FD2` — в HUD meter |
| `$003E` | `+$1E` | Force level `$00…$03`; `$0037` повышает с saturation 3; выбирает Force handler `ES:$1430[level]` и строку weapon matrix |
| `$003F` | `+$1F` | Force attached flag: `$2564` ставит 1 при захвате, `$25C8` очищает при detach; выбирает front/rear blocks матрицы и anchors R-9/Force |

| DS record | Роль | Доказанная цепочка handlers |
|---:|---|---|
| `$0020` | R-9 | `$1FC0 → $2027`; launch/death/respawn `$1F3D/$22CD/$2350`, основной input/fire update `$2027` |
| `$0040` | Beam orb | `$2430 → $244A → $2430`; charge `>=15`, anchor R-9 либо attached Force, исчезновение при charge 0 |
| `$0060` | Force | `$249A → $2682 → $24CE`; level `$2682/$26AD/$26D0/$26E9`; attach `$2581`, detached `$2614`, return `$24CE` |
| `$0080` | history service | `$3067 → $3070`, раз в два VBlank двигает четыре 16-word arrays `$1D40…$1DFF` |
| `$00A0/$00C0` | paired homing missiles | idle `$3304/$3364`; `$3321` пишет `$336D` в handler соседнего record; верх `$33A1↔$3512`, низ `$366D↔$37DC`; terminal `$360A/$38D4` возвращает idle |
| `$00E0` | Wave projectile | `$30FF → $31D9`; terrain/death `$32AA`, descriptor script `$32C3`, возврат `$30FF` |
| `$0100` | Wave companion geometry | `$32FB`, каждый VBlank только `$3924` |
| `$0120/$0140` | первый/второй Bit | idle `$2CE5/$2EA6`, active trail `$2D50/$2F11`, release и возврат idle при недостаточном `$0033` |
| `$0160…$0440` | 24 Force/Bit projectiles | wrappers `$395A…$3CEE`; `ES:$1B80…$1FFF` — 48 front/rear blocks × 3 levels × 4 types, 69 callbacks |
| `$0460/$0480/$04A0` | matrix support | `$3D16`, далее ROM callbacks `$3D57/$3EA7/$42B1` |
| `$04C0/$04E0/$0500` | ordinary shots | idle `$4ED8`, flight `$4F40`, terrain/death `$4FA3/$4FAC`, возврат `$4ED8` |

Paired missile chain симметрична по самим инструкциям: `$33A1` добавляет Y
`+3`, `$366D` вычитает 3; hitbox tables — `ES:$1A08/$1A10`; homing
`$3512/$37DC` использует `$1D89`, Q8 vectors `ES:$1A98`, offsets
`ES:$1A58`, sprites `ES:$1AF0`, exhaust `ES:$1B50`. RNG sites
`$3342/$3384` независимо задают delay `($EDE9&$3F)+$30`. Target `$336D`
включён в fixed-point отдельным проверяемым edge
`$3321: [BP+$20]←$336D`, поэтому `$336D/$366D/$37DC/$38D4` больше не
теряются как data.

### Контракты ранее неименованных direct-call entries

Эти entry points были найдены control-flow, но раньше не встречались как
отдельные literals в карте. Здесь фиксируется их механическая роль по
instructions и callers; тем самым каждый из 206 достигнутых V30 function
entries имеет semantic-map context. После автоматического раскрытия записей
новых object handlers тот же индекс включает и дополнительные состояния ниже.

| Entry | Контракт |
|---:|---|
| `$0320` | извлечь byte из 32-byte sound ring `$2020`, отфильтровать команды по текущему main handler/DSW и записать допустимую команду в port 0 |
| `$041B` | внутренняя точка цикла очистки неиспользованного хвоста sprite RAM: шаг 8 до `$03C0`, обнуление words `+4/+6` |
| `$051F` | декодировать DSW stop-mode `$2044&$2000` и Start bits `$2042&3`, вести latch `$2F1C`, вернуть carry=активно |
| `$055E` | обработать Coin 1/2 edges, coinage counters и packed-BCD credits `$2F06` |
| `$05D0` | увеличить coinage subcounter; при достижении threshold вызвать `$05DC` |
| `$05DC` | добавить credits с `ADJ4A`, saturation `$99`, отправить sound command `$63` |
| `$05F5` | каждые 16 IRQ уменьшить coin pulse counters `$2F00/$2F01` и собрать mask `$2F19` |
| `$061E` | собрать output word port 2 из player-select, flip/cocktail и credit flags |
| `$0653` | очистить неиспользованный хвост sprite RAM от `$2EFC` до `$03C0` |
| `$14E7` | сравнить четыре bytes в обратном направлении; carry clear только при полном равенстве |
| `$191B` | проверить шестибайтовую ASCII-строку на заполнение `$30`; при полном заполнении заменить её `$11` |
| `$192F` | разложить младший BCD nibble в ASCII и двигать source назад/destination вперёд |
| `$193A` | разложить оба BCD nibble одного byte в два ASCII bytes |
| `$1BE9` | записать одну аппаратную sprite record из descriptor: signed dx/dy, code/flags и resource slot |
| `$1CA6` | вариант sprite emitter для составных/отражённых descriptors с тем же лимитом `$03C8` |
| `$1FAB` | вычислить foreground cell/value для collision probe объекта |
| `$2736` | Force collision/side selection: определить сторону от R-9, звук `$37`, переключить state `$2581` и dispatch по уровню `$003E` |
| `$2825` | одна из четырёх симметричных Force terrain probes вокруг anchor |
| `$2835` | Force terrain eraser: четыре соседние cells code `$09F6` заменить `$0FA0/0`, увеличить dirty `$2F30` |
| `$297C` | Force renderer/state `$0…3`: выбор direction phase по input `$2F21`, tables `$1440/$1458/$1470/$159E`, emission через `$1BE9` |
| `$2C58` | выбрать descriptor через pointer `ES:[BX+8]` и передать общему Force/Bit renderer `$1DE9` |
| `$2C76` | шестикадровая Force/Bit animation: phase `+$13`, таблицы `$1458/$1470`, renderer `$1DE9` |
| `$38F4` | короткоживущий scrolling player-weapon visual: foreground delta, 8-phase descriptor `$1A28`, timer и delete |
| `$3924` | общий player weapon/Force/Bit geometry dispatcher: загрузка hit extents, выбор таблиц по `$003E/$003C` и indirect state jump |
| `$4FB9` | очистить одну foreground HUD cell `$0FA0/0` и увеличить dirty `$2F30` |
| `$6788` | создать группу children/projectiles `$5000/$67D5` из восьмибайтных velocity records |
| `$77C1` | runtime большого terrain enemy `$74B4`: motion/fire/render/collision/death substate chain |
| `$8355` | runtime targeting enemy `$80E3`: table motion, flash, fire, terrain/bounds и damage chain |
| `$9DD9` | клонировать mouth-projectile `$F000/$9EC0` из координат/velocity parent projectile, resource `$3F` |
| `$E98D` | скопировать/нормализовать packed score после NEC `ADD4S`, обновить caches `$2F4D/$2F4F` |
| `$E9A0` | tilemap queue pump gate `$2F1F`; вызывает `$E9E7` для pending foreground/background strip jobs |
| `$E9E7` | подготовить strip job и dispatch в `$EA95/$EB02` для foreground/background descriptor stream |
| `$EC61` | заполнить N foreground collision/HUD records парой `code=$0019,attr=$008F` |
| `$EDD9` | установить 24-bit RNG seed `$2F28:$2F2A = $03_01_05` |
| `$F3FF` | выбрать stage/difficulty sound command из `ES:$8C0C/$8C02` и отправить через `$0303` |
| `$F43B` | создать `$0100/$F44E` timer `$0080`; caller `$F01B` использует уже загруженный priority `$FFFE` |
| `$F44E` | каждый pass удерживать invulnerability `$2FC6=1`, уменьшить timer и при нуле снять latch/удалить object |
| `$F493` | проверить collision records Force и двух Bits `$0076/$0136/$0156` через `$F578` |
| `$F4BF` | проверить пары records `$00B6/$00D6` и `$00A8/$00C8`, связать owner word `+$0C` |
| `$F525` | пройти weapon collision records начиная `$00B6`, используя `$F578`, и удалить попавший record |
| `$F560` | общий scan collision records player ammunition/Force/Bit перед точной проверкой `$F578` |
| `$076C` | terminal game/session state: palette `$8C50`, очистка `$2F1E`, sound 0, cleanup `$2FC4=1`, остановка scroll, jobs `$E883/$E8A0`, затем timer `$001F` и handler `$07DA` |
| `$0E65` | session initializer: latch `$2F1D=1`, palette type `$0F`, очистка двух player state blocks, выбор score buffer `$86B7/$86CF`, очистка 128 bytes score RAM, установка restart bytes `$2FCE/$2FCF=1`, затем `$0F03` |
| `$0F03` | выбрать P1/P2 restart counter `$2F44/$2F45`; при нуле перейти `$0FB0`, иначе остановить scroll, поставить jobs `$E865/$E8A0/$EC7B`, создать `$FF20/$0F5C` и перейти через timer `$0040` в `$0FA1` |
| `$2365` | respawn terrain helper: probe в фиксированной native точке `$00B4,$0114`, маскирование attributes прямоугольника foreground и создание continuation object `$FF20/$23C8` |
| `$2614` | detached Force flight state: input `$2F23&$40`, Q8 motion `$0672/$0689`, render `$2702`, terrain `$1EB5`, bounds; при условии возврата ставит `$24CE`, затем вызывает renderer `$2A10` |
| `$27CC` | visual object, создаваемый при detach по `$25D3`: timer/index `+$20` выбирает descriptor offset, первые десять counts anchor к Force `$64/$68`, затем к R-9 `$24/$28`; `$1BCC`, countdown и delete после исчерпания ROM sequence |
| `$2A10` | renderer четырёх Force states из `object+$12`: выбирает phase/descriptor tables `$149A…`, передаёт запись в `$1BE9` |
| `$2D50` | первый Bit trail state: `$0033>=1`, charge/repeat `$2F25/$2F26`, history `$1DA0/$1D80`, delayed anchor `$008E`, обе Q8 velocity, `$1BE9`, затем terrain `$2736` |
| `$2F11` | второй Bit trail state: `$0033>=2`, зеркальные arrays `$1DE0/$1DC0`, cursors `$009C/$009E`, инвертированный Y offset; `$0672/$0689`, `$1BE9`, `$2736` |
| `$30FF` | player-weapon scheduler object: фиксирует X=`$0040`, рассчитывает geometry `$3924`, выбирает anchor R-9 либо auxiliary object по `$0039`, читает запись `ES:$188C` по индексу `$0039`, получает resource `$09`, sound `$31` |
| `$32C3` | двухdescriptorный scripted player-weapon visual: проходит записи указателем `object+$10` и timer `+$12`; нулевая длительность освобождает resource и возвращает handler `$30FF` |
| `$336D` | инициализировать второй paired missile `$00C0`: `(R9.x,R9.y+2)`, resource `$3C`, RNG delay, direction 4, handler `$366D` |
| `$33A1` | верхний paired missile state: phase `+$13`, Q8 motion, render/terrain; homing `$3512`, terminal `$35F1` |
| `$3512` | homing state того же missile-object: `$1D89` вычисляет угол, `ES:$1A98` задаёт Q8 velocity, phase `+$12` пошагово поворачивается к целевому сектору; render/terrain продолжаются общей частью `$3564…` |
| `$360A` | terminal scrolling visual после `$35F1`: добавляет foreground delta, выбирает одну из восьми descriptor phases от timer `$001F`, затем освобождает resource и удаляет объект |
| `$362A` | построить hitbox extents для missile-object: при phase `+$13 >= $38` взять четыре extents из таблицы `ES:[SI…]`, иначе записать фиксированные extents в `object+$1F0…$1F2` |
| `$366D` | нижняя зеркальная ветвь paired missile: Y step `-3`, direction/terrain/render симметричны `$33A1`, homing `$37DC` |
| `$37DC` | homing нижнего missile: `$1D89/ES:$1A98`, hitbox `ES:$1A10`, terminal `$38BB` |
| `$38D4` | terminal visual нижнего missile: 31 VBlank descriptors `ES:$1A28`, release и возврат `$3364` |
| `$3D57` | resource-backed timed descriptor sequence: descriptor=`object+$06 + 6*timer`; после исчерпания освобождает resource и восстанавливает сохранённый handler из `object+$0A` |
| `$4F40` | Beam-meter tile updater: выбирает partial/full tile по накоплению, обновляет Q8 позицию и terrain probes, очищает HUD cells через `$4FB9`, создаёт visual `$38F4` с descriptor `$26EC` |
| `$7502` | state большого terrain enemy `$74B4`: foreground delta, motion/fire branch, render `$779E`, hitbox `$3426`, damage `$F6DA`; flash timer использует sound `$56`, death идёт `$777B` |
| `$759F` | второй state `$74B4` с теми же render/collision/death contracts и отличающимся motion/timer transition |
| `$7654` | третий state `$74B4`: продолжает terrain-relative motion и переводит обработчик в следующий fire/movement substate по ROM timer |
| `$76AC` | четвёртый state `$74B4`: render `$779E`, collision `$F6DA`, flash/death chain; transition назначает `$7719` |
| `$7719` | пятый state `$74B4`, завершающий его motion/fire cycle и возвращающий ROM-defined следующий handler; damage/death остаются `$F6DA/$777B` |
| `$7891` | runtime enemy, создаваемого `$78F8`: интегрирует обе Q8 velocity через поля `+$30/+$20`, выбирает descriptor `$346A…$349A` по знаку/величине vertical velocity и направлению |
| `$8138/$82D6` | крупный tracking enemy: каждые 32 update получает сектор через `$1D89`, читает 16-векторную Q8 матрицу `$3966`, проверяет terrain по знакам скорости; при вертикальном совмещении счётчик `+$14` переводит объект в 31-update атаку `$82D6`; на timer `$10` `$8355` создаёт flash `$83DF` и летящий child `$842C`; hitbox `$3956=(-16,+16,-20,+20)`, damage `$F6DA`; child `$842C` имеет player hitbox `$395E=(-24,+20,-2,+2)` |
| `$86EA` | runtime animated enemy `$86A6`: fire `$F63A`, foreground delta, периодический угол `$1D89`, render, collision `$F694` и bounds cleanup |
| `$875D…$893E` | Stage 2 timed spawner: parent life `$0600`, parameter script `$3AFE` меняет target Y/spawn/delay cadence поверх difficulty `$3B12`; `$8817` создаёт children resource `$2D`, initial Y с RNG; `$8861` сочетает Q8 X `$3B2A`, jitter target Y и 128-count oscillator, затем optional delay переводит в aimed `$893E` через `$1D89`, velocity root `$3B22`, direction descriptors `$3B32`, collision `$3C12`, death `$E7A6` |
| `$8490` | Stage 7 enemy `$8469`: foreground delta, Q8 `vx=-$0200`, fire `$F63A`, descriptor `$39A6`, collision `$39AC`; probe `(x-$20,y)` останавливает X на 8 update и задаёт `vy=±$0100` по `$2EB6&1`, вертикальный probe `±$18` отражает знак |
| `$85B0/$865E` | Stage 5 composite shooter `$8561`: Q8 `vx=-$0100`, 8 двухdescriptorных phases `$39CE`, HP `$1E`, flash resource `$55`; difficulty records `$39B4`, пять Y offsets `$39C4`, child `$E6AB`; death `$E817` использует resource `$01` (resource `$63` принадлежит отдельному entry `$E80C`) |
| `$67D5/$687D/$69B4` | 16-direction families: `$67D5/$687D` use collision `$2D84=(-4,+4,-4,+4)`; event `$696E` reads HP bytes `$2D8C=(3,5,8,14)`, script/count records `$92AC`, collision `$2E36=(-12,+12,-12,+12)`, а `$69B4` выбирает descriptor `$2DD0+6*direction` и один из 16 signed terrain probes `$2D90` по direction `object+$16` |
| `$89B0` | первый terrain-aware state enemy `$897E`: fire `$F63A`, четыре terrain probe; только если ни одна запрошенная ось не сдвинулась, ставит `+$22=$03FF` и handler `$8AEE` |
| `$8AEE` | отдельный зеркальный state `$897E`: инвертирует vertical target; blocked vertical branch сокращает `+$22` до 1, successful pass декрементирует его, полностью blocked pass сразу возвращает `$89B0` |
| `$95F1` | Q8 mobile enemy: velocity из `+$10/+$12`, четырёхфазный descriptor `$417E`, terrain/bounds, hitbox `$4196=(-4,+4,-4,+4)` и damage `$F694`; следующие 16 descriptors `$419E…$41FD` в этой ревизии не адресуются |
| `$9C33` | vulnerable emerge state тела Dobkeratops: отсчитывает ROM timer, выполняет body render/collision и после окончания назначает `$9C70` |
| `$9D30` | Dobkeratops body spawn pattern: RNG выбирает sound `$50…$53` и delay 1/2, затем создаёт `$EF00` children по ROM records через allocator |
| `$9E78` | Dobkeratops mouth-projectile motion: каждые два VBlank меняет Q8 Y, X уменьшается на 4, render `$44BA`, collision и bounds определяют delete/explosion path |
| `$A1A3` | Dobkeratops tentacle-tip runtime: fire `$F63A`, background delta, обе Q8 velocity, angle descriptor `$4CC6`, hitbox `$4CBE` и следующий элемент ROM motion script |
| `$E691` | explosion animation state: descriptor table `$8490 + phase`, ROM timer продвигает кадры и по завершении переводит в cleanup `$E67C` |
| `$00FE` | аппаратный VBlank IRQ entry (вектор ROM `$00080` = `$0040:$00FE`): `PUSH DS/ES`, `PUSHA`, выбирает service IRQ `$3900:$02FD` через `$308E`, иначе читает ports 0/2/4 в `$2040/$2042/$2044`, ведёт frame/input/sound/scroll paths и завершает `IRET`. Прежний адрес `$00FF` — артефакт MAME write-tap, который сообщает IP после однобайтного `PUSH DS` |
| `$09F9` | attract/title moving-object script: Q8 X/Y, composite render `$1C1B`, шестибайтные `(vx,vy,duration)` records через `object+$10`; `$8000` завершает script, credits/session latch выбирают delete/alternate path |
| `$0A63` | сокращённый attract object handler: при `$2F1D` удалить object путём `$0A43`, иначе только composite render descriptor `object+$20` |
| `$0C9F` | start-game gate: sound `$26`, cleanup `$2FC4=1`, затем handler `$0CAF` |
| `$0CAF` | дождаться пустой task ring, обнулить 16 scroll words, поставить tile/text jobs `$E8A0/$E883/$ED58/$ED3A`, создать семь `$0100/$09F9` объектов и перейти в `$0D9F` |
| `$0D9F` | countdown после start presentation: гасит `$2F1E`, снимает cleanup, запускает palette `$FB9C` и ставит handler `$0DD2` |
| `$0DD2` | поставить text job `$ED58` для descriptor `$0AEE`, затем перейти `$0DE0` |
| `$0DE0` | P1 Start gate: каждые 8 VBlank ставит `$EBF1`; при Start 1 списывает один packed-BCD credit, копирует `$2F14→$2F32`, обнуляет P2 lives и идёт `$0E65`; при двух credits готовит `$0E2A` |
| `$0E2A` | P1/P2 Start gate: Start 2 списывает два packed-BCD credits и копирует `$2F14` в оба lives words `$2F32/$2F3A`; Start 1 использует однокредитный путь `$0DFD` |
| `$3070` | каждые два VBlank пишет native Y R-9 в 16-word ring `$1D40` и X в `$1D60`, продвигая два write/read cursors modulo `$20` |
| `$30B6` | краткоживущий player/Force anchored visual: timer `+$10`, anchor выбирается `$24/$28` либо `$64/$68`, четырёхфазный descriptor `ES:$17F6`; при нуле release resource и delete |
| `$3EA7` | initializer одного weapon-matrix projectile: получает resource `$02`, копирует Force X/Y `$64/$68`, ставит active flag `+$17=1` и handler `$3EC4` |
| `$3EC4` | общий Q8 projectile handler из matrix: velocities `+$10/+$12`, descriptor pointer `+$14`, visual `$204E`, foreground terrain erase `$4FB9`, bounds `$1D6B`; три terminal paths release resource и возвращают сохранённый handler `+$0A` либо matrix cleanup `$3D17/$3D37` |
| `$42B1` | matrix object anchor initializer: optional phase `+$0C` по gate `$006A`, округляет Force `$64/$68` к сетке 8+4 и ставит `$42DD` |
| `$42DD` | scrolling pre-delay state: foreground delta, geometry `$3924`, после timer получает resource `$3D`, flash `$70`, ставит `$4311`; invalid terrain ведёт cleanup `$4481` |
| `$4311` | восьмисекторный moving/composite weapon state: deltas `ES:$2086`, четыре shifted renders `ES:$2056`, terrain probes, optional sound `$3B`, timer/linked-neighbour conditions; terminal animation `$4467` |
| `ES:$204E…$2099` | hitbox `(12,12,4,4)` для matrix projectile; восемь записей `$2056` `(terrain dx,terrain dy,branch descriptor)`; четыре точных диагональных шага `$2086=(8,8),(8,-8),(-8,-8),(-8,8)`; `$2096=(8,-8)` — неадресуемый пятый вектор |
| `$4467` | шестибайтно обратный terminal descriptor stream от `ES:$20F4`; после offset 0 release resource и восстановление handler из `+$0A` |
| `$448E` | зеркальный matrix anchor initializer: phase 0/2 по `$006A`, Force `$64/$68` округляются к 8+4, следующий handler `$44BA` |
| `$44EE` | двухфазный terrain-aware state: X delta `ES:$2096`, descriptor pointer `ES:$20A2`, toggles `+$0C^=2`, sound `$3B` для parent `$3BFE`, neighbour/flash checks; terminal `$456A` |
| `$456A` | terminal descriptor stream, общий алгоритм `$4467`, та же таблица `ES:$20F4` и возврат `+$0A` |
| `$4763` | четырёхфазный anchor/history initializer: phase по `$006A`, Force X/Y округление 8+2, копирование трёх history pairs, следующий `$479B` |
| `$479B` | pre-delay state: geometry `$3924`, resource `$3D`, flash `$70`, handler `$47C9`; invalid terrain ведёт `$491A` |
| `$47C9` | history-chain terrain state: linked object берёт три прошлые пары у предыдущей record либо интегрирует scroll+deltas `ES:$2114`; composite render/collision и terminal `$4900` |
| `$4900` | terminal descriptor stream от `ES:$21BC`, шаг назад 6 до offset 0, затем release resource и возврат `+$0A` |
| `$49CF` | четырёхчастный Force-relative composite: сторона по sign `+$14`, anchor `$64/$68±$50`, frame `+$10` и base `+$12`; четыре `$1BCC`, visual `+$0C`, симметричные `$2702` probes и ROM terminal branches |
| `$4C6A` | moving четырёхчастный composite: X+=`+$14`, frame `+$10&7`, base `+$12`, четыре `$1BCC`, visual `+$0C`, bounds/terrain/player collision; terminal release и возврат `+$0A` |
| `$4E0F` | быстрый горизонтальный Force projectile initializer: velocity `±8` и descriptor half по `$006A`, resource `$3D`, optional sound `$3F`, затем `$4E42` |
| `$4E42` | горизонтальный projectile: X+=`+$14`, blink от `$2EB6&4`, descriptor `+$0C`, visual `$26DC`, bounds, Force collision `$2736`, terrain; terminal timer `$30`/handler `$4E88` |
| `$4E88` | terminal descriptor stream от `ES:$26AC`, offset уменьшается на 6 до нуля; release resource и возврат `+$0A` |
| `$4EAF` | однокадровый visual при `(R-9.x+8,R-9.y)`: чередует descriptors `$26F2/$26F8` по `$2EB6&1`, затем release resource и delete |
| `$5D2D` | runtime enemy `$8020` от stage handler `$5CEA`: X velocity `-$0200`, 8-phase descriptor `$299A`, difficulty-0 `$298A=(-$0600,$0030)`, collision `$29CA=(-9,+9,-5,+5)`, child fire helper `$5D9A`; child `$E6AB/$E6C0` интегрирует унаследованную Q8 X velocity, рисует двухdescriptorный stream `$84CE`, collision `$84FE=(-16,+16,-4,+4)`; hit parent ставит `$E7BE`, sound `$50` и job `$E8BD/$86F4` |
| `$5D9A` | fire cadence helper `$5D2D`: countdown `+$34`, reload из `+$30`, создаёт `$6000/$E6AB` в координатах parent с velocity/parameter `+$32`, sound `$59` |
| `$5F3C` | 45 Stage 6 enemies от `$5EED`: command bits задают turn direction/mirror/speed, records `$9324` — X/Y/initial cardinal direction, speed offset `$931C`, Q8 velocity table `$2A80`, двухdescriptorный composite `$2AC0/$2AF0`, HP 10, resources `$28/$51`; трёхточечный ray `$2A40` по collision меняет direction, damage helper `$6081`, death `$E817` |
| `$6081` | две последовательные damage probes `$F6DA` с tables `$2B20/$2B30` либо `+8` variant; успешный hit ставит sound `$56` и flash counter `+$11=$1F` |
| `$69B4` | runtime terrain enemy `$8010/$69B4`: priority `$F5C1`, scroll, fire `$F63A`, descriptor `$2DD0`, terrain probe `$1E6C` с заменой VRAM `$0FA0→$09F6/$0082`, damage `$F6DA`, flash `$6A78`, death/cleanup |
| `$6A78` | hit-flash renderer `$69B4`: пока `+$3D!=0` декрементирует; раз в четыре counts временно подменяет resource `+$06` на flash resource `+$3C`, иначе обычный `$1BCC` |
| `$6EC4` | fixed large Stage 7 object `$6E9B`: `(x,y)=($0110,$0108)`, HP `$C8`, resource `$54`, scroll; probe `(x+$40,y)` через `$1EB5` разрешает Q8 `vx=$00C0`, четыре двухrecord composite roots `$3042/$304E/$305A/$3066`, collision `$3072`; смерть `$E817` плюс 18 overlapping debris pairs `$301C` в `$E7B6` |
| `$6FD0` | Stage 2 object от `$6F89`: 14-byte record `$9384` задаёт Y, две пары Q8 velocities, 16-word descriptor table и target angle; `$93BC=(-1,$80,$180,$200)` выбирает angle/timer gate; HP принудительно 10, resources `$27/$55`, collision `$31EE` |
| `$7048` | continuation `$6FD0`: foreground scroll; на terrain code `$0FA0` интегрирует primary velocity и frame `table+4`, иначе secondary velocity и 16-frame ring; hit входит на 23 update в `$7106`, death — `$E817` resource `$63` |
| `$7106` | death/terminal state той же цепочки: damage `$F6DA`, sound, resource release `$523E/$F50C`, helper `$7168` и окончательное удаление `$03EC` |
| `$7168` | flash/composite helper `$7106`: выбирает descriptor через timer/phase и вызывает `$1C1B` без изменения state |
| `$71C7` | 25 Stage 5 enemies от `$7182`: position `$8DD0`, fire `$F8A7/$F63A`, initial direction bytes `$31FE`, difficulty turn cadence `$31F6=(16,8,4,2)` и velocity roots `$320E`; active timer `$0280`, direction сдвигается на один из 16 sectors к `$1D89`, descriptor `$3216+6*direction`, collision `$3276` |
| `$72D2` | 23 Stage 6 enemies от `$7294`: `$FA75` position, command high-byte bit 0 задаёт vertical/horizontal pair, four Q8 vectors `$329E`, five-frame animation roots `$32BE`, HP 2, resources `$43/$55`; `$73A0` отражает direction bit 0 по bounds/terrain probe `$32AE`, `$73DB` создаёт aimed child `$7435` |
| `$737D` | renderer `$72D2`: phase-dependent descriptor через `$1BCC` |
| `$73A0` | terrain/bounds helper `$72D2`: probes `$1E6C/$1D6B`, возвращает flags вызывающему state |
| `$73DB` | child-shot helper `$72D2`: target angle `$1D89`, allocator `$03A6` создаёт `$7435`, получает resource `$51EE` |
| `$7435` | child projectile `$73DB`: Q8 motion от direction matrix, 4-phase `$327E` с object-slot phase, collision `$3296`; первые 8 even checks пропускают terrain, затем `$1EB5` и background threshold `$07D0`, player `$F485`, bounds; collision переходит в breakup `$E686` |
| `$7607` | initializer большого terrain enemy `$74B4`: заполняет ROM motion/damage fields и выбирает первый из states `$7502/$759F/$7654/$76AC/$7719` |
| `$780E` | child/runtime большого terrain enemy `$77C1`: Q8 motion, descriptor `$1BCC`, terrain `$1E6C`, player collision `$F694`, sound и resource cleanup |
| `$78F8` | 15 Stage 5 formation events: command high bits выбирают priority `$34AE=(4400,4300,4200,4100)`, `$F88C` задаёт position, `$F912` — общий motion root; priority threshold `$4280` выбирает 11-record stream `$34B6` либо 17-record `$34E2` |
| `$7935` | formation parent от `$78F8`: countdown pairs `handler,delay`, каждый allocator child получает текущий decrementing priority, общий X/Y и `$F5C1` root; поле `+$3C` образует linked chain newest→previous, zero delay удаляет parent в том же update |
| `$799C` | первый child initializer formation `$7935`: получает resource, задаёт стартовые phase/velocity/link fields и ставит `$79C1` |
| `$79C1` | первый child runtime: priority `$F5C1`, damage `$F6DA`, renderer `$7D45`, timer/motion state transitions и sound |
| `$7A1E` | повторяющийся child initializer formation: получает resource и переводит child в `$7A3F` с ROM position/phase fields |
| `$7A3F` | основной formation child runtime: resource `$26`, HP 6; читает flags предыдущего link, наследует delayed cascade `previous.delay+4` с 3 commands либо входит в escape; иначе 1/2-command `$F5C1`, descriptor `$3676`, alternating damage probe `$37CE` |
| `$7AD9` | terminal child initializer из последней pair script: получает resource и переводит объект в `$7AFA` |
| `$7AFA` | terminal child runtime: resource `$25`, HP 6, тот же linked-cascade contract, descriptor `$371E`, collision `$37D6`; expiry выбирает follow root `$A3E6/$A380` по phase |
| `$7BBB` | terminal follow state: `$F5C1`, descriptor `$371E`, damage `$37D6`, общий death/cleanup `$7C3D/$7C77` |
| `$7BFC` | main follow state: `$F5C1`, descriptor `$3676`, damage `$37CE`, общий death/cleanup `$7C3D/$7C77` |
| `$7CD3` | formation escape state: `(priority & $0F)` индексирует 16 Q8 vectors `$8FD0`, animation seed берётся из `$EDE9`, bounds `$1D6B`, descriptor base `$3676/$371E`, damage `$37CE` |
| `$7D22` | общий renderer states `$7A3F…$7CD3`: phase/table descriptor и `$1BCC` |
| `$7D45` | renderer state `$79C1`: composite descriptor через `$1C1B` |
| `$7D68` | Stage 2 initializer двух variants: command bit 0 индексирует `(Y,variant)` records `$37DE`, ставит `(X=$02D0, HP=$28)`, resources `$29/$55`, collision `$3846+8*variant`, state `$7DBB` |
| `$7DBB` | approach state объекта `$7D68`: foreground scroll до `X<$0270`, damage `$F6DA`, composite helper `$8035`, затем 8-update vertical shift `$7E18` |
| `$7E18` | state 2 цепочки `$7DBB`: тот же damage/helper contract, ROM timer/position переводит `$7E80` |
| `$7E80` | state 3 цепочки `$7DBB`: damage `$F6DA`, helper `$8035`, следующая ROM ветвь `$7EEB` |
| `$7EEB` | state 4: damage, основной helper `$8035` и дополнительный `$8058`, затем `$7F49` |
| `$7F49` | state 5: damage/helper `$8035`, timer/position ведёт `$7FAD` |
| `$7FAD` | terminal state цепочки: damage, helper `$8035`, explosion job, resource release `$523E/$F50C` и delete `$03EC` |
| `$8035` | общий composite renderer цепочки `$7DBB…$7FAD`: выбирает descriptor по state phase и вызывает `$1C1B` |
| `$8058` | child-spawn helper hold-state `$7EEB`: при timer `$C0/$80` создаёт `$8D85`; difficulty 0 пропускает `$40`; variant выбирает scripts `$A434/$A45A` либо `$A484/$A4B8` и начальные Q8 velocities `(-$20,-$28)`/`(-$18,-$40)` |
| `$8F86/$90A2` | Stage 4 four-direction enemy `$8F5E`: position `$8DD0`, initial direction map `$3F76`, difficulty vectors `$3F86`, 4×4 turn-pointer matrix `$3FC6`, collision `$407E`; proximity к R-9 запускает 31-update turn, `$90E0` очищает четыре клетки `$09F6→$0FA0/0` с byte-wise BL arithmetic |
| `$83DF` | короткоживущий child `$8355`: descriptor `$1BCC`, timer/parent condition, затем release resource и delete |
| `$842C` | projectile/child `$8355`: Q8 X `$0672`, composite `$1C1B`, player collision `$F485`, bounds `$1D6B`, release/delete |
| `$85B0` | runtime `$8020` stage enemy от `$8561`: Q8 motion, composite `$1C1B`, damage `$F6DA`, helper `$865E`, jobs/sound, resource cleanup/explosion |
| `$865E` | child fire helper `$85B0`: sound и allocator `$03A6` создают ROM child с parent coordinates/velocity fields |
| `$86D3` | initializer child/animation `$86A6`: вычисляет угол к R-9 через `$1D89`, записывает ROM phase/velocity и ставит runtime `$86EA` |
| `$8798` | fixed object controller от `$875D`: вызывает два механических шага `$87BA/$8817`, удаляется по stage cleanup |
| `$87BA` | первый step `$8798`: countdown/position fields и ROM condition без внешних helpers |
| `$8817` | второй step `$8798`: RNG `$EDE9`, allocator `$03A6`, resource `$51EE`, создаёт child `$8861` |
| `$8861` | child `$8817`: RNG/angle `$EDE9/$1D89`, Q8 motion, `$1BCC`, player `$F694`, bounds, sound/job и resource cleanup |
| `$893E` | continuation state terrain-aware enemy `$897E`: Q8 motion, descriptor `$1BCC`, player collision `$F694`, bounds `$1D6B`, возврат в ROM state chain |
| `$8C2E` | state 1 timed random controller `$8C12`: sound и allocator `$03A6`; timer переводит `$8C71` |
| `$8C71` | state 2 того же controller: новый sound/allocator record и переход `$8CB1` |
| `$8CB1` | state 3: третий ROM child spawn и переход `$8CF4` |
| `$8CF4` | state 4: child spawn, terrain helper `$8D54`, затем `$8D31` |
| `$8D31` | terminal controller state: player collision `$F485`, затем delete `$03EC` по ROM условию |
| `$8D54` | terrain probe helper `$8CF4`: `$1E6C` по ROM offset, возвращает tile/carry condition |
| `$8D85` | scripted child `$8058`: resource `$3E`, flash `$55`, collision `$3F6E`, трёхcommandный `$F5C1`, foreground scroll и четырёхфазный двухrecord composite `$3F26` через `$1C1B`; завершение script или hit переводит `$8DC6` |
| `$8DC6` | 31-update morph child: four two-record descriptors `$3F3E`, после countdown ставит HP 4 и active state `$8E15` |
| `$8E15` | active `$8D85`: каждые `$80` updates выбирает ROM target `$3EE6` либо R-9, velocity равна удвоенной signed разнице координат, Q8 integration, composite ring `$3F56`, bounds `$012C…$02D3/$007C…$0193`; damage задаёт retreat `vy=-$0300`, flash и special descriptor, death `$E7BE` |
| `$8F86` | runtime `$8230` stage enemy от `$8F5E`: Q8 motion, composite `$1BCC`, player `$F694`, helper `$90E0`, bounds, sound/jobs и cleanup |
| `$90A2` | continuation state `$8F86`: descriptor `$1BCC`, player collision `$F694`, ROM motion/phase и возврат/cleanup |
| `$90E0` | terrain helper `$8F86`: ROM-offset probe `$1E6C`, возвращает tile/carry и обновляет direction fields |
| `$915B` | единственный Stage 2 event `$7404`: record `$409E` задаёт общий `$F5C1` root `$A652` и `(X,Y)=($02C8,$0130)`; command bit 2 принудительно ставит base timer `$00C0`, root priority `$201F`, cleanup ordinal 2 |
| `$91CC` | multipart parent от `$915B`: исполняет все 22 `(initializer,delay)` records `ES:$40C6…$411D`, decrementing priority и cleanup ordinal `+2`, связывает children newest→previous и удаляется на zero delay |
| `$9246` | initializer первого multipart child `$91CC`: resource `$51EE`, следующий state `$925B` |
| `$925B` | first child: resources `$40/$55`, `$F5C1`, pulse countdown `$base+$28` с reload `$base` и значением `(RNG&3)+1`, descriptor `$419E`, alternate-frame `$427C` probe; controller `$A523` ведёт staggered cleanup |
| `$92C3` | initializer второго child типа: resource `$51EE`, следующий `$92D8` |
| `$92D8` | child state 2: priority/damage/common renderer `$957C`, ROM timer/link transition |
| `$933C` | повторяемый initializer основного multipart child: resource `$51EE`, state `$9355` |
| `$9355` | 18 основных linked parts resource `$3F`: previous pulse countdown, Manhattan gate `$0090` к R-9, radial helper `$95A3`, global four-frame descriptor `$425E`, alternating player collision `$427C`; collision переводит `$9425` и создаёт `$E7BE` |
| `$9425` | multipart child continuation: priority/damage `$F6DA`, renderer `$957C`, next state from ROM links |
| `$9477` | initializer позднего multipart child: resource `$51EE`, state `$948C` |
| `$948C` | late child state: priority/damage/common renderer, переход в terminal initializer/state pair |
| `$94E1` | initializer terminal multipart child: resource `$51EE`, state `$94F6` |
| `$94F6` | terminal multipart child: priority/damage/render, explosion job, resource release `$523E/$F50C` и delete `$03EC` |
| `$957C` | общий linked multipart renderer: handler owning controller `$A3B3` на нечётном VBlank подменяет resource на `$55`, иначе обычный `$1BCC` |
| `$95A3` | восьмиchild spawn helper `$9355`: difficulty 0/other выбирает `$411E/$414E`, восемь records `(handler,vx,vy)`, каждый `$95F1` получает resource `$3F`, sound `$5D` |
| `$95F1` | radial child: literal Q8 motion, four-phase descriptor `$417E`, odd-frame terrain `$1EB5` и bounds `$1D6B`, even-frame player collision `$4196`; collision ставит `$E7AE`, natural bounds release/delete |
| `$9674` | controller от `$9660`: angle `$1D89`, allocator создаёт `$96E9`, resource `$51EE`; завершается после ROM count/script |
| `$96E9` | child `$9674`: Q8 motion, `$1BCC`, player `$F694`, bounds, sound/job, resource release/delete |
| `$9758` | final-stage callback threshold `$0340`: allocator создаёт `$983B`, выдаёт resource и ROM coordinates/phase |
| `$978D` | final-stage callback `$1000`: sound + allocator `$983B`, иной ROM record |
| `$97C7` | final-stage callback `$13C0`: sound + allocator `$983B`, третий ROM record |
| `$9801` | final-stage callback `$1780`: sound + allocator `$983B`, четвёртый ROM record |
| `$983B` | final-stage child четырёх callbacks: priority `$F5C1`, `$1BCC`, player `$F485`; ROM timer/motion переключает `$98A8` либо delete |
| `$98A8` | moving continuation `$983B`: target angle `$1D89`, Q8 motion, descriptor `$1BCC`, player `$F485` |
| `$9F18` | Dobkeratops-related projectile continuation: Q8 Y `$0689`, descriptor `$1BCC`, player `$F485`, bounds `$1D6B` и ROM terminal transition |
| `$A290` | stage/boss controller от `$A22E`: scripted timers, sound/jobs, palette `$54E4`, scroll `$5579`, child allocators; helpers `$A5A4/$A5C5`, terminal delete `$03EC` |
| `$A5A4` | helper `$A290`, создающий multipart root через stage handler `$915B` с ROM command word |
| `$A5C5` | helper `$A290`: allocator `$03A6` создаёт child `$A5EB` и заполняет его script/position fields |
| `$A5EB` | child `$A5C5`: RNG `$EDE9`, terrain `$1E6C`, ROM timer/motion; переход `$A638` |
| `$A638` | terminal child state `$A5EB`: sound по ROM condition и delete `$03EC` |
| `$A6A5` | второй child controller `$A290`: RNG, sound, allocator, затем self-delete по исчерпанию ROM records |
| `$A71D` | единственный Stage 5 event `$8C00`: RNG плюс координаты R-9 выбирают один из восьми route sets `(sum&7)*8`; создаётся controller `$A762`, обнуляются обе X-scroll velocities и звучит `$19` |
| `$A762` | создаёт upper/middle/lower bodies `$AA0F/$AB62/$ACE7` по route pointers `$5ABA`, три attached `$AC4C`, resources `$41/$42/$53`, difficulty fire timers `$5844`; затем синхронизирует bit masks 1/2/4 до exit `$A982/$A9C1` |
| `$A982` | continuation `$A762`: timer/position-only state, следующий `$A9C1` |
| `$A9C1` | terminal state `$A762`: sound, scroll/palette restore `$5579`, delete `$03EC` |
| `$AA0F` | upper body: route motion `$AFE6`, six-record composite `$5A02/$5A14`, difficulty straight shots `$AB01`, HP 40/collisions `$5A26…$5A3E`, flash `$53`, death path `$58EE` |
| `$AB01` | child-spawn helper `$AA0F`: RNG `$EDE9`, allocator `$03A6`, sound и ROM velocity/descriptor fields |
| `$AB62` | middle body: route motion `$AFE6`, six-record composite `$5A46/$5A58`, HP 40/collisions `$5A6A…$5A7A`, flash `$53`, death path `$594E` |
| `$AC4C` | три attached components: следуют за middle/lower с ROM offsets, `$1D89` выбирает orientation/descriptor pointers `$5870`, `$F8A7/$F63A` fire, исчезают через `$E7BE`, если owner handler сменился |
| `$ACE7` | lower body: route motion `$AFE6`, four-record composite `$5A82/$5A94`, lower straight shots `$ADFB`, paired ballistic debris `$AE5C`, HP 40/collisions `$5A9A…$5AB2`, death path `$59A6` |
| `$ADFB` | RNG child-spawn helper `$ACE7`: allocator `$03A6`, sound и ROM position/velocity record |
| `$AE5C` | второй spawn helper `$ACE7`: RNG, allocator `$03A6`, resource `$51EE`, parent linkage и ROM fields |
| `$AEFB` | paired debris: randomized signed horizontal Q8 `$80…$17F`, initial vertical `$280…$47F`, slot-phased descriptors `$58CE`, gravity `-$10/update`, terrain/player/pair collision `$58E6`; при vertical underflow переходит `$AF6F` |
| `$AF6F` | falling continuation debris: Q8 motion, gravity `-$10`, same descriptor ring/terrain, player `$F694`, bounds `$1D6B` |
| `$AFBF` | composite renderer helper `$AA0F`: передаёт выбранную multipart запись в `$1CA6` |
| `$AFCC` | зеркальный composite renderer helper `$AB62` через `$1CA6` |
| `$AFD9` | renderer helper `$ACE7`: сочетает `$1BCC` и `$1CA6` по phase/side |
| `$AFE6` | общий route helper тел: текущая запись движет raw Q8 velocities до countdown 0; общий bit-mask barrier затем читает следующий 6-byte record с удвоенными velocities/половинной duration; `$8000` меняет route stream, zero route ставит completion bit и terminal velocity `$0200,0` |
| `$B073` | terminal state предыдущего stage controller: RNG, sound, allocator, затем delete `$03EC` по ROM count |
| `$B111` | boss/stage controller от `$B0E1`: arena setup `$5596`, helper `$F9B5`, sound, allocator children/resources и scripted transitions |
| `$B1FA` | boss/stage controller от `$B1D8`: RNG `$EDE9`, allocator children, resource `$51EE`, затем state `$B2DC` |
| `$B2DC` | active controller/object `$B1FA`: Q8 motion, composite `$1C1B`, collision `$F7F1`, RNG child spawns, sound/jobs; переходы `$B40A/$B473` |
| `$B40A` | terminal state `$B2DC`: sound, scroll restore `$5579`, resource release `$523E/$F50C`, delete `$03EC` |
| `$B473` | moving composite continuation `$B2DC`: Q8 X `$0672`, render `$1C1B`, ROM timer возвращает основной state |
| `$B491` | child/controller `$B3DE`: RNG, sound, delete после исчерпания ROM spawn script |
| `$B521` | active boss/stage object от `$B21C`: collision `$F7F1`, target angle `$1D89`, helpers `$B719/$B75A/$B797`, jobs/sound и terminal cleanup |
| `$B645` | Q8 continuation `$B521`: motion `$0672/$0689`, collision `$F7F1`, renderer `$B719`, sound/state transition |
| `$B6AE` | render-only continuation `$B521`, вызывающий `$B719` и возвращающийся по timer |
| `$B6C4` | escape/terminal motion `$B521`: Q8, bounds `$1D6B`, collision `$F7F1`, renderer `$B719` |
| `$B719` | общий descriptor renderer состояний `$B521/$B645/$B6AE/$B6C4` через `$1BCC` |
| `$B75A` | timer/phase helper `$B521` без внешних calls; обновляет ROM state fields |
| `$B797` | RNG helper `$B521`, выбирающий ROM phase/velocity через `$EDE9` |
| `$B7FB` | единственный Stage 7 event `$A800`: создаёт root `$B805` priority `$A200` |
| `$B805` | создаёт пять armour `$B997` при X `$02D0…$03D0` и animation thresholds `$03C0…$0340`, random spawner `$BAA7`, missile spawner `$BD32`, core `$BE81`; затем controller `$B8D5/$B950` |
| `$B8D5` | controller timer: на `$02E0` останавливает X scroll, на `$0300` ставит bit `$80` в 128 foreground attributes от `$1002`, на `$1120/$1160` начинает exit `$B950` |
| `$B997/$B9FD` | пять armour sections: foreground scroll, forward/reverse composite frames `$60E6/$60F2/$60FE/$610A`, collision/death offsets `$6116`, resource `$2F`; `$F75F` ограничивает damage accumulator `$A0`, но handler намеренно не убивает section — retreat запускает только root flag |
| `$BAA7` | после timer `$0360` уменьшает cadence `$20→8`, RNG индексирует 32-handler table `$612C`, X cycle `$611E`, child vertical Q8 velocity `-(400-16*cadence)` |
| `$BB40…$BC63/$BC95` | 11 child constructors задают descriptor roots `$616C…$6238`, collision `$6244/$624C/$6254`, resources и animation flags; общий runtime `$BC95` интегрирует vertical Q8, damage и ROM death variants |
| `$BD32` | каждые `$80` updates после `$0360` читает cyclic X list `$627C`, `$8000` пропускает slot, zero возвращает pointer; создаёт `$BDB2` resource `$21` |
| `$BDB2` | 256-update missile: vertical `+1` до `$40`, hold, `-1` после `$C0`; aimed descriptors через `$1D89/$625C`, child shots на `$60/$A0`, collision `$630A` |
| `$BE81` | core `(02E8,0110)`, resource `$54/$55`, HP `$55`; после `$0500` phase выбирает Q8 X profile `$631A`, composite pointer `$633A`, collision pointer `$637C`; death ставит root flag, очищает 2048 terrain attributes до low nibble и входит explosion storm `$BFE8` |
| `$B8D5` | terminal/timer state `$B805`: sound и delete `$03EC` |
| `$B950` | промежуточный state `$B805`, вызывает helper `$B966` |
| `$B966` | sound/delete helper `$B950` по ROM condition |
| `$B997` | stage object от `$B822`: composite `$1C1B`, collision/damage `$F75F`, sound и transition `$B9FD` |
| `$B9FD` | continuation `$B997`: composite/collision, RNG child spawn, resource release/jobs и delete |
| `$BA9B` | timer-only child/controller от `$BA5C`; меняет handler/fields без external calls |
| `$BAA7` | randomized projectile controller от `$B85B`: RNG и allocator по таблице handlers `ES:$612C`, delete после ROM count |
| `$BB40` | один из 11 handlers random table `$612C`: RNG initialization и resource `$51EE`, затем общий `$BC95` |
| `$BB72/$BB7E/$BB8A/$BB96/$BBA2/$BBAE` | шесть коротких random-table initializers: задают разные ROM velocity/phase constants и переводят object в `$BC95` |
| `$BBC3` | random-table initializer с RNG/resource `$51EE`; может немедленно delete, иначе `$BC95` |
| `$BC08` | random-table initializer с resource `$51EE`, затем `$BC95` |
| `$BC31/$BC63` | два RNG/resource initializers random table, затем общий runtime `$BC95` |
| `$BC95` | общий runtime 11 random handlers: Q8 Y `$0689`, descriptor `$1BCC`, damage `$F6DA`, RNG, sound/jobs, resource release/delete |
| `$BD32` | controller от `$B87F`: sound, allocator `$BDB2`, resource `$51EE`, delete после ROM count |
| `$BDB2` | child `$BD32`: Q8 Y, target angle `$1D89`, composite `$1C1B`, damage `$F6DA`, child helper `$BE43`, jobs/resource cleanup |
| `$BE43` | child-spawn helper `$BDB2`: angle `$1D89`, allocator `$03A6`, resource `$51EE`, ROM velocity/link fields |
| `$BE81` | controller/child от `$B897`: RNG, Q8 X, composite `$1C1B`, damage `$F6DA`, nested allocator/resources и terminal cleanup |
| `$BFE8` | continuation `$BE81`: RNG/allocator/sound, затем delete `$03EC` по ROM condition |
| `$C03F` | stage child от `$BEC0`: priority `$F5C1`, descriptor `$1BCC`, player `$F694`, sound и transition `$C069` |
| `$C069` | terminal child `$C03F`: priority/player/render, explosion job, resource release `$523E/$F50C`, delete `$03EC` |
| `$C0CA` | final-stage controller от `$C0A9`: progression `$30`, callback script `ES:$6416` через `$C0DC`, terrain/player/damage `$1EB5/$F578/$F75F`, allocator spawn table и terminal states `$C1EB/$C4BC` |
| `$C1EB` | final-stage transition state `$C0CA`: sound и tilemap job `$EAA9`, затем ROM state advance |
| `$C284` | child/controller, создаваемый `$C1A3`: RNG, sound, allocator и delete по ROM count |
| `$C2F0/$C2F6/$C305/$C30A/$C315/$C31B/$C326/$C32C/$C332/$C37A` | десять коротких callbacks script `ES:$6416`: каждый записывает конкретные final-stage state/scroll bytes; `$C2F0/$C31B` также sound, `$C332` terrain `$1EB5` |
| `$C37F` | callback script `ES:$6416`: allocator создаёт `$C39C`, при отказе/старом объекте вызывает delete `$03EC` |
| `$C39C` | moving final-stage child `$C37F`: ROM motion/timer и terrain helper `$C434`, transition `$C3EE` |
| `$C3EE` | paired continuation `$C39C`, также использует terrain helper `$C434` |
| `$C434` | общий terrain helper `$C39C/$C3EE`: probe `$1EB5`, обновление direction/phase по tile result |
| `$C4BC` | Stage 3 battleship/background controller от `$C46E`: progression, scroll bytes, spawner `$C61F`, script reader `$C5F8`, sounds `$F3FF`, stage transition `$F366`, cleanup `$03EC` |
| `$C57D` | terminal scroll sequence `$C4BC`: задаёт fixed velocities/timers, sounds `$1A/$1C`, scroll/palette `$5579/$F130/$F3FF`, затем next-stage path |
| `$C5F8` | прочитать трёхбайтную запись movement script `object+$12`: два signed direction bytes и duration; `$80` возвращает carry как sentinel |
| `$C61F` | пройти 10-byte spawn records `ES:$6CE0…$6F87`: сравнить threshold с `-object.x`, allocator handler `+6`, записать child X/Y и parent link, шаг `$0A` |
| `$C656/$C662/$C66E/$C67A/$C686/$C692/$C69E/$C6AA/$C6B6/$C6C2/$C6CE/$C6DA/$C6E6/$C6F2/$C6FE/$C70A/$C716/$C722/$C72E/$C73A/$C746/$C752/$C75E/$C76A/$C776/$C782/$C78E` | 27 leaf handlers spawn table `$6CE0…$6F87`: без external calls, каждый записывает собственный ROM constant/state и возвращает; точный target выбирается record `+6` |
| `$C7C3` | final-stage weapon/object controller: RNG, allocator, collision helper `$C93F`, затем delete по ROM records |
| `$C846` | continuation controller `$C7C3`, выполняющий очередной allocator step |
| `$C8D6` | terminal controller state: sound/job, terrain `$1EB5`, delete `$03EC` |
| `$C928` | общий leaf child четырёх allocator sites `$C84C/$C86B/$C88D/$C8AF`: изменяет только ROM counters/links, без внешних calls |
| `$C93F` | точный collision dispatcher `$C7C3`: последовательно `$F4AA/$F525/$F548/$F560` для разных weapon record classes |
| `$C9A0/$C9AC/$C9B8/$C9C4` | четыре leaf child handlers, выбираемые `object+$22` и allocator `$DA10`; каждый задаёт свой fixed direction/state без external calls |
| `$C9F9` | второй final-stage weapon controller: RNG, allocator, collision helper `$CB7D`, delete по ROM count |
| `$CA84` | continuation `$C9F9` с allocator step |
| `$CB14` | terminal `$C9F9`: sound/job, terrain `$1EB5`, delete `$03EC` |
| `$CB66` | общий leaf child четырёх sites `$CA8A/$CAA9/$CACB/$CAED`, только fixed state constants |
| `$CB7D` | collision dispatcher `$C9F9`: `$F493/$F4AA/$F525/$F548/$F560` в ROM порядке |
| `$CBEF` | spawn-table child initializer: получает resource `$51EE` и переводит object в `$CC1B` |
| `$CC1B` | multipart final-stage child: composite `$1CA6`, damage `$F6DA`, nested allocator/resources, sound и cleanup |
| `$CDED` | continuation `$CC1B`: Q8 Y `$0689`, composite `$1CA6`, collision `$F75F`, allocator child, jobs/resource cleanup |
| `$CE9F` | controller child от `$CE80`: allocator sequence и delete `$03EC` |
| `$CEEA` | child `$CC5F`: composite `$1C1B`, collision `$F75F`, resource release/delete |
| `$CF6C/$CF7C/$CF8C` | три коротких children `$CCC3/$CD6F/$CD19`: descriptor `$1BCC`, затем resource release `$523E` и delete `$03EC` по timer/bounds |
| `$CF9C` | общий moving child трёх allocator sites: Q8 motion, `$1BCC`, terrain `$1E6C`, player `$F485`, bounds `$1D6B`, release/delete |
| `$CFE9` | spawn-table controller: allocator child, resource `$51EE`, fire parameters `$F8A7` |
| `$D095` | spawn-table controller: allocator/resource `$51EE`, fire parameters `$F8A7`, следующий object state по ROM record |
| `$D0FF` | child continuation: composite `$1C1B`, collision `$F75F`, sound, resource release/delete |
| `$D188` | moving child: Q8 Y, composite, terrain `$1E6C`, collision `$F75F`, nested allocator, job/resource cleanup |
| `$D244` | controller от `$D225`: allocator sequence и delete `$03EC` |
| `$D28F` | child трёх allocator sites: target angle `$1D89`, descriptor `$1BCC`, damage `$F6DA`, helper `$D338`, jobs/resource cleanup |
| `$D338` | child-spawn helper `$D28F`: angle, allocator, resource `$51EE`, ROM velocity/link fields |
| `$D39E` | spawn-table initializer: получает resource `$51EE`, state `$D3C9` |
| `$D3C9` | active multipart child: collision `$F75F`, allocator, renderer `$D497`, sound/state transitions |
| `$D497` | общий renderer `$D3C9/$D4CD/$D518`: composite `$1C1B/$1CA6` по phase/side |
| `$D4CD` | continuation `$D3C9`: Q8 Y, collision `$F75F`, renderer, resource cleanup/delete |
| `$D518` | terminal/spawn continuation: collision/render, allocator child, job/resource cleanup |
| `$D596/$D5A3/$D5B0/$D5BD/$D5CA` | пять leaf handlers spawn table: задают distinct fixed direction/state constants без external calls |
| `$D5D7` | шестой spawn-table initializer: RNG `$EDE9`, resource `$51EE`, state `$D608` |
| `$D608` | active child `$D5D7`: target angle, `$1BCC`, damage `$F6DA`, nested allocator/resource, sound/jobs и cleanup |
| `$D71D` | continuation `$D608`: angle `$1D89`, descriptor `$1BCC`, ROM timer transition |
| `$D789` | short child `$D7C9`: descriptor `$1BCC`, resource release `$523E`, delete `$03EC` |
| `$D7B9` | controller `$D664`: allocator child, resource `$51EE`, затем state `$D807` |
| `$D807` | child `$D7B9`: Q8 motion, `$1BCC`, terrain `$1EB5`, player `$F485`, bounds `$1D6B`, release/delete |
| `$D892` | continuation child `$D807`: descriptor `$1BCC`, player `$F485`, next ROM state |
| `$D8B7/$D8C4/$D8D1` | три leaf handlers spawn table; задают `object+$22` соответственно `$C9A0/$C9AC/$C9B8` для allocator `$DA10` |
| `$D8DE` | четвёртый leaf handler: `object+$22=$C9C4` и resource `$51EE` |
| `$D90E` | active child `$D8xx`: RNG, `$1BCC`, damage `$F6DA`, nested allocator, sound/jobs и resource cleanup |
| `$DA49` | continuation `$D90E`: allocator child через handler `object+$22`, `$1BCC`, damage и resource cleanup |
| `$DAC8` | initializer двух allocator sites: получает resource `$51EE`, ставит moving state `$DB02` |
| `$DB02` | child `$DAC8`: descriptor `$1BCC`, player `$F485`, resource release/delete |
| `$DB63/$DB70/$DB7D` | три leaf spawn-table initializers с разными fixed state constants |
| `$DB8A` | четвёртый leaf initializer той же группы, дополнительно resource `$51EE` |
| `$DBB5` | active child группы: `$1BCC`, damage `$F6DA`, helper `$DC63`, sound/jobs и resource cleanup |
| `$DC63` | spawn-decision helper `$DBB5`, вызывает `$DC79` по ROM timer/position |
| `$DC79` | allocator/resource helper `$DC63` |
| `$DCC0` | spawn-table initializer: resource `$51EE`, state `$DCE6` |
| `$DCE6` | composite child continuation через `$1C1B` |
| `$DD25` | общий composite/damage state трёх transitions: `$1C1B` + `$F6DA` |
| `$DD8A` | парный composite/damage state `$1C1B/$F6DA` |
| `$DDF4` | collision/terminal state: composite, hit routine `$F7E4`, allocator, sound/job/resource cleanup |
| `$DEC9` | controller от `$DEA5`: RNG, allocator, sound и delete по ROM count |
| `$DF44` | continuation multipart state: composite `$1C1B`, damage `$F6DA` |
| `$DF95` | terminal multipart state: composite/damage, helper `$E00F`, resource release/delete |
| `$E00F` | spawn helper `$DF95`: RNG, sound, allocator child и resource `$51EE` |
| `$E060` | child `$E00F`: Q8 motion, `$1BCC`, terrain `$1EB5`, player `$F694`, bounds `$1D6B`, resource release/delete |
| `$E0D9` | continuation `$E060` с тем же Q8/render/terrain/player/bounds contract |
| `$E129` | spawn-table initializer: resource `$51EE`, fire parameters `$F8A7`, state `$E157` |
| `$E157` | active child `$E129`: angle `$1D89`, `$1BCC`, damage `$F6DA`, helper `$E201`, sound/jobs/resource cleanup |
| `$E201` | child-spawn helper `$E157`: angle, allocator, resource `$51EE`, ROM velocity/link fields |
| `$E26A` | leaf spawn-table handler: fixed direction/state constants, без external calls |
| `$E277` | leaf spawn-table initializer: resource `$51EE`, fire parameters `$F8A7`, state `$E2AA` |
| `$E2AA` | active child `$E277`: angle/render/damage, два spawn helpers `$E361/$E3CA`, sound/jobs/resource cleanup |
| `$E361/$E3CA` | два angle/allocator/resource helpers `$E2AA`, создающие разные ROM children |
| `$E568` | generic spawned object initializer: resource `$51EE`, RNG `$EDE9`, state `$E5CD` |
| `$E5CD` | Q8-X child `$E568`: descriptor `$1BCC`, resource release `$523E`, delete `$03EC` |
| `$E6AB` | общий projectile initializer шести allocator sites: получает resource `$51EE`, записывает ROM phase и ставит `$E6C0` |
| `$E6C0` | generic projectile `$E6AB`: Q8 X, composite `$1C1B`, player `$F485`, bounds `$1D6B`, resource release/delete |
| `$E700` | Dobkeratops spawn-record handler: resource `$51EE`, ROM fields и следующий explosion/projectile state |
| `$E80C` | random-controller child handler `$8D12`: resource `$51EE`, ROM fields и следующий state |
| `$8C12…$8D54` | 30 Stage 7 set-piece objects: `$FA55` выбирает Y/path из `$93C4`, initial delay `(RNG&$FF)<<1`; explosions `$E7BE` после delay, затем через 16 и 8 update в offsets `(-4,+14),(+16,0),(-4,-4)`, потом `$E80C` resource `$63`; `$8D54` исполняет packed `(tilemap delta,code)` path с независимым сложением BL/BH и attr `$000A` |
| `$EAA9` | final-stage terrain/tilemap job: probe `$1EB5`, затем helper `$EAD0` для записи strip/cell state |
| `$EAD0` | helper `$EAA9`, нормализующий адрес/индекс через `$EAE1` |
| `$EAE1` | leaf arithmetic/address helper `$EAD0`, без внешних calls |
| `$EE3C` | final-stage scroll/reset object от `$EE0B`: timer/conditions, вызывает next-stage init `$F01B` и удаляется `$03EC` |
| `$EEB5` | final-stage object от `$EEAB`: task jobs `$0384`, palette `$5504`, ROM timer/state transition `$EF09` |
| `$EF09` | continuation `$EEB5`: task job `$0384`, palette `$54E4`, затем ROM terminal state |
| `$F3C1` | timed control object от `$F366`: countdown `+$10`; при нуле либо `$2FC4!=0` отправляет delayed sound `+$12` через `$0303` и удаляется `$03EC` |
| `$F461` | поставить global cleanup `$2FC4=1` и создать `$0100/$F477` с timer 3 |
| `$F477` | трёхpassовый cleanup timer: при нуле снимает `$2FC4` и удаляет object |
| `$F49B` | collision helper: последовательно проверяет records `$0136/$0156` через `$F578` |
| `$F7E4` | entry variant damage routine: сохраняет old damage `+$1F`, проверяет X bound и входит в общую ветвь `$F775` |
| `$F7F1` | полный multi-weapon damage dispatcher: R-9 `$F485`, linked records `$F49B`, shot `$F4AA`, owner pairs `$F4BF`, missiles `$F548`, Force/Bit scan `$F560`; обновляет damage/hit flags в ROM порядке |
| `$F912` | command-field decoder: bits 4…7 CX индексируют word table `ES:$9274`, результат в child `+$12` |
| `$F932` | difficulty decoder `$2F2E&3`: тройка words `ES:$9294` записывается в `+$2A/+$2C/+$28` |
| `$F95C` | command high-nibble decoder: table `ES:$92AE` задаёт flag `+$17`, script pointer `+$12` и первый word `+$14` |
| `$F9B5` | command bits 4…5 decoder: word `ES:$931C` → `object+$22` |
| `$F9C9` | command low-nibble decoder: шестибайтная запись `ES:$9324` → X/Y и byte `+$20` |
| `$F9F0` | command low-two-bit decoder: 14-byte record `ES:$9384` → семь position/script fields, X фиксирован `$02D0` |
| `$FA40` | command bits 2…3 decoder: word `ES:$93BC` → `object+$34` |
| `$FA55` | command low-three-bit decoder: 4-byte record `ES:$93C4` → Y и field `+$30`, X=`$02C0` |
| `$FA75` | command low-nibble decoder: 4-byte position pair `ES:$93DC` → X/Y |
| `$FA90` | command bit `$10` decoder: X=`$02C0`, Y=`$0174` либо `$009C` |
| `$FAA5` | command low-nibble decoder: word `ES:$943C` → period `+$20`; RNG `$EDE9 & (period-1)` → phase `+$22` |
| `$FAC1` | command low-nibble decoder: X=`$02C8`, Y из word table `ES:$941C` |
| `$FB53` | six-object controller child от `$FB10`: восьмибайтные `(duration,vx,vy,descriptor)` records, Q8 motion, `$1BCC`, X bound/cleanup, resource release/delete |

Final-stage handler `$9660` создаёт невидимый `$2000/$9674` spawner в
`X=$02C0`, выбирая Y через bit `$10` (`$0174/$009C`). Таблица
`ES:$943C` — 16 reload periods, а не координаты: `$0140,$0130,$0110,$00F0,
$00E0,$0090,$0060,$0040`, затем восемь `$0030`. При обнулении timer spawner
вычисляет 16-секторное направление `$1D89`, выбирает difficulty velocity
matrix через `$4284` (`$9010` при difficulty 0), descriptor через `$428C` и
создаёт child `$2010/$96E9`. Child интегрирует Q8 X/Y, переключает соседний
descriptor по `$2EB6&8`, использует collision `$436C=(-9,+9,-9,+9)` и при
поражении входит в общий `$E7D4` stream `$8530` с resource type `$6B`.

### Полный граф косвенных V30-переходов

В runtime достигнуты ровно одиннадцать инструкций с косвенной целью:
`$00D3,$00F6,$0244,$0259,$0267,$1BC6,$257F,$2612,$3957,$C0DC,$FB06`.
Генератор запрещает появление двенадцатой неописанной инструкции и требует,
чтобы каждая разрешённая цель была началом декодированной инструкции.
(`$FB06` — второй stage-event dispatcher через ту же таблицу `ES:$B92D`, что и `$1BC6`.)

| Instruction | Источник цели | Полная граница |
|---:|---|---|
| `$00D3` | main callback word `DS:$3060` | bootstrap записывает `$55E8` |
| `$00F6` | восьмибайтная task-ring запись `DS:$1E20 + cursor` | 16 producer callbacks `$E865,$E883,$E8A0,$E8BD,$EA1F,$EA39,$EA41,$EA49,$EA51,$EA73,$EBF1,$EC14,$EC7B,$ED3A,$ED58,$ED93`; генератор выводит набор обратным разбором CX во всех вызовах allocator `$0384`, включая путь `MOV DX,$EA1F` (`$1156`) → `MOV CX,DX` (`$1175`) |
| `$0244/$0259/$0267` | handler word `object+$00` директора, 40 fixed slots и linked slots | union initial `ES:$081A[40]`, всех `DX→$03A6` producers, state writes `MOV [BP/SI],imm` и bootstrap `$1BA6/$1BA7` |
| `$1BC6` | event opcode table | 50 words `ES:$B92D…$B98F`, 48 уникальных handlers; `$0800` повторён трижды |
| `$257F/$2612` | Force level/state table | четыре words `ES:$1430 = $2682,$26AD,$26D0,$26E9` |
| `$3957` | player-weapon matrix | `ES:$1B80…$1FFF`, 48 таблиц по 12 words, 69 уникальных callbacks; `$3959` занимает 384 из 576 entries |
| `$C0DC` | final-stage threshold/callback script | 39 исполняемых records `ES:$6416…$64B1`; `$8000,$FFF2` по `$64B2` является sentinel и не объявляется ребром |

Allocator `$03A6` имеет 171 статически достигнутый producer site: immediate
`DX`, семь ROM-table producers (`$794E,$91E5,$95BB,$9D5F,$BAEE,$C637,$DA10`)
и их точные таблицы. Полный список каждого ребра, включая 68 десятибайтных
final-stage spawn records `ES:$6CE0…$6F87`, генерируется в разделе
`Runtime V30 indirect control-flow cross-reference` файла
`RTYPE_WORLD_ROM_COMPLETE.md`. Проверка сравнивает полный набор producer sites,
а не только число.

Z80 имеет ровно два косвенных `JP (HL)` (`$035D/$03AB`). Первый разрешён
32-word таблицей `$035E`, второй — таблицей `$03AC` из трёх words; значения
обеих таблиц побайтно фиксированы генератором. Других косвенных Z80 переходов
в достигнутом code graph нет.

#### Initial fixed-object handlers `ES:$081A`

`$06A0` копирует ровно 40 words в `DS:$0020,$0040,…,$0500`; шаг RAM record
равен `$20`, шаг ROM — 2. Первые десять records — R-9/Force/player weapon
directors, следующие 24 выбирают блоки weapon matrix, последние шесть — три
экземпляра `$3D16` и три обычных shot-slot handler `$4ED8`.

| DS object | Index | Initial handler |
|---:|---:|---:|
| `$0020` | 0 | `$1FC0` |
| `$0040` | 1 | `$2430` |
| `$0060` | 2 | `$249A` |
| `$0080` | 3 | `$3067` |
| `$00A0` | 4 | `$3304` |
| `$00C0` | 5 | `$3364` |
| `$00E0` | 6 | `$30FF` |
| `$0100` | 7 | `$32FB` |
| `$0120` | 8 | `$2CE5` |
| `$0140` | 9 | `$2EA6` |
| `$0160` | 10 | `$395A` |
| `$0180` | 11 | `$3980` |
| `$01A0` | 12 | `$39A6` |
| `$01C0` | 13 | `$39CE` |
| `$01E0` | 14 | `$39F6` |
| `$0200` | 15 | `$3A1E` |
| `$0220` | 16 | `$3A46` |
| `$0240` | 17 | `$3A6E` |
| `$0260` | 18 | `$3A96` |
| `$0280` | 19 | `$3ABE` |
| `$02A0` | 20 | `$3AE6` |
| `$02C0` | 21 | `$3B0E` |
| `$02E0` | 22 | `$3B36` |
| `$0300` | 23 | `$3B5E` |
| `$0320` | 24 | `$3B86` |
| `$0340` | 25 | `$3BAE` |
| `$0360` | 26 | `$3BD6` |
| `$0380` | 27 | `$3BFE` |
| `$03A0` | 28 | `$3C26` |
| `$03C0` | 29 | `$3C4E` |
| `$03E0` | 30 | `$3C76` |
| `$0400` | 31 | `$3C9E` |
| `$0420` | 32 | `$3CC6` |
| `$0440` | 33 | `$3CEE` |
| `$0460/$0480/$04A0` | 34…36 | `$3D16` |
| `$04C0/$04E0/$0500` | 37…39 | `$4ED8` |

#### Полное множество callbacks weapon matrix `ES:$1B80…$1FFF`

Диапазон состоит из 48 последовательных блоков по `$18` bytes; в каждом 12
words. `$3939` вычисляет внутри выбранного блока byte offset
`8*(DS:$003E-1)+DS:$003C`, читает word и делает `$3957: JMP AX`.
Ниже нет пропущенных entries: сумма occurrence count равна 576.

| Callback | Words в матрице | Callback | Words в матрице |
|---:|---:|---:|---:|
| `$3959` | 384 | `$3D7B` | 4 |
| `$3D81` | 4 | `$3D89` | 4 |
| `$3D91` | 4 | `$3DB7` | 8 |
| `$3DBD` | 8 | `$3DC5` | 8 |
| `$3DCD` | 8 | `$3DF3` | 8 |
| `$3DF9` | 8 | `$3E01` | 8 |
| `$3E09` | 8 | `$3E2F` | 4 |
| `$3E35` | 4 | `$3E3D` | 4 |
| `$3E45` | 4 | `$3E6B` | 4 |
| `$3E71` | 4 | `$3E79` | 4 |
| `$3E81` | 4 | `$3F28` | 2 |
| `$3F5D` | 2 | `$3F84` | 1 |
| `$3FA9` | 1 | `$3FCB` | 1 |
| `$3FF0` | 1 | `$4012` | 1 |
| `$4037` | 1 | `$4064` | 2 |
| `$4099` | 2 | `$40C0` | 1 |
| `$40E5` | 1 | `$4107` | 1 |
| `$412C` | 1 | `$414E` | 1 |
| `$4173` | 1 | `$41A0` | 2 |
| `$41D1` | 2 | `$41F4` | 1 |
| `$4215` | 1 | `$4233` | 1 |
| `$4254` | 1 | `$4272` | 1 |
| `$4293` | 1 | `$4591` | 2 |
| `$45B8` | 2 | `$45DF` | 4 |
| `$45FE` | 4 | `$461D` | 2 |
| `$463C` | 2 | `$465B` | 2 |
| `$467A` | 2 | `$46A1` | 2 |
| `$46C8` | 4 | `$46E7` | 4 |
| `$4706` | 2 | `$4725` | 2 |
| `$4744` | 2 | `$4927` | 1 |
| `$4977` | 1 | `$4CD3` | 2 |
| `$4CF8` | 2 | `$4D1D` | 1 |
| `$4D3F` | 1 | `$4D61` | 2 |
| `$4D8E` | 2 | `$4DBB` | 1 |
| `$4DE5` | 1 | **Итого** | **576** |

## Stage 1: инициализация и скорость

| V30 | File offset | Назначение |
|---:|---:|---|
| `$F01B` | `$F41B` | выбирает 14-байтную запись stage, задаёт указатели, скорости и ring preload |
| `$F0F3` | `$F4F3` | повторно загружает скорость и progression по stage index |
| `$F130` | `$F530` | останавливает четыре scroll velocity |
| `$F153` | `$F553` | transition reset аккумуляторов и скоростей |
| `$F353` | `$F753` | после перехода включает foreground velocity `$0080` |
| `$F429` | `$F829` | штатно обнуляет foreground/background X velocity |

### Таблица Stage (`ES:$87FA`, шаг 14 байт)

Запись Stage 1 (`index 0`):

| Offset | Значение | Назначение |
|---:|---:|---|
| `$87FA` | `$0600` | начальный progression/threshold |
| `$87FC` | `$0000` | foreground map source pointer |
| `$87FE` | `$0000` | background map source pointer |
| `$8800` | `$0080` | foreground X velocity: 0.5 native px/VBlank |
| `$8802` | `$0100` | background X velocity: 1 native px/VBlank |
| `$8804` | `$0901` | stage configuration / object-list selector |
| `$8806` | `$0001` | stage-specific parameter |

`ES:$8C20` — таблица указателей списков объектов. Для Stage 1 выбран
`ES:$8C70`; первые 15 слов: `$8000,$8011,$8012,$8013,$8014,$8015,$8016,
$8000,$8018,$8019,$801B,$801D,$8001,$8003,$8005`.

Полные 161 записи progression event stream Stage 1 находятся в
`Docs/RTYPE_WORLD_STAGE1_EVENTS.md`. Документ генерируется прямо из World ROM
скриптом `Source/Tools/m72_stage_event_map.py`; номера MAME frames туда не
включаются.

## Stage 1: dispatcher врагов и первые типы

Четырёхбайтный event stream начинается с `ES:$B993`, заканчивается Stage 1
записью `ES:$BC13`, которая вызывает `$F01B` для следующего stage. Последние
события перед первым боссом:

| ES | Threshold | Command | Handler | Смысл |
|---:|---:|---:|---:|---|
| `$BBFF` | `$1318` | `$9C00` | `$F366` | stage/boss transition control |
| `$BC03` | `$13A0` | `$5800` | `$98FD` | multipart parent Dobkeratops |
| `$BC07` | `$148A` | `$0800` | `$F429` | остановка X scroll |
| `$BC0B` | `$14C0` | `$6800` | `$5596` | collision table boss arena |
| `$BC0F` | `$14FE` | `$A000` | `$F130` | остановка всех scroll velocity |
| `$BC13` | `$1500` | `$6404` | `$F01B` | следующий stage после boss state |

Первые три боевых типа сопоставлены одновременно по event handler, linked
object list и Sprite RAM MAME frame 1500:

| Event handler | Runtime handler | ROM sprite codes | Объект |
|---:|---:|---|---|
| `$5DC8` | `$5E8E` children | `$0132` (formation phase) | крупный patrol formation |
| `$596D` | `$59A2` | `$0036/$00F2/$0160/$0161/$00F4` | красный scripted flyer |
| `$5A02` | `$5A2B` | `$0100/$0102…` | наземный walker |

Это не имена, назначенные по внешнему виду: соответствие подтверждено точными
координатами object anchor и результатом `$1BCC`. Формула visible X составного
sprite: `object.x + signed(descriptor.dx) - 320`; Y восстанавливается из
`object.y + signed(descriptor.dy)` по аппаратной формуле M72.

### Точные HEX entry points первых типов

`$596D…$59A1`, создаёт priority `$8010`, handler `$59A2`:

```text
51 b9 10 80 ba a2 59 e8 2f aa 59 72 27 e8 f9 9e e8 27
9f bb ce 9a 89 5c 12 26 8b 07 89 44 14 c6 44 17 02 b0
0d e8 59 f8 88 5c 06 e8 4e 94 25 1f 00 89 46 16 c3
```

`$5A02…$5A2A`, создаёт priority `$8020`, handler `$5B9F`, два resource type
`$1E/$1F`:

```text
51 b9 20 80 ba 9f 5b e8 9a a9 59 72 1b e8 7a 9e e8 92
9e e8 65 9f b8 1e 00 e8 d0 f7 88 5c 06 b8 1f 00 e8 c7
f7 88 5c 3c c3
```

### Enemy `$5A02`: ground walker, покадровый автомат

Runtime-диапазон `$5A2B…$5CE9` лежит в maincpu region по file offsets
`$5E2B…$60E9`. Подтверждённые поля object:

| Поле | Смысл |
|---:|---|
| `+$00` | текущий handler |
| `+$02`/`+$04` | Q8 fractional word / native X |
| `+$08` | native Y, направление вверх увеличивает значение |
| `+$1E` | direction из `CH&1` |
| `+$20` | pointer последовательности landing sprites |
| `+$22` | 4-VBlank timer кадра landing |
| `+$3C` | второй resource/palette slot type `$1F` |

Процедуры восстановлены из ROM, а не по изображению:

| Handler | Точное действие |
|---:|---|
| `$5B9F` | записывает `$5BA4` и fall-through в него в том же scheduler pass |
| `$5BA4` | `$F63A`; `Y-=3`; для direction 0 добавляет `$2ED0`; рисует `$294C/$2970` с фазой `$2EB6&8`; вызывает `$F694,$1D6B`; probe `$1E6C` в `(X±8,Y-16)`; при code `<$0DFC` выравнивает `Y=(Y+7)&$FFF8`, ставит pointer `$292A/$2932`, timer 4, handler `$5C3E` |
| `$5C3E` | landing: scroll delta, sprite из `ES:[+$20]`, каждые 4 VBlank `+$20+=2`; нулевой terminator переключает handler на `$5A2B` |
| `$5A2B` | `$F63A`; direction 0 получает scroll delta; Q8 X velocity `$FFC0/$00C0` через `$0672`; walk sprite из `$291A/$2922`; `$F694,$1D6B`; два terrain probes выбирают `$5AE9` либо `$5CA6` |
| `$5AE9` | вторая 4-VBlank sprite-последовательность, затем motion script `$9AF8/$9B0A` и handler `$5B4D` |
| `$5B4D` | `$F5C1` script motion, fall-through обратно в `$5B9F` по завершении; использует type `$1F` для falling sprite |
| `$5CA6` | scroll-following edge state, sprite `$293A/$295E` по стороне от R-9, затем `$F694/$1D6B` |
| `$5C83/$5CD7` | `$F50C`, release обоих resource slots; первая ветвь создаёт `$E7BE`, вторая удаляет object через `$03EC` |

#### Ракеты ходящего `$5A02`: `$F8A7 → $F63A → $E601`

Entry не ограничивается координатами и направлением: instruction в `$5A12`
вызывает `$F8A7`. High nibble `CL` выбирает шестибайтную запись
`ES:$8E10 + 6*((CL&$F0)>>4)` и сохраняет её как
`+$2A=первый fire threshold`, `+$2C=верхний threshold`,
`+$28=указатель таблицы Q8-скоростей ракеты`. Затем `$EDE9`, умножение
результата на 4 и маска `+$2A-1` задают начальный `+$26`. RNG вызывается и
для нулевой записи.

Каждый runtime handler ракетницы начинает update одним и тем же `$F63A`:

| Handler | bytes относительного `CALL $F63A` |
|---:|---|
| `$5A2B` | `e8 0c 9c` |
| `$5AE9` | `e8 4e 9b` |
| `$5B4D` | `e8 ea 9a` |
| `$5BA4` | `e8 93 9a` |
| `$5C3E` | `e8 f9 99` |
| `$5CA6` | `e8 91 99` |

`$F63A` увеличивает `+$26`; при равенстве `+$2A` либо достижении `+$2C`
сбрасывает счётчик и, если `+$28!=0`, создаёт object `$A000/$E601`.
Поэтому стрельба должна работать во всех фазах, включая падение, посадку и
ходьбу, а не только в одном визуальном состоянии. Для первого стреляющего
Stage-1 command `$1488` (`CL=$88`) row 8 таблицы равна
`$0040,$0140,$8F90`; при исходном RNG `$0304` начальный `+$26=$0010`, и
первая ракета запрашивается через `$30` update. Command `$1408` выбирает
нулевую row 0 и не стреляет — это отдельный штатный вариант, а не ошибка.

Python `GroundWalker` теперь хранит буквальные поля `$F8A7` и вызывает общий
`EnemyProjectile` в точках `$F63A`. Ранее был перенесён только автомат
движения `$5B9F…$5CD7`, поэтому визуально правильные ракетницы действительно
ходили, но ни одна не могла создать ракету.

Дополнительная сверка обнаружила обязательную зависимость выше по event
stream: каждый из шести stage-control objects `$FB9C` на threshold `$06C6`
вызывает `$EDE9` в `$FBE0` и сохраняет `4*RNG` в `+$2C`. Однако добавлять в
Python только эти шесть вызовов нельзя: MAME к frame 1472 выполнил уже 154
шага `$EDE9`, тогда как частичная Python-модель знает лишь малую часть всех
consumers. Такой частичный патч сдвигал `+$26` с `$0038` только до `$001C`,
а не до фактического MAME `$0014`, поэтому он удалён. Доказанный вызов
`$FB9C->$EDE9` остаётся в ROM-карте; точный global RNG checkpoint будет
включён только после карты всех callers `$EDE9` и их VBlank scheduling.

Критический HEX начала падения и terrain probe `$5B9F…$5C3D`:

```text
c7 46 00 a4 5b e8 93 9a 83 6e 08 03 bb 70 29 f6 46
1e ff 75 09 a1 d0 2e 01 46 04 bb 4c 29 f7 06 b6 2e
08 00 75 03 83 c3 06 ff 76 06 8a 46 3c 88 46 06 e8
f8 bf 8f 46 06 bf 82 29 e8 b7 9a 73 03 e9 a1 00 e8
86 c1 73 03 e9 ed 00 f6 06 c4 2f ff 74 03 e9 e3 00
ff 76 04 ff 76 08 b8 08 00 f6 46 1e ff 75 03 b8 f8
ff 01 46 04 83 6e 08 10 e8 5c c2 8f 46 08 8f 46 04
3d fc 0d 72 01 c3 83 46 08 07 81 66 08 f8 ff b8 2a
29 f6 46 1e ff 74 03 b8 32 29 89 46 20 c6 46 22 04
c7 46 00 3e 5c c3
```

В `Stage.terrain_address` была найдена буквальная ошибка: Python применял
`$FC00`, но ROM `$1E72` содержит `SHR AX,1 / AND AX,$00FC / ADD AX,$1020`.
Из-за этого walker читал `$2BE0:$00E2` вместо MAME `$2B98:$0FA0` и садился в
воздухе. Исправлена только маска `$00FC`.

Точный RAM checkpoint из `enemy_groundwalker_exact`:

| Snapshot | Handler/state | X | Y | `+$20` | `+$22` |
|---:|---|---:|---:|---:|---:|
| 1471 | object отсутствует | — | — | — | — |
| 1472 | `$5B9F` | `$02C8` | `$00B8` | — | — |
| 1473 | `$5BA4` | `$02C7` | `$00B5` | — | — |
| 1474 | `$5BA4` | `$02C7` | `$00B2` | — | — |
| 1475 | `$5C3E` | `$02C6` | `$00B0` | `$292A` | 4 |
| 1487 | `$5A2B` | `$02C0` | `$00B0` | `$2930` | 4 |
| 1500 | `$5A2B` | `$02B0` | `$00B0` | `$2930` | 4 |
| 1800 | `$5A2B` | `$0139` | `$00B0` | `$2930` | 4 |
| 1810 | `$5A2B` | `$012C` | `$00B0` | `$2930` | 4 |
| 1811 | object отсутствует | — | — | — | — |

Python совпадает с этими десятью снимками по координатам, state, animation
pointer/timer и Q8 phase; это отдельный unit test. После найденной ошибки
«висящих» объектов в Python перенесены и три ранее пропущенных состояния:

- `$5A2B` после движения делает probe 1 `(X±$10,Y-$14)`. Пустота
  (`code >= $0DFC`) ставит `$5AE9`, pointer `$292A/$2932`, timer 4;
- если probe 1 твёрдый, probe 2 идёт в `(X±$12,Y-$0C)`. Пустой probe 2
  оставляет `$5A2B`; твёрдый переводит в `$5CA6`;
- `$5AE9` проигрывает три descriptor words по четыре VBlank, затем выбирает
  `$9AF8/$9B0A` и `$5B4D`; `$5B4D` исполняет `$F5C1`, включая тот же-pass
  fall-through `$5B9F→$5BA4`; `$5CA6` следует scroll delta и выбирает
  `$293A/$295E` unsigned-сравнением X R-9 и объекта.

MAME snapshots подтверждают, что `$5CA6` — реально используемое состояние,
а не догадка: frame 3500 содержит walkers `(X,Y,dir)` `$0142,$00B0,1`,
`$0143,$00B0,1`, `$01A5,$00B0,0`; frame 5500 — `$0188,$00B0,0`.
Unit tests отдельно заставляют обе terrain probes выбрать walk/turn/edge,
проходят `$5AE9→$5B4D→$5BA4` и проверяют основной MAME trace 1471…1811.

No-fire trace `enemy_groundwalker_nofire` доказал прямой выход первого object:
он не переходит в edge-state, а остаётся в `$5A2B`. В CPU frame 1810 X
становится `$012B`, после чего `$1D6B` возвращает carry и `$5CD7` удаляет
object. Буквальные границы `$1D6B…$1D88`:

```text
8b 46 04 2d 2c 01 72 14 2d a8 01 73 0f 8b 46 08 2d
7c 00 72 07 2d 18 01 73 02 f8 c3 f9 c3
```

То есть CLC только для unsigned `X=$012C…$02D3` и
`Y=$007C…$0193`. Временная Python-проверка `x<$0100/y>$0200` удалена.

`$5DC8…$5DFD`, создаёт parent formation priority `$8010`, handler `$5DFE`:

```text
51 b9 10 80 ba fe 5d e8 d4 a5 59 72 28 e8 b4 9a e8 1a
9b e8 a7 9b 80 e1 0f 80 f9 03 72 09 80 f9 09 73 04 83
44 04 40 c7 44 36 02 00 c7 44 32 00 00 c6 44 17 02 c3
```

### Общие декодеры параметра `CX`

| V30 | HEX | Буквальный результат |
|---:|---|---|
| `$F876…$F88B` | `8b d9 81 e3 0f 00 03 db c7 44 04 c8 02 26 8b 87 b0 8d 89 44 08 c3` | `x=$02C8`, `y=ES:[$8DB0+2*(CL&$0F)]` |
| `$F88C…$F8A6` | `8b d9 81 e3 0f 00 03 db 03 db 26 8b 87 d0 8d 89 44 04 26 8b 87 d2 8d 89 44 08 c3` | `(x,y)=ES:[$8DD0+4*(CL&$0F)]` |
| `$F8F5…$F911` | `8b d9 8a df 81 e3 03 00 03 db 03 db 26 8b 87 50 92 89 44 30 26 8b 87 52 92 89 44 34 c3` | поля `+$30/+$34` из `ES:$9250`, index `CH&3` |
| `$F926…$F931` | `8b c1 c1 e8 04 25 07 00 88 44 11 c3` | `byte +$11=(CX>>4)&7` |
| `$F97D…$F984` | `8a c5 24 01 88 44 1e c3` | direction flag `byte +$1E=CH&1` |
| `$F985…$F99E` | `8b d9 c1 eb 04 81 e3 0f 00 03 db 26 8b 9f ec 92 89 5c 12 26 8b 07 89 44 14 c3` | animation pointer через `ES:$92EC`, index `(CX>>4)&$0F` |
| `$F99F…$F9B4` | `8b d9 81 e3 07 00 03 db 26 8b 87 0c 93 89 44 08 c7 44 04 c8 02 c3` | `x=$02C8`, `y=ES:[$930C+2*(CL&7)]` |

`$F8A7…$F8F4` выбирает шестибайтную запись движения по high nibble `CL` и
difficulty `RAM:$2F2E`, заполняет `+$2A/+$2C/+$28`, затем получает начальную
маску/phase из RNG `$EDE9` в `+$26`. Точные bytes:

```text
8b d9 81 e3 f0 00 d1 eb d1 eb 8b c3 d1 e8 03 d8 81 c3
10 8e a0 2e 2f 32 e4 03 c0 03 c0 03 c0 03 c0 03 c0 03
d8 03 c0 03 d8 26 8b 07 89 44 2a 26 8b 47 02 89 44 2c
26 8b 47 04 89 44 28 e8 02 f5 03 c0 03 c0 8b 5c 2a 4b
23 c3 89 44 26 c3
```

### Менеджер sprite-resource / palette slot

`$1BCC` не сохраняет младший байт attribute из sprite descriptor: он
подставляет туда `object+$06`. Поэтому номер палитры врага нельзя назначать
по внешнему виду. Он является результатом штатного менеджера `$51EE`.

| V30 | Назначение | Буквальная семантика |
|---:|---|---|
| `$51EE…$5227` | acquire resource | поиск type в 16 записях `DS:$2114…$2133`; при отсутствии занимает последнюю свободную, увеличивает refcount и возвращает slot в `BL` |
| `$5228…$523D` | создать служебный object | адрес `DS:$2D34 + slot*6`, type/handler word `$8000\|resource_type`, поле `+$04=0` |
| `$523E…$5259` | release resource | уменьшает refcount; при нуле записывает type `$FF` |
| `$E430…$E488` | stage resource owner | создаёт object `$1000/$E4A5`, читает запись `ES:$8314 + 6*(CX&3)` и acquire типов `$57/$59/$5A/$5C` |
| `$E489…$E4A4` | destructor owner | release всех четырёх slot и удаление object |

Точный HEX `$51EE…$5259`:

```text
bb 32 21 b9 10 00 ba ff ff 8a 27 3a c4 74 1e 80 fc ff
75 02 8b d3 83 eb 02 e2 ee 83 fa ff 74 17 8b da 88 07
53 81 eb 14 21 e8 0e 00 5b fe 47 01 81 eb 14 21 d1 eb
c3 b3 ff c3 03 db 8b d3 03 db 03 da 81 c3 34 2d b4 80
89 07 c7 47 04 00 00 c3 80 fb ff 74 16 32 ff 03 db f6
87 15 21 ff 74 0b fe 8f 15 21 75 05 c6 87 14 21 ff c3
```

Точный HEX `$E430…$E4A4`:

```text
51 b9 00 10 ba a5 e4 e8 6c 1f 59 72 4b 8b d9 81 e3
03 00 03 db 8b c3 03 db 03 d8 26 8b 87 14
83 89 44 10 26 8b 87 16 83 89 44 32 26 8b 87 18 83
89 44 26 b0 57 e8 86 6d 88 5c 20 b0 59 e8 7e 6d 88
5c 21 b0 5a e8 76 6d 88 5c 22 b0 5c e8 6e 6d 88 5c
23 c7 44 28 00 00 c3 8a 5e 20 e8 af 6d 8a 5e 21 e8
a9 6d 8a 5e 22 e8 a3 6d 8a 5e 23 e8 9d 6d e8 48 1f
c3
```

Узкий snapshot MAME подтверждает состояние manager после начального preload:
на frame 898 заняты type `$02/$09/$57/$59/$5A/$5C`, а на frame 1500
добавлены `$0D/$56/$0C/$1E/$1F/$01`. Это контрольные результаты исполнения,
не входные данные Python runtime.

### Stage-control и таблица столкновений

`$FB9C` создаёт priority `$FF00`, handler `$FBED`, копирует шесть words из
16-байтной записи `ES:$989C + 16*CL` и устанавливает `+$2C=4*RNG`. Это
временной stage-control object; resource manager он напрямую не вызывает.

```text
51 b9 00 ff ba ed fb e8 00 08 59 72 43 8a d9 32 ff 03
db 03 db 03 db 03 db 81 c3 9c 98 26 8b 07 89 44 20 26
8b 47 02 89 44 22 26 8b 47 04 89 44 24 26 8b 47 06
89 44 26 26 8b 47 08 89 44 28 26 8b 47 0a 89 44 2a
e8 04 f2 03 c0 03 c0 89 44 2c c3
```

`$5526` декодирует `CL` через пару words `ES:$2754 + 4*CL` и передаёт
их `$54E4` с `DX=$000F`. `$5596`, вызываемый событием boss arena `$6800`,
инициализирует 15 записей по 12 bytes с
`word+0=$8000, word+4=1, word+8=3, word+$0A=$1F`.

Ровно 12 записей `$2754…$2783` имеют формат `(second-bank slot,resource
type)`: `(7,$17),(7,0),($0D,0),(9,0),($0A,0),($0B,0),($0C,0),($0D,0),
($0E,0),($0F,$0F),($0F,$0F),($0F,$0F)`. Следующие слова `$2784…$278B`
не принадлежат palette-таблице: это отдельный pickup hitbox.

```text
; $5526…$5540
81 e1 ff 00 03 c9 03 c9 8b d9 26 8b 8f 56 27 26 8b
9f 54 27 ba 0f 00 e8 a4 ff c3

; $5596…$55B4
be f4 2d b9 0f 00 c7 04 00 80 c7 44 04 01 00 c7 44
08 03 00 c7 44 0a 1f 00 83 c6 0c e2 e8 c3
```

### Полный palette manager и palette-only автоматы

Palette manager имеет два независимых набора по 16 slots:

| Records RAM | Staging R/G/B | Hardware palette | ROM RGB source |
|---:|---:|---:|---:|
| `$2D34`, шаг 12 | `$2134/$2314/$24F4` | `$C800:$0000/$0400/$0800` | `3B00:$0000 + type*48` |
| `$2DF4`, шаг 12 | `$2734/$2914/$2AF4` | `$CC00:$0000/$0400/$0800` | `3B00:$2400 + type*48` |

Каждый ROM palette type — ровно 48 bytes: 16 последовательных RGB triples.
При разворачивании `$53CF/$5481` каждый byte превращается в word и три
компоненты кладутся в отдельные staging planes с шагом `$0200`; slot сдвигает
destination на `$20` bytes. Формат 12-байтной управляющей записи:

| Поле | Точная роль |
|---:|---|
| `+0` | bit 15 active, low byte target palette type |
| `+2` | число компонент, изменённых текущим fade-step |
| `+4` | 0 = immediate copy, nonzero = gradual convergence |
| `+6` | dirty word для копирования staging в hardware RAM |
| `+8` | VBlank cadence mask |
| `+$0A` | текущий порог convergence, старт `$001F` |

`$5301` проходит сначала 16 records `$2D34`, затем 16 records `$2DF4`.
Mode 0 вызывает immediate `$53CF/$5481`; они копируют все 48 bytes,
сбрасывают bit 15 active и ставят dirty `+6=1`. Ненулевой mode вызывает
`$5360/$540E`: только когда `($2EB6 & cadence_mask)==0`, каждая RGB component
двигается на единицу к target. Для увеличения изменение выполняется, когда
`target-current >= threshold`; для уменьшения — сразу. После прохода dirty
ставится в 1, threshold уменьшается от `$1F` до 1; при threshold 1 и нулевом
changed-count active bit снимается.

`$525A…$52AD` и `$52B2…$5300` являются единственными commit-процедурами.
Для каждого dirty slot они сбрасывают `+6`, делают три `REP MOVSW` по 16 words
и переносят staging R/G/B в соответствующие аппаратные planes. Тем самым
palette-only изменение не затрагивает tile code, attribute или sprite RAM.

Публичные setters имеют точные контракты:

| Entry | Records | Действие |
|---:|---:|---|
| `$54C4` | `$2D34 + 12*slot` | active type=`CL`, gradual mode, mask=`DX`, threshold=`$1F` |
| `$54E4` | `$2DF4 + 12*slot` | то же для второго palette bank |
| `$5504` | `$2DF4 + 12*slot` | active type=`CL`, immediate mode, mask=0, threshold=`$1F` |
| `$5526` | `$2DF4` | по index `CL` читает `(slot,type)` из `ES:$2754+4*CL`, gradual mask `$000F` |
| `$5541` | `$2DF4` | загружает все 15 slots из списка ES, mode 1, mask 3; slot 15=`$801F` |
| `$5579/$5596/$55B5` | `$2DF4` | инициализация 15 slots с mode/mask `1/DX`, `1/3`, `0/unchanged` |

Все 23 записи palette-only stage-control `$FB9C` в `ES:$989C`, шаг 16 bytes,
полностью определены. Первые шесть words имеют формат
`slot,type_even_phase,type_odd_phase,lifetime,fade_mask,phase_mask`; последние
два words каждой записи равны нулю:

```text
00: 0007 0017 0020 0540 0000 003F
01: 0007 0017 0020 05A8 0000 003F
02: 000B 007B 0078 0B08 0000 003F
03: 000B 007B 0078 19AC 0000 003F
04: 0009 0019 001A 0180 0001 007F
05: 000A 001B 001C 0180 0000 001F
06: 000B 001D 001E 0180 0000 001F
07: 000C 0001 0002 0180 0000 003F
08: 000D 0003 0003 0180 0000 003F
09: 000E 0005 0005 0180 0000 003F
0A: 0009 0019 001A 0440 0001 007F
0B: 000A 001B 001C 0440 0000 001F
0C: 000B 001D 001E 0440 0000 001F
0D: 000C 0001 0002 0440 0000 003F
0E: 000D 0003 0003 0440 0000 003F
0F: 000E 0005 0005 0440 0000 003F
10: 0006 0009 0000 0070 0000 001F
11: 0006 000E 000F 0400 0000 001F
12: 0005 0055 005A 1500 0001 003F
13: 0006 0056 0000 1500 0000 003F
14: 0007 0057 0000 1500 0003 007F
15: 0008 0058 0000 1500 0000 001F
16: 0009 0059 0000 1500 0003 00FF
```

`$FB9C` создаёт `$FF00/$FBED`, копирует эту шестёрку в `+$20…+$2A` и
задаёт `phase=4*RNG`. `$FBED` удаляется по global cleanup либо по нулю
lifetime. В остальные update он ждёт `(VBlank+phase)&phase_mask==0`, затем
выбирает первый/второй type по bit `phase_mask+1` и вызывает `$54E4` с
указанными slot и fade mask. Это исчерпывает все palette-only события всех
восьми stage event streams; отдельного скрытого кадрового автомата нет.

### Сжатый интерпретатор движения `$F5C1`

Красные flyers `$59A2` и children formation `$5E8E` исполняют один и тот
же ROM bytecode. Поле `+$17` задаёт число команд за VBlank, `+$14` — текущий
byte pointer, `+$12` — word pointer сценария. Биты byte последовательно
задают `X +/-1`, `Y +/-1`, смену sprite phase и конец блока. При конце блока
`+$12 += 2`: word `$F0xx` меняет число команд, обычный word задаёт новый
byte pointer, нулевой word загружает loop pointer из следующего word и
возвращает carry.

Важная ветвь, подтверждённая сравнением object state на MAME frame 1500:
если bit 7 установлен, `$F603` заново читает исходный byte, сохраняет
`byte & $1F` в `+$16`, увеличивает `CX` и прыгает прямо на `$F5EA`.
Следовательно bits 2…6 этой phase-команды являются данными: их нельзя
интерпретировать как движение или end marker. После буквального исправления
четыре красных объекта Python совпали с MAME по `(x,y,script,pointer,phase)`:

```text
$011F,$00DD,$9AEE,$B13E,$06
$014C,$00D5,$9AEA,$B3A0,$08
$016F,$00EC,$9AE8,$B382,$09
$019C,$00E9,$9AE4,$B188,$09
```

Точный HEX `$F5C1…$F639`:

```text
8a 4e 17 32 ed 8b 5e 14 26 8a 07 d0 d0 72 33 d0 d0 72
1d d0 d0 73 03 ff 46 04 d0 d0 72 1b d0 d0 73 03 ff 46
08 d0 d0 72 24 ff 46 14 e2 d7 f8 c3 d0 d0 73 e6 ff 4e
04 eb e1 d0 d0 73 e8 ff 4e 08 eb e3 26 8a 07 24 1f 88
46 16 41 eb dc 83 46 12 02 8b 5e 12 26 8b 07 23 c0 74
0f 80 fc f0 75 05 88 46 17 eb e8 89 46 14 f8 c3 26 8b
5f 02 89 5e 12 26 8b 07 89 46 14 f9 c3
```

### Столкновение R-9 с tilemap

Runtime handler R-9 — `$2027`. После движения и вывода он вызывает `$1EB5`.
Эта процедура сначала вызывает foreground sampler `$1E6C`, затем теми же
object coordinates вычисляет background cell из scroll words `$2EC9/$2ECD`.
Возвращаемые коды проверяются буквально:

```text
call $1EB5
cmp  AX,$0DFC       ; foreground
jb   player_death
cmp  CX,$07D0       ; background
jb   player_death
```

Границы движения внутри `$2027`: native object X `$015C…$02A0`, Y
`$009A…$0174`. Поля hitbox R-9 записываются как
`x-7, x+8, y-1, y+6` в `+$38…+$3E`.

### Object hitbox `$F578` и collision tables

Важно для воспроизводимого дизассемблирования: в собранном
`RTYPE_MAINCPU_REGION.bin` эта часть runtime лежит со смещением `$0400`
относительно 16-битных адресов, записанных в объектах и видимых в MAME PC.
Например, handler `$E601` читается с file offset `$EA01`, `$E64E` — с
`$EA4E`, а collision routine `$F578` — с `$F978`. Адреса ниже — runtime
адреса оригинала, не сырые file offsets.

`$F578` не использует размер нарисованного sprite. `SI` указывает на
активную collision-запись игрока/снаряда с границами
`left,right,lower,upper`; `BX` — на четыре signed extent врага в ES:

```text
enemy interval X = [object.x + ES:[BX+0], object.x + ES:[BX+2])
enemy interval Y = [object.y + ES:[BX+4], object.y + ES:[BX+6])
```

Это объясняет, почему прямоугольник по прозрачной рамке PNG неверен.
Перенесённые таблицы Stage 1:

| Object | Table | Signed extents X/Y |
|---|---:|---|
| `$55E9` | `$28DA` | `-7,+7,-7,+7` |
| red flyer `$596D` | `$2912` | `-10,+10,-10,+10` |
| ground walker | `$2982` | `-12,+12,-12,+12` |
| formation child | `$2A38` | `-10,+10,-10,+10` |
| `$60BA` parent | `$2C40` | `-16,+16,-24,+24` |
| `$60BA` shot / child | `$2C84/$2D84` | `-6,+6` / `-4,+4` |
| large terrain `$74B4` | `$3426` | `-12,+12,-12,+12` |
| targeting `$80E3` | `$3956` | `-16,+16,-20,+20` |
| animated `$86A6` | `$3AF6` | `-4,+4,-4,+4` |
| terrain-aware `$897E` | `$3C56` | `-12,+12,-12,+12` |
| common projectile | `$84C6` | `-2,+2,-2,+2` |
| boss orb/body/tentacle | `$44B2/$4526/$4CBE` | `±8 / ±10 / ±6` |

`$F694` обслуживает одноударные цели; `$F6DA/$F75F` сравнивают старый и
новый damage counter `object+$1F`, обрабатывая обычный shot, Beam/Force/Bits
и missiles в оригинальном порядке. Python больше не использует visual PNG
bounds там, где table уже установлена. Полное различение силы всех типов
оружия внутри `$F6DA` ещё не завершено.

Обычный shot хранится в одном из трёх объектов с collision-record внутри
объекта. `$F548` начинает с `SI=$04D6`, проходит ровно три записи с шагом
`$20` и для активной записи вызывает `$F578`. Поэтому лимит обычных выстрелов
равен трём, а не четырём. Узкий capture
`Build/Arcade/MAME/player_shot_state_probe` при одиночном fire даёт:

| MAME frame | object | anchor x/y | native collision bounds |
|---:|---:|---:|---|
| 1252 | `DS:$04C0` | `$01D3,$0110` | запись ещё инициализируется |
| 1253 | `DS:$04C0` | `$01E3,$0110` | X `$01D4…$01F2`, Y `$010C…$0114` |
| 1254 | `DS:$04C0` | `$01F3,$0110` | X `$01E4…$0202`, Y `$010C…$0114` |

Следовательно hitbox обычного shot относительно его native anchor равен
`x-15…x+15,y-4…y+4`. Для офлайн обрезанного 640×480 asset top-left это
rectangle `(-11,-1,50,15)`: snapshot sprite top-left `(155,104)` даёт
logical collision `[247,297)×[203,218)`. Python теперь использует именно
эту запись, а PNG остаётся только изображением.

Wave проверяется отдельной группой `$F4AA`: первая запись находится в
`SI=$00F6`, то есть внутри объекта `DS:$00E0`. Capture
`Build/Arcade/Audio/wave_shot/wave` подтверждает стабильные записи:

| MAME frame | object anchor x/y | native bounds X/Y |
|---:|---:|---|
| 1319 | `$01D3,$0110` | `$01D1…$01E3,$0108…$0118` |
| 1320 | `$01DB,$0110` | `$01D9…$01EB,$0108…$0118` |

Это `x-2…x+16,y-8…y+8` относительно native anchor. Composite Wave sprite
на frame 1319 начинается в native `(139,104)`, поэтому его реальный 640×480
collision rectangle равен `(dx=+10,dy=0,w=30,h=30)`, а не всей визуальной
ширине 133 pixels. Python теперь использует `$F4AA/$F578` bounds.

### Полное разделение weapon collision classes `$F6DA/$F75F/$F7F1`

Все три routines сохраняют старый `object+$1F`, пропускают обработку при
`object.x >= $02B4` и в конце делают `CMP old_damage,[BP+$1F]`. Поэтому ZF=1
означает «damage не изменился», ZF=0 — hit; callers строят flash/death именно
по этому сравнению. `object+$2F` — предел HP. Порядок классов фиксирован:

| Порядок | Helper | Collision records | Класс оружия | Изменение damage |
|---:|---:|---|---|---|
| 0 | `$F485` | R-9 | столкновение самого корабля | damage не добавляется; `record+$01=1` сообщает player hit |
| 1 | `$F493` | `$0076,$0136,$0156` | Force body `$0060` + два Bits `$0120/$0140` | не чаще одного раза за 16 VBlank (`$2EB6&$0F==0`) добавить 1 |
| 1 variant | `$F49B` | только `$0136,$0156` | два Bits, без Force body | та же cadence +1; используется `$F7F1` |
| 2 | `$F4AA` | `$00F6,$0116` | два Beam/Wave collision records | `AH=[record+$00]` есть power 4/8/12/16/20; добавить power, `record+$01 += HP-old_damage` |
| 3a | `$F4BF` | `$00B6,$00D6` + owner links `$00A8/$00C8` | два paired missile records и их linkage | при active missile record добавить 1; owner pair связывается с BP без повторного damage |
| 3b | `$F525` | `$00B6,$00D6` | consuming-вариант двух missiles | добавить 1 и очистить `record+$01`; используется `$F75F/$F7E4` |
| 4 | `$F548` | `$04D6,$04F6,$0516`, ровно 3 records | три обычных shots | добавить 1; накопитель impact `record+$01` очищается, если не исчерпан остаток HP |
| 5 | `$F560` | `$0176…$0456`, ровно 24 records | weapon-matrix projectiles Force/Bit types | `power=record+$01`; добавить power и очистить power после полного nonlethal расчёта |

Точные варианты routines:

- `$F6DA`: R-9 → Force+Bits `$F493` → Beam → missiles `$F4BF` → ordinary
  shots → 24 matrix projectiles.
- `$F75F`: тот же порядок, но missiles вызываются через consuming `$F525`.
- `$F7E4`: сохраняет damage и входит в `$F75F` после шага R-9, то есть объект
  не проверяет столкновение с кораблём, но принимает все weapon classes.
- `$F7F1`: R-9 → Bits-only `$F49B` → Beam → missiles `$F4BF` → ordinary
  shots → matrix; непосредственный Force-body record `$0076` исключён.

Границы групп следуют не из графики: это буквальные адреса records и counts в
`$F493/$F49B/$F4AA/$F4BF/$F525/$F548/$F560`. Порт обязан сохранять этот
порядок и не суммировать несколько одновременных hits до ROM-эквивалента.

### Смерть R-9, взрыв и директор респавна

Трассы `Build/Arcade/MAME/death_probe`, `respawn_probe`,
`player_write_probe/player_writes.csv` и `stage1_player_trace` подтверждают
объект R-9 в `DS:$0020` и stage director в `DS:$0000`. При настоящем
столкновении runtime handler R-9 меняется с `$2027` на `$22CD` инструкцией
в районе `$22AA`. Проверка ландшафта перед этим буквальная:

```text
call $1EB5
cmp  AX,$0DFC       ; foreground
jb   $2269
cmp  CX,$07D0       ; background
jb   $2269
test byte [BP+$37],$FF
jne  $2269
ret
```

Ветка `$2269` сначала очищает ammo/collision flags и проверяет capture-only
invincibility `$2FC6` и DIP bit `$4000`. При реальной смерти она освобождает
resource slot игрока, приобретает resource type `$09`, посылает звуковые
команды `0` и `$35` через `$0303`, записывает `object+$30=$1318`,
`object+$32=3`, handler `$22CD` и обнуляет scroll velocity words
`DS:$2EEC…$2EFA`.

Explosion script в `ES:$1318` состоит из пар sprite descriptor/duration:

```text
$1338,3; $133E,2; $1344,2; $134A,2;
$1350,2; $1356,3; $135C,4; $1362,0
```

Handler `$22CD…$2350` выводит эти записи, уменьшает duration, после нулевой
записи освобождает resource и переводит объект в `$1FC0`. `$1FC0` очищает
поля объекта R-9 и только после разрешения директора заново создаёт состояние
`$2027` в native coordinate `x=$01B0,y=$0100`.

Контрольная временная линия исходного ROM:

| MAME frame | Director `DS:$0000` | R-9 `DS:$0020` | Событие |
|---:|---:|---:|---|
| 1471 | `$10FA` | `$22CD` | зарегистрировано столкновение, начат взрыв |
| 1493 | `$11BB`, timer `$005F` | `$22CD` | директор вошёл в death delay |
| 1587 | `$11CC`, timer `$003F` | `$22CD` | закончился первый delay |
| 1588 | `$11CC` | `$1FC0` | объект R-9 очищен |
| ~1651 | `$0FA1` | `$1FC0` | закончился второй delay |
| 1720 | normal path | `$2027` | R-9 снова активен в `$01B0,$0100` |

`$11BB` является countdown-handler и по окончании ставит `$11CC` с
`timer=$003F`. `$11CC` при `timer=$0030` вызывает `$5579`, а при нуле
сбрасывает scroll accumulators/velocities, вызывает `$E865/$E8A0`, уменьшает
lives в `$2F32/$2F3A` и разветвляется на checkpoint либо game over.

Эта цепочка включена в семантический Python runtime 2026-08-24: отдельный
`PlayerLifecycle` фиксирует trace-границы +117/+180/+249, выбирает последнюю
достигнутую 14-байтную checkpoint-запись, а `Stage.reset_checkpoint` заново
строит Stage-1 ring из общего ROM-derived terrain manifest. Event pointer
ищется по точному progression key от `ES:$B993`; локального reset координат
нет. Цветной семантический renderer checkpoint других stages остаётся отдельным
долгом; активный полный запуск в это время использует совместимый World backend
Canonical через целевые Z80/FT812/TSFM/GS границы.

#### Checkpoint table и восстановление progression

Следующий участок расшифрован напрямую из runtime `$0FA1…$10FA` (в maincpu
region это file offsets `$13A1…$14FA` согласно правилу `+$0400`). `$0FA1`
уменьшает `director+$1E`, вызывает `$55B5` и переходит в `$0FB0`. `$0FB0`
после опустошения очереди объектов обнуляет scroll accumulators/flags, затем
выбирает сохранённую пару по номеру игрока:

```text
player 1: progression = DS:$2F38, checkpoint byte = DS:$2F42
player 2: progression = DS:$2F40, checkpoint byte = DS:$2F43
DS:$2F4B = progression
DS:$2F4A = 0
DS:$2F2D = checkpoint byte
```

Затем ROM с `BX=$B993` ищет event, у которого `ES:[BX]` точно равен
сохранённому progression, и записывает `DS:$2EFE=BX`. То есть респавн не
перематывает живой event pointer приблизительно: он восстанавливает его по
ключу из исходной event table и исполняет command найденной записи.

`$105C` и `$10AB` проходят checkpoint table `ES:$87FA` с шагом 14 байт:
первая процедура выбирает следующую запись, вторая предыдущую. Первые четыре
записи относятся к Stage 1 (последнее word содержит stage id 1):

| ES address | progression | FG strip source | BG strip source | FG velocity | BG velocity | packed config | stage |
|---:|---:|---:|---:|---:|---:|---:|---:|
| `$87FA` | `$0600` | `$0000` | `$0000` | `$0080` | `$0100` | `$0901` | 1 |
| `$8808` | `$06C0` | `$001E` | `$003C` | `$0080` | `$0100` | `$0901` | 1 |
| `$8816` | `$0A80` | `$00B4` | `$0168` | `$0080` | `$0080` | `$0901` | 1 |
| `$8824` | `$0FC0` | `$0186` | `$023A` | `$0080` | `$0080` | `$090A` | 1 |

Следующая запись `$8832` начинается с progression `$1500` и stage id 2,
поэтому не относится к Stage 1. Поля `+2/+4` — исходные offsets потоков
полос foreground/background: при `$06C0` это 3 и 6 полос по 10 bytes
(`$001E/$003C`), при `$0A80` — 18 и 36 полос (`$00B4/$0168`). Значение
`$023A` последнего BG checkpoint учитывает переход background к скорости
`$0080`.

Назначение последних полей теперь закрыто прямым дизассемблированием `$F01B`
(file `$F41B`). Индекс checkpoint умножается на 14, после чего ROM копирует:

```text
+0  -> saved/current progression `$2F38/$2F40,$2F4B`
+2  -> foreground strip source `$2EE4`
+4  -> background strip source `$2EE8`
+6  -> foreground X velocity `$2EEC`
+8  -> background X velocity `$2EF4`
+10 -> packed stage config
+12 -> stage id / palette base byte `$2FCD`
```

У packed config `$0901/$090A` low nibble выбирает запись resource/music
таблицы через `ES:$8C20`, high nibble сохраняется в `$2FC5` и передаётся
`$F3D8`. То есть `$090A` не является отдельной командой респавна и поля
`$0080/$0100` не являются координатами игрока. `$F01B` затем ставит ring
targets `$2EE6/$2EEA=$70`, trackers `$2EE7/$2EEB=0`, обнуляет scroll
accumulators, вызывает queue entries `$E865/$E8A0/$EC7B` и создаёт временную
неуязвимость `$F438/$F44E`. Для no-fire перехода Stage 1→2 allocator,
очерёдность и длительности этих записей теперь exact до VBlank 14000;
побайтовая точность всех VRAM/resource effects всё равно проверяется отдельно.

Назначение трёх queue entries также закрыто:

- `$E865` очищает foreground VRAM `$D000:$0200…$3FFF` парами
  `tile=$0FA0,attr=0`, оставляя HUD-область `$0000…$01FF`;
- `$E8A0` тем же шаблоном очищает все `$4000` bytes background VRAM `$D800`;
- `$EC7B` очищает sprite/collision records игрока (`$0020`, `$0120`,
  `$013C`, `$01B4`), восстанавливает HUD lives и вызывает `$4FD2` с текущим
  charge `DS:$003D`.

`$55B5`, вызываемый перед `$0FB0`, не очищает врагов: он проходит 15 записей
по 12 bytes с базы `DS:$2DF4`, ставит первый word `$8000` и word `+4=0`.
Условие `$0FB0` — точное равенство head/tail object queue
`DS:$2ED8==$2EDA`; только после её опустошения начинается rebuild. Это
исключает прежнее ошибочное толкование `$55B5` как общего enemy reset.

### Межуровневый автомат `$F130…$F365`

Event `ES:$BC0F` (`threshold=$14FE`) входит в `$F130`. `DS:$0020` — handler
главного объекта R-9; только при его штатном значении `$2027` выполняется
переход уровня. Если R-9 уже находится в другом состоянии, `$F138…$F152`
лишь обнуляет четыре 24-битные scroll velocity и возвращается.

Штатная ветвь `$F153` устанавливает global cleanup `$2FC4=1` и
invulnerability `$2FC6=1`, обнуляет все четыре 24-битных scroll accumulator,
все четыре velocity, ставит в очередь `$E865/$E8A0/$EC7B`, затем создаёт
объект priority `$FF00`, handler `$F1BF`. Две дополнительные queue-записи
`($ED93,$8BAA)` и `($ED93,$8BCE)` ставятся только при успешном создании.

`$F1BF` не использует номер кадра. Он ждёт точного равенства queue
head/tail `$2ED8==$2EDA`, повторно вызывает player/HUD reset `$EC7B`, затем:

1. По stage byte `$2FCD` читает word из `ES:$8BE0`, разбивает его на два
   tile code и пишет их в foreground `$D000:$1774/$1778` с attribute 5.
2. Вызывает palette/resource transition `$54E4` для slot 5 с параметром
   `$0010`.
3. Выбирает четырёхбайтную запись результата из `DS:$2FD8` (P1) либо
   `$3018` (P2), раскладывает восемь BCD-nibble в bytes `$3058…$305F`.
4. Ставит timer `$00E0` и handler `$F260`. На остатках `$10,$20,$30,$50,
   $70,$90,$A0` по одному открывает семь позиций foreground
   `$1D90,$1D94,$1D98,$1D9C,$1DA0,$1DA4,$1DA8`. До порога `$F308`
   показывает случайный digit `$0E20+(RNG&$0F)` с нормализацией A…F через
   `&7`; на пороге `$F332` фиксирует BCD digit. Пока менялась хотя бы одна
   позиция, каждый четвёртый VBlank отправляется sound command `$55`.
5. По нулю `$F2F2` выключает slot 5 через `$54E4`, ждёт ещё `$20` update в
   `$F34D`, удаляет transition object, записывает foreground velocity
   `$2EEC:$2EEE=$000080` и сбрасывает 15 records `$2DF4` через `$55B5`.

После возобновления progression достигает `$1500`; event `ES:$BC13`
передаёт command `$6404` в `$F01B`. Low 5 bits равны **4**, поэтому индекс 4
выбирает checkpoint `ES:$87FA+4*14=$8832`, то есть первую запись Stage 2.
Непрерывная no-fire трасса фиксирует причинную последовательность без
зашитых frame-условий: `$FF00/$F1BF` выделен на frame 13288, queue barrier
заканчивается на 13293, transition slot освобождается на 13549, `$F01B`
выделяет `$FFFE/$F44E` на 13553, а его 128-pass timer освобождается на 13681.

### Офлайн HQ-цвета resource types Stage 1

Аппаратный palette slot не является постоянной палитрой: manager повторно
использует освободившийся номер для другого resource type. Поэтому один
`PALxx`-атлас нельзя считать цветом конкретного врага. Инструмент
`Source/Tools/m72_stage1_resource_hq.py` один раз сопоставляет type/slot по
ROM resource table `DS:$2114`, берёт оригинальные 16 pens из M72 palette RAM
и офлайн перекрашивает уже масштабированную геометрию FullHQ. Runtime читает
только готовые `Assets/Converted/Arcade/ResourceHQ/*.bin`.

На frame 1500 стабильные пары: type `$0D`/slot 5 (red scripted flyer),
`$56`/slot 6 (enemy projectile), `$0C`/slot 7 (formation), `$1E`/slot 8 и
`$1F`/slot 9 (ground walker). SHA256 источников и результатов записаны в
`Assets/Converted/Arcade/ResourceHQ/stage1_resource_hq_manifest.json`.

### Взрывы уничтоженных врагов `$E7A6…$E864`

Обычный взрыв не является синтетической анимацией renderer. Враг после
weapon collision освобождает свой resource slot и меняет handler на один из
ROM players. Все четыре малых entry сходятся в `$E7C3`, ставят timer `$02`,
acquire resource type `$01` и переходят в `$E7D4`:

| Entry | sequence `object+$0E` | Использование Stage 1 |
|---:|---:|---|
| `$E7A6` | `$8574` | отдельные специальные малые объекты |
| `$E7AE` | `$8552` | projectile/children объекта `$60BA` |
| `$E7B6` | `$8506` | альтернативный общий взрыв |
| `$E7BE` | `$8530` | red flyer, ground walker, formation child, `$74B4`, `$86A6`, `$897E` |

`$E7D4` каждый VBlank прибавляет foreground delta, рисует descriptor из
`ES:[sequence+2]`, уменьшает byte timer и по нулю переходит к следующей
четырёхбайтной паре `(duration,descriptor)`. Нулевой duration освобождает
type `$01` и удаляет объект. Точный HEX `$E7A6…$E80B` (file
`$0EBA6…$0EC0B`):

```text
c7 46 0e 74 85 e9 15 00 c7 46 0e 52 85 e9 0d 00
c7 46 0e 06 85 e9 05 00 c7 46 0e 30 85 c6 46 0d
02 b0 01 e8 22 6a 88 5e 06 c7 46 00 d4 e7 a1 d0
2e 01 46 04 8b 5e 0e 26 8b 5f 02 e8 e8 33 fe 4e
0d 75 11 83 46 0e 04 8b 5e 0e 26 8b 07 23 c0 74
0b 88 46 0d f6 06 c4 2f ff 75 01 c3 8a 5e 06 e8
36 6a e8 e1 1b c3
```

Крупные враги `$60BA` и первый микро-босс `$80E3` после исчерпания HP
ставят handler `$E817`. Он acquire type `$01`, ставит timer `$01`, sequence
`$85FA` и проигрывает 64×64 кадры через `$E82D/$1C1B`. `$1C1B` является
двухзаписным emitter: сначала читает descriptor `BX+0…BX+4`, затем второй
`BX+6…BX+$0A`. Поэтому каждый указатель sequence обозначает 12-байтную пару,
а не один descriptor. Первый `$863C` равен
`(-32,-32,$05D4,$6000) + (0,-32,$05D4,$6800)`; вывод только первой записи
даёт ровно половину большого взрыва. Прямые death
ветви: `$65E4…$6606` и `$82A0…$82C2`. Точный HEX `$E817…$E864` (file
`$0EC17…$0EC64`):

```text
b0 01 e8 d2 69 88 5e 06 c6 46 0d 01 c7 46 0e fa
85 c7 46 00 2d e8 a1 d0 2e 01 46 04 8b 5e 0e 26
8b 5f 02 e8 de 33 fe 4e 0d 75 11 83 46 0e 04 8b
5e 0e 26 8b 07 23 c0 74 0b 88 46 0d f6 06 c4 2f
ff 75 01 c3 8a 5e 06 e8 dd 69 e8 88 1b c3
```

Общий enemy projectile `$E601` не использует `$E7xx`: collision в `$E64E`
переходит в `$E686`, где десять VBlank проигрывается таблица descriptors
`$8490 + 3*(timer & $0E)`, после чего resource type `$56` освобождается.
Python повторяет этот отдельный распад и не подменяет его обычным взрывом.

### Enemy `$897E`: парные terrain states `$89B0/$8AEE`

Оба handler начинают с `$F63A`, обслуживают счётчик направления и проверяют
до четырёх точек terrain на расстоянии `$18` от центра. `$89B0` выбирает
обычное вертикальное направление к R-9. Если хотя бы одна запрошенная ось
сдвинулась, handler не меняется; только ноль выполненных движений ставит
`object+$22=$03FF` и handler `$8AEE`.

`$8AEE` — самостоятельное состояние, а не постоянный boolean-разворот:
vertical target в нём зеркален. Недоступная вертикальная ветвь записывает
`+$22=1`; после любого выполненного движения counter декрементируется и по
нулю возвращает `$89B0`. Если не сдвинулась ни одна ось, возврат в `$89B0`
происходит сразу. Старый Python оставался в зеркальном направлении после
успешного движения; буквальный перенос этих переходов устранил первое
allocator-расхождение на VBlank 5219.

### Enemy `$55E9`: terrain-bound state machine

Entry `$55E9` создаёт `$8010/$5629`, декодирует `(x,y)` через `$F88C`,
параметр `byte+$11=(CX>>4)&7` через `$F926`, acquire resource type `$0F` и
выбирает script `$9AB2` при `x<$0150`, иначе `$9A96`.

```text
51 b9 10 80 ba 29 56 e8 b3 ad 59 72 29 e8 93 a2 e8 2a
a3 b8 0f 00 e8 ec fb 88 5c 06 bb b2 9a 81 7c 04 50 01
72 03 bb 96 9a 89 5c 12 26 8b 07 89 44 14 c6 44 17 02
c3
```

Состояния подтверждены прямыми переходами ROM:

| Handler | Действие |
|---:|---|
| `$5629` | `$F5C1`, foreground delta, descriptor `$2826/$282C`, три terrain probes `$1E6C` |
| `$5620` | каждый update вызывает `$0689` с `AX=$FF00`, затем прыгает только в общую часть `$562C`; handler остаётся `$5620` до явного terrain-перехода |
| `$56C0` | 31-frame landing animation `$2832/$284A` |
| `$5704` | horizontal velocity `+$0100/-$0100`, animation `$2862/$287A`, два forward terrain probes |
| `$57B1` | 31-frame turn animation `$2892/$28AA`, затем новый script `$9AB2/$9AA2` |

Выбор стороны использует не сравнение: ROM выполняет `AND byte+$16,$0C` и
`JP`. Чётная parity результатов `$00/$0C` выбирает первую таблицу, `$04/$08`
— вторую. Этот автомат перенесён в `TerrainBound55E9`; sprite/collision
checkpoint первого carrier теперь exact по state/X/Y/timer на snapshots
2139,2160,2180,2200,2220,2250,2280,2300,2320,2350.
Поля Q8 `+$03/+$07` при `$03A6` не очищаются. Поэтому `$5620` обязан
использовать унаследованный `Yfrac`, а `$03EC` оставляет получившийся остаток
следующему владельцу того же FIFO-slot; подмена `$5620` одноразовым `Y-=1` с
возвратом в `$5629` меняет и lifecycle, и последующие координаты объектов.

### `$55E9 → $5811 → $586A`: носитель и улучшатель оружия

Уничтожение объекта `$55E9` подтверждается не обычным destructor: carry из
`$F694` во всех его фазах переходит в `$5811`. Эта процедура:

1. вызывает `$F50C`, release текущего resource slot;
2. ставит explosion event `$E8BD/$86EC`, sound command `$50`;
3. создаёт отдельный explosion object `$A000/$E7BE` в прежних `(X,Y)`;
4. преобразует исходную запись в pickup: выбирает пару из
   `ES:$27FE + 4*(object+$11 & 7) + ($2EB6&2)`, где low byte — resource type,
   high byte — pickup type;
5. acquire нового resource, обнуляет animation phase `+$14` и ставит handler
   `$586A`.

Таблица `ES:$27FE` (две допустимые пары на исходный index):

| `+$11&7` | bit `$2EB6&2=0` | bit `$2EB6&2=2` |
|---:|---|---|
| 0 | resource `$0A`, pickup `$00` | `$0A,$00` |
| 1 | `$0A,$02` | `$0A,$02` |
| 2 | `$0A,$04` | `$0A,$04` |
| 3 | `$0A,$0A` | `$0A,$0A` |
| 4 | `$0A,$06` | `$0A,$06` |
| 5 | `$56,$08` | `$56,$08` |
| 6 | `$0A,$0A` | `$0A,$00` |
| 7 | `$0A,$0C` | `$0A,$0C` |

`$586A` каждые 8 VBlank увеличивает `+$14` modulo 12. Pickup type `$08`
рисуется отдельной 12-frame таблицей `ES:$27B6`; остальные используют
descriptor `ES:$278C + 6*type`. Каждые 32 VBlank `$54C4` переключает palette
group `$0A/$0B`. Объект получает foreground delta, проверяет R-9 через
`$F485` с collision table `$2784`, общие bounds `$1D6B` и stage end flag.
Точные четыре signed extent `$2784` равны `(-16,+14,-14,+14)`.

При столкновении `$5947` выполняет sound `$3A`, event `$E8BD/$86F4`, затем:

- для pickup type `<8`: `byte DS:$0037 += 1`, `DS:$003C = type`;
- для type `>=8`: `type -= 8`, читает word **без дополнительного умножения**
  из `ES:$281E+type` и увеличивает указанный byte RAM. Для реально выдаваемых
  чётных типов это `$08→DS:$0033`, `$0A→DS:$0036`, `$0C→DS:$0035`;
- ветвь `DS:$0036` дополнительно превращает object в 16-VBlank indicator
  `$5914`, следующий за `(player.x-$1F, player.y)`, resource type `$09`;
- затем release pickup resource и `$03EC` удаляет object.

Семантика выводится из полного fixed-object графа, а не по внешнему виду:
`$0033` — число двух Bits (`$2CE5/$2EA6`), `$0035` — missile enable для
paired launchers `$3304/$3364`, `$0036` — speed tier, непосредственно
индексирующий таблицу Q8 скорости R-9 `ES:$11B0`. Полный контракт всех bytes
`$0033…$003F` приведён выше.

Критический HEX death→pickup `$5811…$5869`:

```text
e8 f8 9c 8a 5e 06 e8 24 fa b9 bd e8 ba ec 86 e8 61 ab
b1 50 e8 db aa b9 00 a0 ba be e7 e8 75 ab 72 0c 8b 46
04 89 44 04 8b 46 08 89 44 08 8a 5e 11 81 e3 07 00
03 db 03 db a1 b6 2e 25 02 00 03 d8 26 8b 87 fe 27 88
66 11 e8 91 f9 88 5e 06 c6 46 14 00 c7 46 00 6a 58 c3
```

Критический HEX применения pickup `$5947…$596C`:

```text
b1 3a e8 b7 a9 b9 bd e8 ba f4 86 e8 2f aa 8a 46 11
3c 08 73 8d fe 06 37 00 a2 3c 00 8a 5e 06 e8 d5 f8
e8 80 aa c3
```

Управляемый MAME input для evidence: `DOWN` frames 2000–2037 переводит R-9 в
native Y `$00CF`; дальше остаётся штатный периодический fire (5 кадров из 36),
то есть обычные shots, а не удержанный Beam. Получены checkpoints:

| Snapshot | Carrier/pickup slot | X | Y | Дополнительное состояние |
|---:|---:|---:|---:|---|
| 2200 | `$5629` | `$0232` | `$00C4` | carrier resource type `$0F` |
| 2220 | `$586A` | `$0222` | `$00C5` | pickup type `$00`; отдельный `$E7D4` explosion |
| 2338 | `$586A` | `$01E7` | `$00C5` | `DS:$003E=0` |
| 2346 | `$586A` | `$01E3` | `$00C5` | последний плотный snapshot до pickup |
| 2348 | object отсутствует | — | — | `DS:$003E=1`, Force scheduler потребил pending `$0037` |

Evidence: `powerup_carrier_hit_probe3`, `powerup_pickup_probe` и плотный
`powerup_pickup_exact`. Предыдущие `powerup_carrier_probe`/`hit_probe`/
`hit_probe2` сохранены как отрицательные контрольные опыты: соответственно
неверный Y вверх, слишком низкий Y и удержанный Beam без очереди shots.

Python теперь реализует carrier→explosion `$E7BE`→pickup `$586A`, таблицу
`$27FE`, native pickup collision `$2784`, bounds `$1D6B` и raw effects
`$0033/$0035/$0036/$0037/$003C`. Первый type `$00` переводит подтверждённое
состояние в `force_level=1`; геометрия самого Force, его attach/detach/return
реализована ниже буквальным автоматом `$24CE…$2CE4` и не заменяется фиктивным
sprite.

Resource type `$0A` добавлен в офлайн ResourceHQ. Источник цвета нашёлся в
более раннем каноническом checkpoint frame 4500/slot 1; новый pickup capture
служит резервным источником поиска. Файл
`RTYPE_SPRITES_TYPE0A_HQ_ARGB4444.bin`: 6635520 bytes, SHA-256
`BF50035AA1C3556A6CABF9B1F6C808C97467231974A2913F7211E99F0B33EA5D`.

### Начало Force-автомата после первого pickup

Постоянная player-object запись `DS:$0060` имеет handler `$24CE`. При
изменении `DS:$003E` он сравнивает новый уровень с `object+$12`, берёт
`ES:$1430 + 2*level` и делает непрямой jump. Точные первые entries:

| Level | Handler | Действие entry |
|---:|---:|---|
| 0 | `$2682` | `(X,Y)=($0080,$0020)`, release palette, скрыть object |
| 1 | `$26AD` | `Y=$0100`, level в `+$12`, acquire resource `$56`, `+$3A=1` |
| 2 | `$26D0` | сохранить level, reacquire `$56` |
| 3 | `$26E9` | сохранить level, reacquire `$56` |

После type `$00` pickup плотные snapshots `powerup_pickup_exact` показывают:

| Snapshot | Force `+$04,+$08` | `+$06` | `+$12` | `+$3A` |
|---:|---|---:|---:|---:|
| 2346 | `$0080,$0020` | `$FF` | `$0000` | `$0000` |
| 2348 | `$0080,$0100` | slot type `$56` | `$0001` | `$0001` |
| 2350 | `$012B,$0100` | тот же slot | `$0101` | `$0001` |
| 2360 | `$013A,$0100` | тот же slot | `$0301` | `$0001` |
| 2370 | `$0149,$0100` | тот же slot | `$0001` | `$0001` |

High byte `+$12` меняется внутри последующих motion/animation routines и не
является частью level. Полный внешний автомат записи `$0060` замыкается так:

| Handler | Точное состояние |
|---:|---|
| `$24CE` | свободный Force возвращается к выбранной стороне R-9; сохраняет прошлый Q8 X, по `$2F23&$40` включает history-return, ведёт X через `$2C94`, Y/terrain через `$2AB4`, затем проверяет захват `$F485` |
| `$2581` | attached: `X=R9.X±$18`, `Y=R9.Y`; сторона хранится в `+$0A`; следующий `$2F23&$40` задаёт Q8 X velocity `±$0900`, очищает `$003F` и переводит в `$2614` |
| `$2614` | detached: интегрирует `+$30`, выполняет `$2702`, проверяет следующий X terrain probe; вне чистого диапазона `$0150…$029F` возвращает handler `$24CE` |
| `$2702/$2736` | при `X>=$0140` проверяет четыре VRAM cells вокруг Force; только code `$09F6` заменяется парой `$0FA0/$0000` |
| `$2878/$297C/$2A10` | отдельные descriptor selectors для return/attached/detached; level 1/2 имеют шестикадровые rings, level 3 — direction→group table `$15AE`, four-frame nested tables `$1488` и detached blocks `$149A` |

`$2C94` использует асимметричные Q8 скорости `+$0180/-$0140`, target `$01A0`
или `$0238`, либо задержанный X из 16-word history `$1D60`. `$2AB4` делает
девять проб слева направо, различает foreground `<$0DFC` и background
`<$07D0`, считает протяжённость препятствия вверх/вниз, выбирает `±$0200`,
ограничивает Y диапазоном `$0098…$0178`; после достижения X-окна Y следует
задержанной history `$1D40`.

#### Точная проверка Force у головы Dobkeratops

Диагностический режим `mame_reference.lua` может на одном заданном кадре
установить только постоянную запись `DS:$0060`, после чего записывает результат
неизменённых World-ROM handlers. Две трассы начинаются на MAME frame 9480 при
активном body `$9C70`, `(X,Y)=($026E,$0100)`, hitbox `ES:$4526 =
(-10,+10,-10,+10)`:

| Начало Force | Результат оригинального ROM |
|---|---|
| `X=$01E0,Y=$0100,vx=$0900` | `$2614` доходит до `$0255`, probe следующего X встречает foreground wall и ставит `$24CE`; `$2AB4` ведёт Y `$00FE,$00FC,$00FA,$00F8,$00F6,$00F8,$00F6…` |
| `X=$01E0,Y=$00F8,vx=$0900` | верхний проход свободен: `$2614` достигает `$0279`; `$F75F` фиксирует повреждение головы на frame 9501 и повторно на 9517, то есть строго по cadence `$2EB6&$0F==0` |

Это доказывает две детали, которые нельзя «сглаживать» в порте. Видимое
двухпиксельное колебание свободного Force у центральной стены является
поведением ROM `$2AB4`, а не задержкой Python. Голова достижима Force не через
центральный solid row, а через коридор Y=`$00F8…$00FC`; Python повторяет оба
пути и damage `30→29→28`. Эталонные CSV:
`Build/Arcade/MAME/force_probe_y0100/force_probe.csv` и
`Build/Arcade/MAME/force_probe_y00F8/force_probe.csv`.

Python `Source/Python/rtype_port/force.py` исполняет эти состояния в native
M72/Q8 координатах и выводит resource `$56` через общий офлайн HQ atlas.
Правая кнопка мыши или правый Alt подаются как один edge; Force body участвует
в общей проверке `$F493`. Сам `$F493` последовательно проверяет Force
`DS:$0076`, Bit 1 `$0136` и Bit 2 `$0156` и возвращает первое пересечение:
наложение нескольких защитных объектов не умножает урон одному врагу. В
многоударных dispatchers `$F6DA/$F75F` найденное пересечение добавляет один
damage только при `($2EB6 & $0F)==0`; одноударный `$F694` сразу возвращает
попадание без этого cadence. Common projectile `$E601` проверяет Force
напрямую в `$E64E…$E657` каждый VBlank и начинает десятикадровый breakup
`$E686`, но не входит в Wave/ordinary-shot scans. Python повторяет эти три
ветви раздельно. Это закрывает движение, анимацию, attach/detach/return, body
collision и `$09F6` terrain mutation. Отдельный
24-record weapon-matrix `$3959` (лучи Force/Bit) остаётся самостоятельным
автоматом. Его unattached ветвь `$3D7B…$3EA6` уже перенесена: ROM matrix
выбирает 1/2/4 направления для level 1/2/3, общий `$0099` latch занимает
первый свободный fixed slot в каждой тройке, `$3EA7/$3EC4` задаёт resource
`$02`, Q8 velocities и descriptors `$2030/$2036/$203C/$2042/$2048`.
Attached type `$00` также перенесён: callbacks `$3F28…$4293` создают три
группы по 2/8 связанных fixed records для level 2/3; сохранены staggered delays
`1,3,…,15`, powers `2,0,0,1,0,0,1,0`, resource `$3D`, lifetime `$70` и
previous-record termination. `$42B1/$42DD/$4311` округляет anchor Force к
сетке 8+4, исполняет четыре вектора `$2086`, оба terrain probe каждого record
`$2056` и descriptor selection `$209A`; зеркальная группа выполняет
`$448E/$44BA/$44EE` с `$2096/$20A2`. Terminal streams `$4467/$456A` идут
назад по `$20F4…$210C`. Attached weapon types `$02/$04/$06` с callbacks
`$4591…$4EAE` также перенесены. `$02/$04` используют две 3/6-record history
цепи, exact tables `$2114/$2124/$212C`, descriptor roots `$218C/$21A4` и
terminal `$21BC`. `$06` сохраняет отдельные автоматы: 16-frame four-part
beam `$49CF`, moving continuation `$4C6A` и малые projectiles
`$4E0F/$4E42/$4E88`; используются исходные descriptor/hitbox ranges
`$21DC…$26DC`, а не общий синтетический снаряд. Python regression содержит
102 теста и headless Stage 1 smoke до VBlank 2000.

Статус `$06` здесь означает реализованный самостоятельный state graph, но не
финальную trace-equivalence: Python strip gate пока опрашивает 11 native точек
через `collision_codes`, тогда как V30 `$4ABB…$4C1E` шагает BL/DI прямо по
двум tile rings. До покадрового совпадения при wrap и проверки внешнего
collision field `+$17` family `$06` не считать окончательно закрытой.

Оба Bit-объекта также выполняются в Python из `$2CE5…$3066`: сохранены два
отдельных 16-word X/Y history ring, IRQ current/change bytes `$2F25/$2F26`,
ROM offset grid `$15DE`, speed ramps `$16DE/$171E`, descriptors
`$175E/$17A6`, collision `$17EE`, resource `$56` и terrain `$2736`. После
этой ветви regression содержит 105 тестов. Paired missiles `$3304…$38D4`
остаются следующим незакрытым player-owned автоматом; они не подменены
обычными Python shots.

### Enemy `$80E3`: player-targeting state

Entry создаёт `$A000/$8138`, получает `(x,y)` через `$F88C`, задаёт HP `$1E`,
activation timer `$01C0`, RNG offset `+$14`, сохраняет две target positions
`(player.x+$F0, player.y)` и acquire resource types `$20/$55`.

```text
51 b9 00 a0 ba 38 81 e8 b9 82 59 72 47 e8 99 77 c6 44
1f 00 c6 44 2f 1e c7 44 26 c0 01 e8 e6 6c 25 1f 00 89
44 14 c7 44 16 ff ff a1 24 00 05 f0 00 89 44 24 89 44
30 a1 28 00 89 44 28 89 44 32 b0 20 e8 c6 d0 88 5c
06 b0 55 e8 be d0 88 5c 3c c6 44 3d 00 c3
```

Вывод `$8138` передаёт `$1BCC` две соседние шестибайтные записи таблицы
кадра. Первая рисует левую половину 64×64 объекта, вторая находится по
`descriptor+6` и рисует правую половину с тем же object anchor/palette.
Например, базовый кадр `$38A2` содержит descriptors
`(-32,-40,$01D0,$6000)` и `(0,-40,$01D4,$6000)`. MAME frame 3500
подтверждает тот же состав для фазы `$38AE`: две записи Sprite RAM с codes
`$01E0/$01E4`, attr `$6007`, anchors X `$01FF/$021F`, Y `$00E8`.
Один descriptor визуально обрезает первого микро-босса ровно пополам.

Каждые 32 update `$8138` сдвигает прошлую target position, берёт новую
`(player.x+$A0, player.y)`, вызывает 16-направленный классификатор `$1D89`
и читает Q8 velocities из `ES:$3966 + returned_offset`. Offset всегда один
из `$00,$04,…,$3C`. Перед применением X/Y velocity объект отдельно проверяет
точку на 48 native pixels впереди через `$1EB5`; движение разрешено только
при foreground `>= $0DFC` и background `>= $07D0`. Базовые sprite pointer
таблицы `$3866/$386E/$3876/$387E` выбираются по положению игрока и знаку X
velocity.

После activation `+$26=0` вертикальное окно атаки проверяется буквально:
`player.y-$18 < object.y <= player.y+$18`. Каждый успешный update уменьшает
`+$14`; при нуле счётчик перезагружается из difficulty table
`ES:$3856=(20,18,10,08)`, `+$3A` получает `$001F`, handler меняется на `$82D6`.
Атака длится 31 update. При timer `$0D…$08` X Q8 velocity равна `+$0200`, при
`$07…$01` — `-$00C0`; descriptor выбирается из `$3886/$388E` смещением
`(timer & $18) >> 2`. На timer `$10` вызывается `$8355`.

`$8355` создаёт ровно два объекта resource type `$09`. `$842C` копирует
позицию parent, смещает X на `±$30` и получает difficulty-dependent X velocity
из `ES:$385E=(-$0400,-$0500,-$0700,-$0900)` со знаком по стороне игрока.
Он рисует две соседние descriptor-записи одной из таблиц `$3926…`, движется
через `$0672`, проверяет R-9 hitbox `$395E=(-24,+20,-2,+2)` и bounds.
`$83DF` — неподвижная вспышка запуска: X смещён на `-$26` или `+$32`, первые
4 update невидимы, затем 15 update проходят descriptor sequence `$390E` либо
`$38F6`; entry выдаёт sound command `$59`.

MAME object-write trace `Build/Arcade/MAME/enemy_80e3_attack_trace` подтверждает
реальные переходы одного object slot `DS:$0D80`: `$8138` frame 2511,
`$82D6` frame 2514, возврат `$8138` frame 2545; затем атаки начинаются на
2577, 2640, 2703 и далее с периодом 63 кадра. На frame 3500 отдельный child
`DS:$1BC0` имеет handler `$842C`, `(x,y)=($0192,$0110)` и `vx=-$0400`.
Python-классы `PlayerTargeting80E3`, `Targeting80E3AttackFlash` и
`Targeting80E3Projectile` повторяют этот граф, таймеры, обе половины спрайтов,
hitbox и score pointer `$86F8` (500 очков); переходы закрыты regression-тестами.

Два Python-рывка возле этого автомата не являются эффектом ROM. Инструментальный
прогон показал два первых обращения renderer: VBlank 2512 загружал normal
resource `$20`, VBlank 2517 — damage-flash resource `$55`; ленивое чтение
полного 4096-cell банка и построение первых 16 surfaces происходило внутри
55-Hz кадра. Покадровый MAME reference
`Build/Arcade/MAME/miniboss_double_flash_reference`, frames 3488–3512, имеет
обычную чередующуюся scroll-разность без двух выбросов. Python теперь до
gameplay предсоздаёт все surfaces, достижимые через pointer tables
`$3866/$386E/$3876/$387E/$3886/$388E`, эффекты `$38F6/$390E` и projectile
descriptors `$3926…$3950`. Это только устранение runtime I/O/конверсии;
последовательность ROM, координаты и пиксели не изменены.

### Общий enemy projectile `$F63A/$E601`

`$F63A` увеличивает object field `+$26`. При достижении `+$2A` либо верхней
границы `+$2C` сбрасывает его в ноль. Если word `+$28` ненулевой, создаёт
`$A000/$E601`, копирует parent `(x,y)`, вызывает `$1D89` относительно объекта
R-9 в `DS:$0020`, читает пару Q8 velocities из
`ES:[parent+$28 + direction_offset]` и acquire resource type `$56`.

```text
ff 46 26 8b 46 26 3b 46 2a 74 0b 3b 46 2c 73 01 c3
c7 46 26 00 00 f7 46 28 ff ff 74 3c b9 00 a0 ba 01 e6
e8 3e 0d 72 33 8b 46 04 89 44 04 8b 46 08 89 44 08 56
bb 20 00 e8 14 17 8b 76 28 26 8b 00 26 8b 48 02 5e 89
44 30 89 4c 32 c7 44 20 03 00 b0 56 e8 5c 6b 88 5c 06
c3
```

`$E601` каждый update применяет `+$30` через Q8 X integrator `$0672`, `+$32`
через Y integrator `$0689`; descriptor выбирается из `$84AE` по
`((object_slot/8 + $2EB6) & $18)`. Затем идут player collision `$F485` и
отдельная Force/Bit-проверка `$E64E: BX=$84C6,SI=$0076,CALL $F578`. Обычные
shot/Wave этот object не сканируют.

Ветка `$E659…$E67B` сначала проверяет `($2EB6 & 1)`: на нечётном VBlank сразу
возвращается. Только на чётном VBlank `$1EB5` читает обе карты; projectile
переходит в breakup `$E686`, если foreground `<$0DFC` **либо** background
`<$07D0`, иначе `$1D6B` проверяет bounds. Python прежде ошибочно проверял
только foreground каждый update, поэтому ракета `$1488` могла разрушиться,
ещё не покинув ходячую ракетницу. Теперь `EnemyProjectile` повторяет чётность,
две карты и порядок bounds буквально.

### Timed control `$F366/$F3C1`

`$F366…$F397` выбирает byte `$2F44/$2F45` по active-player selector `$2F20`.
Если byte был нулём, entry ставит его, немедленно отправляет sound command
`$21`, создаёт `$1000/$F3C1` и записывает `+$10=$0180`, `+$12=$0020`.
Повторный вызов использует `$2FC5` как индекс: immediate command берётся из
`ES:$8C16`, delayed command — из `ES:$8C0C`, timer равен `$0100`.
`$F3C1…$F3D7` при `$2FC4==0` уменьшает timer; по нулю либо при global cleanup
отправляет `+$12` через `$0303` и освобождает record `$03EC`.

### Enemy `$60BA`: многофазный автомат перед боссом

Stage 1 содержит две event-записи этого типа: `ES:$BBE3` с command `$2C07`
и `ES:$BBF3` с `$2C06`. Entry `$60BA` создаёт object `$8020/$610D`, получает
координаты через `$F88C`, дважды вызывает RNG `$EDE9`, acquire resource types
`$21/$55`, берёт difficulty-слова из `ES:$2B40` и задаёт HP `$1E`.

Основной вывод во всех состояниях является двухзаписным composite через
`$1C1B`: после descriptor по текущему `BX` ROM выводит соседнюю запись
`BX+6`. Например, корень `$2BC8` содержит левую половину
`(dx=-32,dy=-24,code=$0380,attr=$6000)`, а `$2BCE` — правую
`(dx=0,dy=-24,code=$0384,attr=$6000)`. Одиночный вывод `$2BC8` даёт ровно
наблюдавшуюся ошибку — половину 64×48 native объекта. То же правило действует
для пар `$2BD4/$2BDA`, `$2C28/$2C2E` и `$2C34/$2C3A`.

```text
51 b9 20 80 ba 0d 61 e8 e2 a2 59 72 45 e8 c2 97 e8 1c
8d 25 1f 00 89 44 28 b8 21 00 e8 15 f1 88 5c 06 b8 55
00 e8 0c f1 88 5c 3c c6 44 3d 00 8a 1e 2e 2f 32 ff 03
db 26 8b 87 40 2b 89 44 0c c7 44 0e 00 00 e8 e8 8c 25
3f 00 c6 44 1f 00 c6 44 2f 1e c3
```

Таблица состояний восстановлена прямыми переходами handler field `object+$00`:

| Handler | ROM-действие |
|---:|---|
| `$610D` | сторона R-9, Q8 velocities `X=-$0080,Y=-$0100`, descriptors `$2BC8/$2BD4/$2C28/$2C34`, две terrain probes слева |
| `$61B6/$61E3` | Y по 8, X на `+8/-8`, 15-frame landing из pointer table `$2B60/$2B68` |
| `$62BD` | 64-frame неподвижное состояние `$2B80/$2BE0`; при timer `$10` вызывает `$6715` |
| `$6243` | 80-frame движение с `X velocity=-$0100`, восемь pointers `ES:$2B70`; Y здесь не интегрируется |
| `$631B` | второй 15-frame landing, затем `$6392` |
| `$6392` | 72 VBlank с `Y velocity=+$0100` |
| `$6374` | пауза 64 VBlank, вызов `$6715` при timer `$10` |
| `$638C` | 128 VBlank с `X velocity=+$0100` |
| `$6380` | пауза 64 VBlank, вызов `$6715` при timer `$10` |
| `$6459` | Q8 velocities `X=+$0080,Y=-$0100`, две terrain probes справа |
| `$6502/$652F` | правый 15-frame landing |
| `$657C` | `$6715` при `$2EB6 & $7F == 0` выполняется до прибавления foreground scroll; затем финальное движение со scroll |

Во всех основных состояниях `$661A` переключает основной palette slot на
type `$55` каждые четыре VBlank после попадания. `$663E` увеличивает fire
counter `+$0E`; по difficulty reload проверяет вертикальную полосу R-9 и
сторону, затем создаёт `$6000/$66C8`. Projectile получает
`(parent.x,parent.y+$0A)`, resource type `$21`, Q8 X velocity из `ES:$2B48`
либо отрицательное `ES:$2B50`, descriptor `$2C7E/$2C78`.

`$6715` создаёт четыре children, когда parent правее R-9, и три, когда левее:
вторая запись восьмибайтной таблицы `$2C94…$2CB3` намеренно пропускается
ветвью `$6743`. Запись содержит `(x_velocity,y_velocity,direction,unused)`.
Каждый child `$5000/$67D5` получает resource type `$3C`, initial timer `$20`
и turn reload `ES:$2B58`. Основной descriptor берётся как
`$2CB4 + 6*direction`; поверх него рисуется восьмикадровый descriptor
`$2D54 + 6*($2EB6&7)` со смещением из `$2D14`.

После первых 32 update `$687D…$68EE` поворачивает direction на один сектор к
результату `$1D89` и читает новую пару velocities через difficulty pointer
`ES:$2C8C` (difficulty 0 — `$8F90`). `$6788/$67B3…$67C2` при parent.X левее
R-9 меняет знак X velocity и использует direction из `table+6`, а не из
обычного word. В opcode `$687D` записано `TEST word [BP+$22],AX`; узкая
linked-scheduler trace подтвердила, что AX содержит адрес текущего object slot.
Поэтому ветвь является точной проверкой `life_timer & object_slot`: например,
для slot `$10C0` и timer `$0800` результат нулевой, тогда как другие slots
входят в steering path. Перенесены ROM-векторы, пошаговый поворот, оба
descriptors, terrain/bounds и resource lifetime без прежней оговорки.

Projectile `$663E/$6688/$6694` записывает только integer X/Y. Дробный byte X
`object+$03` после `$03A6` не очищается и наследуется от предыдущего владельца
FIFO slot; это residue участвует в `$0672` и меняет дальнейнюю позицию child.
Python `Handler60BAProjectile` сохраняет этот byte буквально.

Handler `$66C8` при terrain/weapon carry в `$66F4` не освобождает object
record. Он release type `$21`, посылает sound `$50` и заменяет handler того же
slot на `$E7AE`. На следующем scheduler pass `$E7AE` acquire type `$01` и
проигрывает timer/descriptor sequence `ES:$8552`; только её sentinel удаляет
record. Bounds path `$6708` остаётся прямым release/delete без explosion.
Непрерывная трасса подтверждает один и тот же slot `$0D00`: collision frame
13186, `$03EC` frame 13210.

Python: `Handler60BA`, `Handler60BAProjectile`, `Handler60BAChild`. На
VBlank 7800 event pointer доходит до `ES:$BC07`; единственный достигнутый
неподдержанный handler теперь boss entry `$98FD`.

### Dobkeratops `$98FD`: parent и составные объекты

Event `ES:$BC03` при progression `$13A0` вызывает `$98FD`. Entry создаёт
только root `$3800/$9915`. Компоненты выделяются не в event frame, а первым
вызовом root на следующем scheduler pass; этот вызов создаёт следующую
иерархию (адреса и количества взяты из циклов ROM, не из изображения):

| Количество | Priority / handler | Начальное состояние | Resource |
|---:|---:|---|---:|
| 1 | `$3810/$9B26` | `x=$0328,y=$0128,timer=$0200`, rear body | `$15` |
| 1 | `$3818/$9B9B` | `x=$0358,y=$0100,timer=$0200`, vulnerable body owner | `$15`, затем `$16/$55` |
| 4 | `$3821/$9F63` | шесть bytes из `ES:$4394`, timer `$0280` | — |
| 18 | `$FF90…$FFA1/$A035` | десять bytes из `ES:$43AC…$445F` | `$17` |
| 1 | `$FFA8/$A133` | `x=$0277,y=$00BF`, motion `$4C76` | `$17` |

Root хранит timeout `$1000`. `$9A80` на каждом update сначала уменьшает его.
Пока жив хотя бы один из четырёх arena-writer (`root+$34 != 0`), скорости не
меняются. Когда последний writer дошёл до sentinel `$8000` и уменьшил счётчик
до нуля, `$9A8C…$9A97` устанавливает background X velocity
`$2EF4:$2EF6=$000040`; foreground остаётся остановленным после `$F429`.
Запись сделана после текущего `$0467`: callback следующего VBlank ещё содержит
accumulator, рассчитанный старой скоростью, а его object dispatch уже видит
`$0040`. Это фаза ROM scheduler, не фиксированный номер host frame.

Затем `$9A9F…$9AAD` различает два флага, которые нельзя объединять. `root+$24`
означает общий выход неповреждённого body через `$9C1B`: только эта ветвь
проходит `$9AAE` и ставит global cleanup `$2FC4=1`. Уничтожение body через
`$9D10` записывает `root+$32=1` и прыгает прямо в `$9AB3`, не включая global
cleanup. Timeout `$1000` также входит прямо в `$9AB3`. Поэтому штатно убитое
тело, rear body, 19 звеньев, debris и arena writers продолжают собственные
ROM handlers вместо мгновенного удаления. Сам `$9AB3` посылает sound command `$1B`,
ставит invulnerability `$2FC6=1` и переключает root на `$9AC8` с таймером
`$00C0`.
На остатке `$0010` отправляются sound commands `$1A/$1C` и ставится
`$2FC1=$FF`. По нулю `$9AE4…$9B04` оставляет invulnerability включённой,
восстанавливает обе 24-битные X-скорости точно как
`$2EEC:$2EEE=$000080`, `$2EF4:$2EF6=$000080` и удаляет root через `$03EC`.
Ветка преждевременного global cleanup `$9B05…$9B25` обнуляет обе 24-битные
скорости, удаляет root и отправляет sound command `$1A`.

На остатке `$0010` запись `$2FC1=$FF` переключает fixed-player handler на
`$2084…$2109`. Значение `$FF` выбирает цель `(X=$0200,Y=$00E0)`; direction
mask строится только если расстояние по оси не меньше 4 native pixels, а Q8
velocities берутся из speed-zero table `ES:[ES:$11B0]=$11BA`. В no-fire
трассе R-9 проходит `(01CC,010E)` на frame 13041, `(01F7,00E8)` на 13072,
`(01FC,00E3)` на 13076 и удерживает `(01FE,00E3)` с 13077.

Неповреждённый body не остаётся навсегда: `$9CE1…$9CEB` при `X<$0120`
переходит в общий `$9C1B`, отмечает связанный root завершённым, освобождает оба
palette resource и record. В эталоне slot `$0700` освобождён на frame 13124.

Event `$F429` сам состоит из `XOR AX,AX` и четырёх word-записей:
`$2EEC/$2EEE/$2EF4/$2EF6=0`; поэтому он останавливает обе скорости целиком,
а не только low word. Номера MAME frames 8176/9322/9770 являются проверочными
наблюдениями конкретного прохождения, но не условиями автомата.

Четыре `$9F63` — не отсутствующие спрайты, а невидимые collision/writer
owners. После timer `$0280` handler `$9F84` включает HP 1 и table `$46C4`.
Попадание, собственный timeout `$0900+(RNG&$1F)` либо damage body `>=15`
вызывает `$1E6C`, сохраняет foreground offset и переходит в `$9FE9`.
Вход `$9FAE…$9FDF` сначала пытается создать `$FE00/$E7B6` в `(x+4,y-4)`;
только успешный `$03A6` затем посылает sound `$52` и score task `$E8BD/$86F0`.
Далее на каждом чётном VBlank owner пишет code `$0FA0` и берёт следующий
signed bytewise delta из собственного пути `$46CC/$4754/$47C6/$482E`;
сложение low/high bytes выполняется без переноса. Sentinel `$8000` уменьшает
root counter `+$34`. Python `DobkeratopsArenaAnchor` теперь пишет тем же путём
в живую `Stage.tilemaps.vram[0]`; boss arena не воспроизводится MAME-кадрами.
Проверка `$9FF0` использует `$2EB6`, уже увеличенный IRQ `$0219` после callback
snapshot, поэтому эквивалент Python — parity `frame_counter+1`; прежняя parity
callback освобождала каждый writer на один VBlank раньше.

PC-trace `Build/Arcade/MAME/boss_transition_pc_exact/vram_writes.csv`
замыкает проверку всех путей. Каждая запись очистки имеет PC `$A010` — это
`POP DS` сразу после буквального `MOV word [D000:BX],$0FA0` в `$A00C`.
Получено ровно 239 записей, то есть сумма длин вместе с финальной итерацией,
на которой сначала очищается текущая cell, а затем читается sentinel `$8000`:

| Путь ES | Записей | MAME frames | Первая/последняя VRAM cell |
|---:|---:|---:|---:|
| `$46CC` | 68 | 9185…9319 через 2 | `$14C0` / `$141C` |
| `$4754` | 57 | 9185…9297 через 2 | `$1CEC` / `$181C` |
| `$47C6` | 52 | 8355…8457 через 2 | `$22EC` / `$241C` |
| `$482E` | 62 | 9185…9307 через 2 | `$28C0` / `$2A1C` |

Для каждой соседней пары адресов автопроверка повторяет две независимые
операции `AL+=CL; AH+=CH` из `$A023/$A025` и сравнивает результат с trace.
Все 235 ROM delta и четыре sentinel-итерации совпадают; это полная
побайтовая проверка постепенной очистки foreground арены.

Rear body `$9B26` первые `$0200` VBlank использует descriptor `$44AC`.
`$9B39` затем ведёт modulo-`$0180` animation: `$44AC` до `$00C0`, `$44A0`
на краях перехода и `$44A6` между `$00D0…$016F`. X каждый update получает
background delta `RAM:$2ED4`. После уже выполненного render он проверяет
`root+$32`; при уничтоженном body release type `$15` и ставит в том же
object slot handler `$E7BE`, который начинает полный взрыв на следующем pass.

Vulnerable body `$9B9B` сначала выводит `$44D2`. После `$0200` update он
release type `$15`, acquire `$16/$55`, проходит 63-frame emerge sequence
`$44DE`, затем `$9C70` задаёт damage counter `0`, limit `$1E` и циклически
выбирает восемь descriptors от `$44F6` по `((timer&$70)*3)/8`.
Hitbox table `$4526` равна `[-10,+10,-10,+10]` native pixels. При timer
`$30` вызывается mouth attack `$9D9E` (`$F000/$9E07`, resource `$3F`).

Во время intro `$9BB9…$9BE7`, когда timer после decrement становится `$0060`,
body создаёт четыре explosion records `$F280/$E7B6`. Для каждого record ROM
дважды вызывает RNG; X/Y получают signed offsets `(rng&$1F)-$10` от body.

Mouth projectile `$9E07` имеет priority `$F000`, trail timer `$40` и straight
timer `$20`. Каждый четвёртый update условие `trail_timer&3==0` вызывает
`$9DD9` и создаёт равноприоритетный `$9EC0` из текущих координат и velocity
parent; из-за linked scheduler новый trail начинает исполняться только на
следующем pass. После 32 update `$9E07` выбирает знак вертикального ускорения
по Y R-9 и переходит в `$9E78`: X уменьшается на 4, Q8 Y меняется каждые два
VBlank. `$9EC0` использует resource `$3F`, сохраняет phase offset, 32 update
летит прямо, затем копирует acceleration parent и продолжает `$9F18` с теми
же bounds. И orb, и trail наследуют неочищенные Q8 fraction bytes своих FIFO
slots. Эталонные первые allocations trail: frames 9361, 9365, 9369, 9373.

Попадание определяется `$F75F`. Если damage изменился, `$9CA8` ставит
sprite-flash timer `$10`; `$9CEC` сначала уменьшает timer и при
`$2EB6&4==0` временно выводит object через sprite resource type `$55`.
Одновременно `$9CAF…$9CCB` создаёт palette-animation object `$F800/$FC20`:

```text
+$10=$0010, +$20=$0003, +$30=$0023, +$32=$0016, +$34=$0006
```

`$FC20…$FC52` только когда `($2EB6 & 3)==0` вызывает `$5504` для tile
palette slot 6. При `$2EB6&4==0` он загружает type `$23` (синий flash), при
установленном bit 2 — type `$16` (обычный оранжевый); по окончании 16 VBlank
обязательно восстанавливает `$16`. Поэтому это не стадия босса и не выбор по
номеру кадра.

Fatal hit `$9D10…$9D2B` начисляет BCD-награду `ES:$8714`, записывает
`root+$32=1`, устанавливает body handler `$9D30`, pointer `$454E` и delay 1.
Это не 32-кадровый общий взрыв. `$9D30…$9D9D` последовательно обрабатывает
все 62 шестибайтные записи `ES:$454E…$46C1`
`(signed dx,signed dy,child handler)`. Перед каждой попыткой `$03A6` дважды
вызывается RNG: первый результат выбирает отсутствие sound либо `$51…$53`,
второй задаёт `(rng&1)|1`, то есть delay 1 с обязательным потреблением RNG.
Успешный child получает priority `$EF00`, координаты body+offset и auxiliary
pointer `$452E`; при отказе allocator pointer не продвигается и запись
повторяется. Sentinel `$8000` по адресу `$46C2` освобождает оба resource body
и его object slot.

Четыре допустимых child handlers сохранены буквально. `$E7B6/$E7BE` играют
свои односоставные resource-`$01` последовательности, `$E817` —
двухdescriptorную `$85FA`. `$E700` сначала возвращает без render, затем играет
`$8506`; на шестнадцатом pass `$E75C` получает terrain address для
`(x-$0C,y+$0C)` и заменяет ровно 16 cells на code `$0FA0` по auxiliary path
`ES:$452E…$454D`. Низкий и высокий bytes адреса складываются независимо;
attribute word не изменяется. Python исполняет все 62 ROM records, а не
рисует один приближённый эффект.

Узкая MAME write-trace `boss_palette_state_probe` установила полный путь:
`$5504…$5525` создаёт palette object для slot 6; `$5481…$54C3` разворачивает
16 RGB entries type `$16/$23` в staging buffers `DS:$27F4/$29D4/$2BB4` и
ставит dirty word `DS:$2E42`; `$52C2…$52F0` тремя `REP MOVSW` переносит их в
`CC00:$00C0/$04C0/$08C0`. На соседних reference frames 9500/9501 VRAM и
resource table неизменны, а в palette RAM меняется только bank 1 slot 6.

Основной силуэт корпуса действительно находится в background tilemap и имеет
attribute palette 6. `m72_boss_palette_tiles.py` поэтому офлайн рендерит для
секций S2/S3 две пары одного ROM `code/attribute` набора: `NORMAL9501` из
palette RAM 9501 и `FLASH9500` из 9500. Python выбирает готовую пару только по
ROM-derived 16-frame hit timer/`$2EB6&4`; runtime recolor отсутствует.
Манифесты с SHA-256: `Assets/Converted/Arcade/Stage1/Sections/
STAGE1_S2_BOSS_PALETTE_manifest.json` и `STAGE1_S3_BOSS_PALETTE_manifest.json`.

Каждая из 18 записей `ES:$43AC` содержит
`(x,y,descriptor,motion_pointer,parameter)`. `$A035` ждёт `$20` VBlank,
после чего `$A08B` читает шестибайтные motion steps
`(Q8 vx, -Q8 vy, duration|loop_bit)`. Low 12 bits — duration, bit 15
возвращает pointer к началу собственного сценария. Наконечник применяет тот
же interpreter, но каждый update выбирает descriptor через `$1D89` и table
`ES:$4CC6`.

Контроль Python и MAME на VBlank 8500 для одной и той же фазы motion:

```text
body: handler=$9C70, x=$026E, y=$0100, timer=$0066
tip:  x=$01FC/$01FD, y=$010F, motion pointer=$4C88, step timer=$0007
```

Однопиксельное расхождение полностью объяснено перекрывающимся форматом
координаты и больше не является неизвестным. `$0672` прибавляет Q8 velocity к
слову `[BP+$03]`: byte `+$03` — дробная часть X, byte `+$04` — младший byte
целого X; carry отдельно увеличивает byte `+$05`. `$0689` симметрично работает
с `[BP+$07]`, integer Y находится в `+$08/+$09`. Освобождение `$03EC` очищает
только handler `+$00`, integer X `+$04` и integer Y `+$08`; bytes `+$03/$07`
не очищаются. Поэтому новые звенья закономерно наследуют Q8 residue прежних
владельцев тех же 64-байтных slots.

На VBlank 7500 одна конкретная invincible-capture FIFO `$2054`,
head `$2EE0=$0044`, после 23 предшествующих allocation выдаёт `$99D7` slots в
следующем порядке. В скобках указаны унаследованные `(Xfrac,Yfrac)` именно
этого прохождения:

```text
$48AA:$1780(30,60) $48E0:$0EC0(9C,D8) $4916:$0800(40,00)
$494C:$1940(80,80) $4982:$1A00(A0,60) $49B8:$06C0(40,20)
$49EE:$07C0(40,00) $4A24:$1900(52,6C) $4A5A:$1980(24,DD)
$4A90:$1100(2D,2B) $4AC6:$1600(84,77) $4AFC:$1300(60,00)
$4B32:$1C00(80,00) $4B68:$0D00(40,60) $4B9E:$1040(C0,40)
$4BD4:$0F80(80,00) $4C0A:$19C0(A0,40) $4C40:$0D80(1A,B0)
$4C76:$1540(A6,2E)
```

Первые 18 строк — звенья, `$4C76` — наконечник. Эта таблица больше не зашита
в runtime: разные ввод и история выстрелов закономерно меняют прежних
владельцев слотов и Q8 residue. Python повторяет FIFO `$03A6/$03EC`, при bind
берёт реальные bytes `+$03/$07` выбранного slot и потому сохраняет общий ROM
контракт. Автотест с invincible snapshot сравнивает все 19 script roots,
motion pointers/timers и допускает единственный integer carry от иной FIFO
истории; независимая no-fire object-pool трасса до VBlank 14000 совпадает
строго, 2936/2936 allocation/free events.

`$A035/$A133` выводят и проверяют collision каждого звена уже во время
32-pass intro. В `$A08B` collision `$F75F` вызывают только звенья с нечётным
scheduler priority и только при нечётном уже увеличенном `$2EB6`; tip `$A1A3`
проверяется каждый pass. Наконечник перед motion выполняет `$F63A`, а после
intro `$F8A7` загружает fire record `ES:$8E10 + 3*6 + difficulty*$60` и
потребляет RNG. При `DS:$2F2D=0` projectile script затем буквально очищается.

После `root+$32=1` active handler сначала завершает текущие Q8 motion/render/
collision действия и только затем ставит `$A107`. Каждое звено независимо
уменьшает собственный parameter из записи `$43AC` (tip — `$0068`), на
ненулевой ветви продолжает background scroll и render. Нулевая ветвь release
type `$17`, один раз потребляет RNG для sound none/`$51…$53` и ставит `$E7BE`.
На следующем pass `$E7BE` acquire type `$01` и проигрывает полный explosion
stream в том же object slot. При штатном убийстве `$2FC4` не установлен,
поэтому сворачивать этот stream до одного кадра было ошибкой.
Реализованы `DobkeratopsRoot`, `DobkeratopsBack`, `DobkeratopsBody`,
`DobkeratopsTentacle`, `DobkeratopsDebrisE700`, `DobkeratopsOrb`,
`DobkeratopsOrbTrail`.

Автопилот создаёт только обычные `InputState`, без телепорта и invincibility;
он уже уничтожает vulnerable body и доводит root до `boss_defeated=True`.
Это пока не объявлено безошибочным прохождением: после введения точных ROM
hitbox остаются фиксируемые столкновения с enemy projectiles/children, над
которыми продолжается работа.

## Stage 1: ROM tilemap generator

| V30 | File offset | Назначение | Python |
|---:|---:|---|---|
| `$E865` | `$EC65` | очистка foreground VRAM `$D000:0200…3FFF` | `M72Tilemaps.__init__` |
| `$E8A0` | `$ECA0` | очистка background VRAM `$D800:0000…3FFF` | `M72Tilemaps.__init__` |
| `$EA51` | `$EE51` | foreground: вычисляет ring destination, пять метаблоков | `_draw_strip(layer=0)` |
| `$EA73` | `$EE73` | background: то же для второго слоя | `_draw_strip(layer=1)` |
| `$EA95` | `$EE95` | читает foreground descriptor `ES:[BX-$39D9]` | `_draw_strip` |
| `$EB02` | `$EF02` | читает background descriptor `ES:[BX-$2971]` | `_draw_strip` |
| `$EB20` | `$EF20` | метаблок без flip | `_draw_strip` |
| `$EB4B` | `$EF4B` | vertical flip, `code XOR $8000` | `_draw_strip` |
| `$EB86` | `$EF86` | horizontal flip, `code XOR $4000` | `_draw_strip` |
| `$EBBB` | `$EFBB` | horizontal+vertical, `code XOR $C000` | `_draw_strip` |

Одна полоса содержит пять вертикальных метаблоков. Метаблок — `8×6` tiles;
вся полоса — `8×30`. Descriptor хранит индекс в младших 14 битах и flip в
старших двух. Данные одного метаблока занимают 144 байта в сегменте `$3000`:
48 записей по три байта (`code word + attribute byte`). V30 намеренно делает
перекрывающийся второй `MOVSW`, поэтому в VRAM сохраняется точное слово
`attribute + low byte следующего code`; Python повторяет это побайтно.

Формулы Stage 1 при начальном source `$0000`:

- foreground descriptor: `ES:[(source - $39D9) & $FFFF]`, первый `$C627`;
- background descriptor: `ES:[(source - $2971) & $FFFF]`, первый `$D68F`;
- metatile bytes: file offset `$30000 + (descriptor & $3FFF) * 144`;
- ring destination: `((destination * 2) + $1020) & $10FF`;
- после полосы: `source += $000A`, `destination += $10`.

Инициализация не использует готовую карту: `$2EE6/$2EEA=$70`, а
`$2EE7/$2EEB=0`; `$02AE/$02CE` подают по одной полосе за кадр до заполнения
кольца. Та же логика затем вызывается при каждом переходе scroll через 64 px.

## R-9: появление и Beam

| V30/data | File offset | Назначение | Python |
|---:|---:|---|---|
| `$1F3D` | `$233D` | обработчик оригинального появления R-9 | `build_launch_frames` |
| `$10C2…$112A` | `$14C2…$152A` | восьмибайтные шаги launch script | `LAUNCH_STEPS` |
| `$1138/$1150/$1168/$26FE` | `+$0400` | таблицы четырёх кадров engine/plasma effect | `LAUNCH_EFFECT_TABLES` |
| `$1BCC` | `$1FCC` | вывод составного sprite descriptor | координаты launch/player sprites |
| `$244A` | `$284A` | выбор кадра Beam orb | `beam_animation_phase` |

Beam orb: `phase = ($2EB6 & $001C) >> 2`; заряд влияет на размер/готовность,
но не останавливает циклическую анимацию при удерживаемом FIRE.

### Beam/Wave: счётчик, мощность, форма и damage

Объект R-9 хранится в `DS:$0020`, поэтому его поле `+$1D` одновременно видно
как `DS:$003D`. При удержании FIRE участок `$2203…$221B` дважды выполняет
`INC byte [BP+$1D]` за VBlank и насыщает значение на `$80`. При отпускании
`$23EA…$242F` классифицирует этот байт и сразу обнуляет его:

| Charge `player+$1D` | Level `player+$19` | Wave power `object+$16` |
|---:|---:|---:|
| `$00…$17` | 0 | Wave не создаётся |
| `$18…$2F` | 1 | 4 |
| `$30…$47` | 2 | 8 |
| `$48…$4F` | 3 | 12 |
| `$50…$67` | 4 | 16 |
| `$68…$80` | 5 | 20 |

Последний столбец читается из `ES:$188C = 0,4,8,12,16,20` в `$3133…$3143`.
Handler Wave `$31D9` выбирает пару sprite descriptors через
`ES:$1898 + ((power-1)&$1C)`; адреса двух фаз:

| Power | phase 0/1 | active sprite codes | native size |
|---:|---:|---|---:|
| 4 | `$18AC/$18BE` | `$11/$12` | 16×16 |
| 8 | `$18D0/$18E2` | `$41/$42` | 32×16 |
| 12 | `$18F4/$1906` | `$46,$4E,$14 / $47,$4F,$15` | 48×16/17 |
| 16 | `$1918/$192A` | `$50,$51,$59 / $52,$53,$5B` | 64×16 |
| 20 | `$193C/$194E` | `$54,$55,$16 / $56,$57,$17` | 80×16 |

Геометрия и проверка terrain вокруг Wave также целиком задаются ROM:

| ES range | Формат | Достижимое использование |
|---:|---|---|
| `$180E…$183D` | 6 × `(left=4,right=5,lower=height,upper=height)`, `height=8,16,32,64,96,128` | не имеет runtime-ссылок; сохранённая альтернативная таблица hitbox |
| `$183E…$1855` | 12 слов числа горизонтальных probes: `5,5,6,6,7,8,9,10,11,12,12,12` | `$3227…$3243` для power 4/8/12/16/20 выбирает только записи 0…4 |
| `$1856…$187D` | 5 × четыре радиуса `(left,right,lower,upper)` | `$3213…$3224` выбирает запись stride 8 после семикадровой launch-задержки и передаёт её `$38F4` |
| `$187E…$188B` | 7 слов, все равны 1 | `$318A…$31D7` использует level 1…5 как начальную длину foreground/background terrain scan; слоты 0 и 6 недостижимы |

Пять активных hitbox-записей `$1856` равны соответственно
`(2,16,8,8)`, `(12,22,8,8)`, `(12,28,8,8)`, `(12,20,8,8)` и
`(12,30,8,8)`. Это именно границы collision object, а не размеры PNG:
`$38F4…$3920` вычитает left/lower и прибавляет right/upper к native anchor.
Для cropped Wave top-left `(232,195)` после перевода native→640×480 это даёт
rect `(242,195,30,30)`, `(225,195,57,30)`, `(225,195,67,30)`,
`(225,195,54,30)` и `(225,195,70,30)` для power 4/8/12/16/20. Python до
2026-08-13 ошибочно применял только первую, минимальную запись ко всем пяти
мощностям; теперь индексируется фактическое `object+$16`.

Все десять вариантов декодируются офлайн инструментом
`Source/Tools/m72_wave_power_assets.py` в `.../Sprites/WavePower`. Для
power 20 RGBA после xBRZ6+Lanczos побайтно совпадает с ранее извлечёнными из
MAME максимальными фазами. В `$F6DA`, когда `$F4AA` сообщает collision, ROM
читает `AH=[SI]`; для Wave `SI=$00F6`, то есть `[SI]` есть именно
`object+$16`. Поэтому damage равен 4/8/12/16/20, а не константе 4.

Wave не удаляется от первого пересечения. В `$F708…$F717` каждый
пересечённый enemy получает текущую мощность `object+$16`, а в байт
`Wave+$17` прибавляется оставшийся до попадания HP этого enemy. После прохода
enemy objects собственный handler Wave в `$328A…$3294` обнуляет аккумулятор
и вычитает его из мощности; только borrow ведёт в terminal `$32AA`. Поэтому
луч пробивает несколько слабых целей, расходуя мощность на их оставшийся HP.
После уменьшения любое значение 1…20 заново группируется выражением
`((power-1)&$1C)` в визуальные/hitbox уровни 1–4, 5–8, 9–12, 13–16 и 17–20.
Прежний Python ошибочно удалял Wave при первом `damage_at` и проверял только
первый пересечённый enemy; это исправлено 2026-08-13.

Orb появляется при `player+$1D >= $0F`: это буквальное сравнение `$2430`.
Beam meter получает тот же charge в `$4FD2`; для `$05…$7B` его внутренняя
часть строится из `(charge-4)>>3` полных восьмипиксельных tiles и отдельного
tile остатка. Для всех реально достижимых even charge `$00,$02…$80` сохранено
65 отдельных состояний `BEAM_METER_C000…C128`: work RAM каждого исходного
кадра подтверждает byte `$003D`, а xBRZ6+Lanczos выполняется только offline.
Python выбирает готовое состояние по `charge/2`; прежняя подмена partial tile
обрезкой полного bitmap удалена.

Тот же переход `$2430…$2444` после успешного acquire resource `$03` посылает
sound command `$32` и меняет handler на `$244A`; повторно `$32` при удержании
FIRE не посылается. Когда charge становится нулём, `$2482…$2494` освобождает
resource, посылает `$33` и возвращает handler `$2430`. Изолированный MAME
capture подтверждает, что `$32` звучит непрерывно до конца даже 10.38-секундной
активной части, а `$33` служит остановкой. Python запускает отдельный looped
BASS channel при пересечении `$0F` и останавливает его при отпускании FIRE.
PCM `RTYPE_SFX_CHARGE_U8_22050.raw` начинается в момент команды, сохраняет
исходную задержку YM2151 0.133896 с и получен offline sinc64-ресемплером из
прямого soundlatch capture без музыки.

### Hit flash после `$F6DA`

Многоударные Stage 1 объекты сравнивают damage counter до/после `$F6DA` и
при изменении ставят `object+$3D`: `$74B4` и `$60BA` — `$0C`, `$80E3` —
`$10`. Helpers `$779E/$661A/$8409` каждый update сначала уменьшают таймер и
выбирают flash resource `object+$3C`, когда `(timer & 3)==0`. Этот автомат и
штатные flash palettes теперь перенесены в Python; исчезновение объекта при
исчерпании HP остаётся прежним путём `take_damage`.

## Stage 1: вращающаяся змея и изменение foreground terrain

Это буквальная вращающаяся змея из 16 звеньев. Тот же автомат объясняет первые
расхождения foreground после MAME frame 4432: это не tilemap scroll и не
подгружаемая полоса — parent змеи сам пишет в foreground VRAM `$D000`,
постепенно строит и затем стирает контур. Узкая PC-трасса на
frame 4462 показала 20 записанных cells; записи выполнялись непосредственно
инструкциями `$6C1C/$6C20`.

| V30 | File offset | Назначение | Статус |
|---:|---:|---|---|
| `$6A9B…$6ACA` | `$06E9B…$06ECA` | создаёт parent вращающейся змеи и задаёт таблицу 16 звеньев | Python exact |
| `$6ACB…$6B4E` | `$06ECB…$06F4E` | создаёт 16 звеньев типа `$13`, затем включает задержку `$40` | Python exact |
| `$6B4F…$6C08` | `$06F4F…$07008` | двигает parent со scroll и раз в 8 VBlank строит/стирает путь | Python exact, включая оба child-armed пути |
| `$6C09…$6C36` | `$07009…$07036` | немедленно рисует весь первый путь `$03E8/$0081` | Python exact |
| `$1E6C…$1EB4` | `$0226C…$022B4` | координаты объекта + scroll → offset foreground VRAM | Python exact |
| `$6C37…$6E9A` | `$07037…$0729A` | полный child, damage/death, связь с terrain paths, projectile `$6E27` | decoded полностью |
| `$1BA7…$1BCB` | `$01FA7…$01FCB` | dispatcher четырёхбайтных stage events | event `$4400` Python exact |
| `ES:$B92D` | `$1B92D` | таблица обработчиков stage event | decoded для event `$4400` |
| `ES:$BB5F` | `$1BB5F` | Stage 1 event: threshold `$0D2C`, command `$4400` | decoded |

Данные child/death после его descriptor sheet разделяются строго по
исполнению:

- `$2FD4…$2FDB` — damage hitbox `(-8,+8,-8,+8)`, который `$6C77/$6C86/$6D2C`
  передают `$F6DA`;
- `$2FDC…$301B` — не адресуемое этой ревизией кольцо 16 пар `(dx,dy)`;
- `$301C…$3041` — 18 signed offset words и terminal `$8000` для смерти
  post-boss объекта `$6F32`. Цикл `$6F4E…$6F79` намеренно читает перекрытые
  окна `(word[i],word[i+1])`, сдвигает указатель на одно слово и завершает
  генерацию по terminal либо при заполненном allocator.
| `ES:$2E46` | `$12E46` | 16 записей spawn-параметров по 8 байт | decoded |
| `ES:$2EC6` | `$12EC6` | цепочки знаковых приращений адреса tilemap | decoded для `$6C09/$6B4F` |

### Точные HEX-процедуры

`$6A9B…$6ACA`:

```text
51 b9 10 80 ba cb 6a e8 01 99 59 72 22 33 c0 89 44 22
89 44 38 89 44 3a 89 44 10 c7 44 04 d8 02 c7 44 08 54
01 c7 44 12 46 2e c7 44 20 10 00 c3
```

`$6ACB…$6B4E`:

```text
b9 21 80 ba 37 6c e8 d2 98 72 6e c7 44 16 00 01 89 6c
30 8b 5e 12 26 8b 07 89 44 04 26 8b 47 02 89 44 08 b8
bc a0 89 44 12 26 8b 47 06 89 44 14 b8 11 00 2b 46 20
89 44 20 03 c0 03 c0 89 44 38 c6 44 1f 00 c6 44 2f 01
83 7c 20 04 75 10 8a 1e 2e 2f 32 ff 03 db 26 8b 87 3e
2e 88 44 2f 26 8b 4f 04 e8 77 8d b0 13 e8 b9 e6 88 5c
06 83 46 12 08 ff 46 22 ff 4e 20 75 87 c7 46 34 40 00
c7 46 00 4f 6b c3
```

`$6B4F…$6C08`:

```text
ff 4e 34 75 03 e8 b2 00 a1 d0 2e 01 46 04 f7 06 b6 2e
07 00 74 03 e9 8e 00 8b 5e 38 23 db 74 40 83 fb 01 75
0b 8b 46 26 89 46 28 c7 46 38 c6 2e 8b 5e 28 8b 76 38
1e b8 00 d0 8e d8 c7 07 e8 03 c7 47 02 81 00 1f 26 8b
04 23 c0 74 0e 02 d8 02 fc 89 5e 28 83 46 38 02 e9 05
00 c7 46 38 00 00 8b 5e 3a 23 db 74 40 83 fb 01 75 0b
8b 46 26 89 46 2a c7 46 3a c6 2e 8b 5e 2a 8b 76 3a 1e
b8 00 d0 8e d8 c7 07 a0 0f c7 47 02 81 00 1f 26 8b 04
23 c0 74 0e 02 d8 02 fc 89 5e 2a 83 46 3a 02 e9 05 00
c7 46 3a 00 00 f7 46 22 ff ff 74 08 f6 06 c4 2f ff 75
01 c3 e8 e4 97 c3
```

`$6C09…$6C36`:

```text
e8 60 b2 81 e3 ff 3f 89 5e 26 1e b8 00 d0 8e d8 be c6
2e c7 07 e8 03 c7 47 02 81 00 26 8b 04 23 c0 74 09 02
d8 02 fc 83 c6 02 eb e7 1f c3
```

`$1BA7…$1BCB`:

```text
be 4b 2f 8b 1e fe 2e 8b 04 26 3b 07 72 16 83 06 fe 2e
04 26 8b 4f 02 8a dd d0 eb 81 e3 7e 00 26 ff 97 2d b9
c3
```

Event-запись и соответствующая ячейка dispatch table:

```text
ES:BB5F  2c 0d 00 44    ; threshold=$0D2C, command=$4400
ES:B94F  9b 6a          ; handler[$11]=$6A9B
```

`$1E6C…$1EB4`:

```text
a1 c1 2e 8b c8 81 e1 07 00 d1 e8 25 fc 00 05 20 10 8b
d8 8b 46 04 03 c1 2d 40 01 d1 e8 25 fc ff 03 d8 81 e3
ff 10 b8 7f 01 2b 46 08 73 02 33 c0 25 f8 ff c1 e0 05
03 d8 81 e3 ff 3f 1e b8 00 d0 8e d8 8b 07 25 ff 0f 1f
c3
```

### Буквальный автомат

`$6A9B` выделяет parent через `$03A6` с `(type=$8010,
handler=$6ACB)`, обнуляет поля `+$10/+$22/+$38/+$3A`, задаёт координаты
`x=$02D8`, `y=$0154`, указатель `ES:$2E46` и счётчик `$10`.

`$1BA7` сравнивает старшее слово progression `RAM:$2F4B` с threshold текущей
event-записи `ES:[RAM:$2EFE]`. Если threshold достигнут, указатель увеличивается
на 4, command загружается в `CX`, а offset dispatch table вычисляется как
`((CH >> 1) & $7E)`. Для Stage 1 event `ES:$BB5F` command `$4400` даёт offset
`$22`, то есть индекс `$11`; `ES:[$B92D+$22]=$6A9B`. Это исходный ROM-триггер
terrain parent. MAME frame 4395 остаётся только контрольным следствием
достижения progression `$0D2C`.

`$6ACB` выделяет 16 children `(type=$8021, handler=$6C37)`. Для каждого
читает из восьмибайтной записи `ES:[parent+$12]` координаты `+0/+2`, параметр
`+6`, ставит sprite descriptor `$A0BC`, вычисляет ordinal и создаёт связанный
ресурс типа `$13` через `$51EE`. После последнего child parent получает
`timer=$0040` и `handler=$6B4F`.

У ordinal 4 есть доказанная особенность времени жизни `BX`. Ветка
`$6B13…$6B26` читает difficulty HP и оставляет `BX=2*difficulty`; поэтому
следующий `$6B29: MOV CX,ES:[BX+4]` читает не `record+$04`, как у остальных
15 children, а `ES:$0004+2*difficulty`. При difficulty 0 это
`ES:$0004=$5E8B`: low byte `$8B` выбирает в `$F8A7` огневую строку 8
`($0040,$0140,$8F90)`. RNG phase на MAME VBlank 4931 равна `$000C`, первая
ракета этого child создаётся ровно на VBlank 6003.

`$6B4F` каждый кадр добавляет foreground delta `RAM:$2ED0` к `parent.x`.
Когда истекает `timer`, вызывает `$6C09`. Далее только при
`RAM:$2EB6 & 7 == 0` выполняет по одному шагу двух независимых путей:

- build path пишет `code=$03E8, attribute=$0081`;
- erase path пишет `code=$0FA0, attribute=$0081`.

Следующий адрес вычисляется не обычным сложением word: ROM отдельно выполняет
`BL += delta.low` и `BH += delta.high`, то есть переноса между байтами нет.
Нулевое слово завершает путь. Начальный tilemap offset хранится в `parent+$26`,
текущие offsets — в `+$28/+$2A`, указатели пути — в `+$38/+$3A`.

`$6C09` получает tilemap offset из `$1E6C`, маскирует его `$3FFF`, сохраняет
в `parent+$26` и немедленно проходит цепочку с `ES:$2EC6`, записывая весь
build path в `$D000`. Подстановка номера MAME-кадра запрещена.

### Полный автомат звена `$6C37…$6E9A`

Граница `$6C37` подтверждена не линейной догадкой: именно это word записывает
parent `$6ACB` как handler каждого из 16 children. Ресурс type `$13` — palette/
sprite-resource child, полученный `$51EE` и освобождаемый `$523E`; это не
неизвестный дополнительный объект.

В `$6ACB` поля child имеют следующий формат:

| Поле | Значение |
|---:|---|
| `+$04,+$08` | `(x,y)` из восьмибайтной записи `ES:$2E46 + 8*n` |
| `+$12` | motion-script `$A0BC` для `$F5C1` |
| `+$14` | word `record+$06`, параметр animation/motion |
| `+$16` | `$0100` |
| `+$20` | ordinal `$01..$10` |
| `+$30` | указатель parent object |
| `+$38` | `4*ordinal`, локальный timer/phase |
| `+$1F` | накопленный damage, сначала 0 |
| `+$2F` | HP/порог 1; для ordinal 4 — difficulty word `ES:$2E3E+2*difficulty` |
| `+$2A,+$2C,+$28,+$26` | `$F8A7`: fire thresholds, velocity table и RNG phase; command берётся из `record+$04`, кроме ordinal 4 с буквальной BX-особенностью `ES:$0004+2*difficulty` |

Каждый VBlank `$6C37` выполняет `$F5C1`, общий fire helper `$6DBA`, добавляет
foreground delta `$2ED0` и рисует запись через `$1BCC`. База ROM display list —
`ES:$2F6E` только у ordinal 4, у остальных `ES:$2F0E`; offset равен
`6*object+$16`. Если parent уже левее R-9, hit-test `$F6DA` использует обычный
порог `+$2F`; иначе процедура временно ставит `$80`, чтобы закрытая сторона
не принимала ранний урон. Попадание в ordinal 4 дополнительно вызывает
`$0303` с `CL=$56`.

Helper `$6D54` связывает крайние children с двумя terrain-путями parent. При
`x>=$0140`, `y` с bit `$0100` и `y<$0144` ordinal `$10` ставит `parent+$38=1`,
а ordinal `$01` — `parent+$3A=1`. Именно эти флаги запускают build/erase paths
в `$6B4F`; связь children с foreground теперь полностью определена.

При достижении damage threshold `$6CCB` создаёт explosion `$E7BE`, получает
resource `$52`, освобождает `$13`, получает `$14` и ставит handler `$6D15`.
Для ordinal 4 также выставляется `parent+$10=1`; его `$6CB1` уменьшает child
timer `+$38`, после чего путь заканчивается. `$6D15` продолжает motion,
scroll/render и hit processing до ухода за X `$00E0` либо global cleanup
`RAM:$2FC4`, затем освобождает `$14` и удаляет object.

`$6DBA` — встроенная стрельба child: когда parent X меньше R-9 X, увеличивается
`+$26`; совпадение с `+$2A` или достижение `+$2C` сбрасывает счётчик и создаёт
`$A000/$6E27`. Пара Q8 velocities берётся из `ES:[+$28 + 4*object+$16]`,
projectile получает resource `$56` и ссылку на parent в `+$36`. `$6E27`
интегрирует X/Y через `$0672/$0689`, выбирает одну из четырёх display-записей
`ES:$2EEE + 3*((object_address>>3 + $2EB6)&$18)/4`, проверяет R-9 `$F485`,
terrain `$1E6C/$1D6B` и диапазон относительно parent; collision вызывает
`$E686`, обычный выход освобождает `$56` и удаляет object.

Таблицы кадров змеи не являются RAM и не строятся на лету:

| ROM range | Точное содержимое |
|---:|---|
| `ES:$2EEE…$2F05` | 4 кадра снаряда `$6E27`, phase от `(object-slot/8+VBlank)&$18` |
| `ES:$2F0E…$2F6D` | 16 углов обычного звена, `6*(object+$16)` |
| `ES:$2F6E…$2FCD` | 16 углов крупного ordinal-4 core, `6*(object+$16)` |
| `ES:$2FCE…$2FD3` | кадр разрушенного звена в resource type `$14` |

MAME no-fire snapshot VBlank 5500 содержит parent `$6B4F` в `DS:$0F40` при
`x=$024A` и все 16 живых `$6C37`. Их sprite codes `$0190…$01A4` и
`$0A94…$0AA0` получаются именно из двух ROM-колец выше. Это одновременно
проверяет идентичность объекта: речь идёт о вращающейся змее, не о
Dobkeratops и не о наборе независимых турелей `$86A6`.

Проверка: на MAME frame 4462 PC `$6C1C/$6C20` записывает 20 foreground cells
с `$03E8/$0081` по адресам от `$D1580` до `$D2880`, что совпадает с этим
алгоритмом и таблицей `ES:$2EC6`. Parent находится в `DS:$1800`: frame 4395
создаёт его, frame 4396 завершает `$6ACB`, а frame 4462 получает
`parent.x=$02B8` после update. MAME snapshot снимается до same-frame VRAM writes;
поэтому итог проверен на frame 4500: весь видимый foreground совпадает с
Python побайтно.

Расширенная no-fire write-trace
`Build/Arcade/MAME/object_pool_stage1_no_fire_writes_14000/object_writes.csv`
проверяет не только initial path. Child ordinal `$10/$01` реально ставят
`parent+$38/+$3A=1`; `$6B4F` затем сначала пишет build-cell `$03E8/$0081`,
после него erase-cell `$0FA0/$0081`, читает очередное слово `ES:$2EC6` и
сдвигает соответствующий pointer на 2. На VBlank 5940 projectile `$6E27`
пробует foreground offset `$1D74`: MAME уже вернул там `$0FA0`, тогда как
старый неполный Python-код оставлял `$03E8` и ошибочно входил в `$E686`.
После переноса обоих путей и особенности ordinal 4 рубеж 6500 дал
**1731/1731 exact allocator lifecycle events**. Та же непрерывная трасса
продлена до VBlank 14000. После точного `$F366/$F3C1`, порядка `$657C`,
mirror `$6788`, Q8 residue `$663E`, deferred `$98FD/$9915`, explosions
`$9BB9`, фазы stop `$F42E`, trail `$9E07/$9EC0`, post-boss R-9 `$2084`,
projectile explosion `$66F4/$E7AE` и переходов
`$F130/$F1BF/$F260/$F34D/$F01B/$F44E` автоматическая сверка даёт
**2936/2936 exact events** от VBlank 852 до 14000. Совпадают каждый
`$03A6/$03EC`, FIFO slot, event pointer `$BC23`, RNG `$05,$01,$03` и
active/skipped main-loop frames `12080/1069`. На frame 14000 уже исполняются
ранние события Stage 2. Это доказанный рубеж no-fire object-pool lifecycle,
не заявление о готовности всего интерактивного Stage 1, render, collision или
SFX.

## Подтверждённые контрольные точки

| Кадр MAME | Foreground VRAM | Background VRAM | Что проверено |
|---:|---:|---:|---|
| 898 | 2048/2048 cells exact | 2048/2048 exact | чистая ROM-инициализация и preload |
| 1000 | 2048/2048 exact | 2048/2048 exact | динамические полосы frames 914/978 |
| 3500 | 1920/1920 exact | 1920/1920 exact | смена скорости `$F0F3` |
| 4500 | 1920/1920 exact | без изменений | event `$4400`, `$6A9B/$6C09`, path `ES:$2EC6` |
| 6500 | 1920/1920 exact | 1920/1920 exact | несколько ring wrap и пропуски IRQ |

Ручная проверка на текущем Python stand: базовый ring-ландшафт визуально
корректен от начала Stage 1 до первого босса. ROM-автомат boss-transition и
все четыре потока очистки foreground отдельно закрыты точной PC-trace,
описанной в разделе Dobkeratops.

Эталон используется только тестом. Runtime `rtype_port.stage` больше не читает
`STAGE1_*_EVENTS.bin` и не воспроизводит MAME-трассу.

## Полный реестр foreground VRAM mutators `$D000`

Полный reached V30 graph содержит также процедуры, которые только читают
foreground (`$1E6C/$2AB4/$31A3/$3263/$4AB5/$4BE4`); они не смешиваются с
mutators ниже. Все пути, реально записывающие в segment `$D000`, сведены в
один реестр. Адреса — адреса инструкций ROM, диапазоны — offsets внутри
сегмента, без пересчёта в экранные координаты.

| Owner/state | Write sites | Точное изменение `$D000` |
|---:|---:|---|
| `$2365` | `$238B…$23A2` | rectangle 2×20 attribute words от `probe_offset+2`, шаг X `+4`, Y `+$100`: `word &= $000F` |
| `$2736` | `$2759/$2776/$2798/$27B5` | четыре соседние Force probe cells: только code `$09F6` заменяется `$0FA0`, attribute становится 0, dirty `$2F30++` на каждую замену |
| `$4FB9` | `$4FBF/$4FC4` | одна cell по BX: `code=$0FA0, attr=0`, затем `$2F30++` |
| `$4FD2…$50C9` | `$4FE5…$50C2` | Beam meter HUD, fixed pairs `$0060…$00A2`: border `$06B2/$06BF`, full `$06BA`, partial code из `ES:$272E`, attr всегда `$008F` |
| `$69B4` | `$6A12/$6A17` | probe cell объекта: только пустой `$0FA0` превращается в solid `$09F6/$0082` |
| `$6ACB/$6C09` | `$6B8B/$6B8F`, `$6BD2/$6BD6`, `$6C1C/$6C20` | Stage 1 path: build `$03E8/$0081`, erase `$0FA0/$0081`; offsets идут по signed-byte-pair streams `ES:$2EC6` и object `$38/$3A`; полный state machine описан в разделе объекта `$4400` |
| `$8D54` | `$8D60…$8D81` | script `object+$30`: records `(packed signed Δoffset word, code word)`, sentinel packed word 0; на каждой cell записать script code и attr `$000A` |
| `$90E0` | `$90FC…$914D` | четыре cells вокруг probe; каждая `$09F6` заменяется `$0FA0/0`, остальные codes не меняются |
| `$9FE9` | `$A003…$A02A` | раз в 2 VBlank записать `$0FA0` в текущий `object+$20`, затем добавить packed `(signed Δlow,signed Δhigh)` word из script `object+$10`; `$8000` завершает и уменьшает parent `+$34` |
| `$A290` | `$A458…$A462`, `$A50B…$A515` | при controller counters `$1760` и death branch одинаково пройти 1152 attribute words `$1C02…$2DFE`, шаг 4, оставить `word&$000F` |
| `$A638` | `$A682…$A69C` | каждые 4 VBlank скопировать rectangle `CL×CH` code words из ROM `$1000:SI` в `$D000:DI`, после каждого code поставить attr `$0088`; X шагает low-byte `+2`, Y `+$100` |
| `$B8D5` | `$B90C…$B916` | при timer `$0300` пройти 128 attributes `$1002…$11FE`, шаг 4, выполнить `word |= $0080` |
| `$BE81` | `$BFDA…$BFE4` | после lethal path пройти 2048 attributes `$1002…$2FFE`, шаг 4, выполнить `word &= $000F` |
| `$C0CA` | `$C11A…$C123` | после Force collision при progression `>=$0BC0`: восемь vertical cells от terrain DI, шаг `$100`, code `$03E8` |
| `$C0CA` transition | `$C1CB…$C1D8` | 2048 iterations от DI `$1002`: mask background word `&$000F`, переключить ES на `$D000`, записать foreground `$0FA0`, DI суммарно `+4` за iteration |
| `$C4BC` | `$C550…$C55A` | terminal gate `object+$3E!=0`: 256 words от `$9D02`, шаг 4, `word&=$000F` |
| `$DDF4` | `$DE92…$DE9C` | lethal path: тот же 256-word range `$9D02`, шаг 4, `word&=$000F` |
| `$E865` | `$E873…$E87F` | stage clear без HUD: 3968 records `$0200…$3FFF`, шаг 4, `code=$0FA0, attr=0` |
| `$E883` | `$E890…$E89C` | полный foreground clear: 4096 records `$0000…$3FFF`, шаг 4, `code=$0FA0, attr=0` |
| `$EA51/$EA95` | `$EB34…$EBE9` | штатная foreground strip loader: 5 metаблоков × 8×6 cells, source `$3000`, destination ring `$1020…$10FF`, четыре exact flip variants `$EB20/$EB4B/$EB86/$EBBB` |
| HUD/text jobs | `$E9D7/$E9E2`, `$EA0E/$EA11`, `$EA34`, `$EC6D/$EC70`, `$ECC4/$ECC7`, `$EDC1/$EDC7`, `$F1EF…$F1FC` | fixed ROM HUD copies, 7-digit score, 8-word labels, lives/Beam fields, generic text rectangle и две code/attr `$0005` cells в `$1774…$177A`; destinations/counts задаются literal job descriptors |

Таким образом gameplay-mutators отделены от strip/HUD writers и от чистых
terrain readers. В reached code нет другого способа установить `DS/ES=$D000`
и выполнить запись: отдельный случай `$C1C3…$C1D8` учтён, хотя segment там
загружается через DX, а не literal `MOV AX,$D000`.

## Полный реестр RNG и VBlank scheduling

`$EDD9` задаёт единственный seed `$2F28:$2F2A = $05,$01,$03`. Один вызов
`$EDE9` выполняет строго:

```text
old = (a,b,c)
AL = (b + c) & $FF
(a,b,c) = (AL, old.a, old.b)
AH = old.c
return AX
```

RNG не имеет собственного периодического IRQ. Каждый step выполняется ровно в
том VBlank, когда object dispatcher `$0259/$0267` дошёл до конкретного owner
handler и его локальные timer/`$2EB6 & mask` guards пропустили ветвь. Поэтому
перенос обязан сохранять allocator order и порядок object slots: перестановка
двух handlers переставляет и RNG sequence.

В полном замкнутом графе находятся ровно 75 инструкций `CALL $EDE9`.
`RTYPE_WORLD_ROM_COMPLETE.md`, раздел `Все runtime вызовы RNG $EDE9`, содержит
все 75 адресов, owner entry и окно из четырёх инструкций до/после каждого call.
До-call окно фиксирует cadence guard (`$2EB6` mask/countdown) либо показывает,
что это однократная инициализация сразу после allocator; after-call окно точно
фиксирует mask/range и destination результата. Генератор сравнивает число и
полный reached call set; добавленный или потерянный caller делает проверку
красной.

## Контракты state-entry, начинающихся opcode `$FF`, и раскрытых ими ветвей

Старый фильтр ошибочно отбрасывал handler, если его первый байт был `$FF`.
Но `$FF` у V30 является нормальным opcode группы `INC/DEC/CALL/JMP`, а не
признаком erased ROM. После замены фильтра на проверку самого значения
handler (`$0000/$FFFF`) fixed-point граф раскрыл следующие entry. Здесь
записан их буквальный контракт; полный набор инструкций и callers находится
в generated `RTYPE_WORLD_ROM_COMPLETE.md/JSON`.

| Entry | Буквальный контракт ROM |
|---:|---|
| `$002D` | продолжение bootstrap после upload: очистить оставшиеся `$8000` bytes sound/shared segment `$E000`, выбрать портом 2 main map, установить `DS=ES=SS=$4000`, очистить work/sprite RAM и вернуть `ES=$1000` |
| `$075F/$085A/$088A` | terminal/title timers: `$075F` по нулю входит в session cleanup `$076C`; `$085A` после двух VBlank запускает sound `$25`, palette jobs и `$088A`; `$088A` создаёт семь presentation objects handlers `$0C88/$0C71`, затем идёт в `$094A` |
| `$094A/$095A/$0973` | завершение start presentation: дождаться timer, поставить game/session latch и cleanup, через четыре VBlank очистить scroll/queues, вызвать palette transition и передать управление `$09F9` |
| `$0A71/$0A7C` | объект с timer `$0240`; по нулю послать sound `$27` и удалить object `$03EC` |
| `$0A8B` | attract controller: до `$0090` VBlank каждые `$40` создаёт `$23C8` visual (надпись GAME OVER: X=`$0200`, Y=`$0118`, `[SI+$10]=$24`); terminal branch меняет handler/timer и presentation latch. Тот же visual с Y=`$0110` при настоящем GAME OVER создают `$2365` (`MOV DX,$23C8` на `$23A8`) и `$EFED`. Порт по решению пользователя 2026-09-14 ставит демо-надписи X=0 (байт `$00EAA`), см. `PROJECT_MEMORY.md` |
| `$0AE7/$0B0C` | service/attract mode sequencer: циклически обновляет `$308C`, затем обнуляет scroll words `$2EC0…$2ECE`, ставит очистку обоих tile layers и следующий timed state |
| `$0B3D/$0B9E` | timed palette/title transitions: `$0B3D` снимает cleanup, создаёт palette/resource и text objects; `$0B9E` после задержки входит в общий terminal `$076C` |
| `$0BAC` | по mode `$308C` выбирает sound shared segment из `ES:$086A`, сбрасывает ring offset `$308A`, вычисляет offset ROM presentation record и создаёт его объекты |
| `$0C71/$0C88` | два cleanup-aware countdown handler: после `object+$02==0` переходят соответственно к `$1992` и `$1951`; при `$2FC4!=0` удаляют object |
| `$0F79` | terminal start/logo composite: пока timer `$50…$30` рисует пары descriptors `$0B3E/$0B4A`; по нулю освобождает resource и продолжает state chain |
| `$11E2` | session reset после `$13A7`: выбирает event pointer `$C5DF`, грузит palette `$8C50`, гасит sound, обнуляет scroll и переинициализирует fixed objects |
| `$124F/$1258` | session/start timers и выбор активного player по `$2F20,$2F32,$2F3A`; переключают handler `$0F03` либо идут в presentation branch |
| `$12E2` | ставит foreground-clear и два text jobs `$0E06/$0E1C`, снимает cleanup, запускает palette `$11`, resource slot 5 и следующий start state |
| `$132A/$136E/$141F` | два input-driven countdown автомата: `$132A` читает port-shadow `$2052`, `$136E` — `$2042`; общий `$141F` выбирает sound из `ES:$0DE0`, text descriptor из `ES:$0DDE`, перезаряжает timer `$003E` и уменьшает phase на 2 |
| `$14F9/$1515` | очистка слоёв и восьмикадровая задержка; затем sound `$28`, spawn `$FAD7`, palette/resource jobs и продолжение presentation |
| `$160F` | после countdown создаёт два sprite/text objects `$1951` и `$1A51`, назначает им descriptors/координаты; failure идёт в общий cleanup |
| `$1655/$1660` | timed character/tile animation: `$1660` читает phase bytes `ES:$0B5C`, pointer `ES:$0B7E`, строит foreground cells в `$D000`, меняет phase/timer до terminal branch |
| `$17D7/$17FB/$1817/$1878` | конец presentation: input-or-timer gate, sound `$29`, очистка обоих слоёв, затем palette/resources; `$1878` ждёт input shadow либо timer и возвращается в общий `$12A7` |
| `$188E/$18EB` | интерпретатор text/tile records: `$188E` каждые `object+$20` VBlank копирует 8-byte ROM command в `object+$30`; `$18EB` пишет последовательность tile code/attribute `$0006` в foreground VRAM и сохраняет обновлённые source/destination pointers |
| `$1951/$1992/$19D3` | два варианта инициализации text stream из `object+$08`: header `(destination,attribute,count)`; `$1951` берёт source сразу после header, `$1992` — из `object+$16`; общий `$19D3` пишет один code/attribute, двигает указатели и завершает запись по счётчику |
| `$1A51/$1AA1/$1B3E` | `$1A51` — ещё один header+inline-source text handler; `$1AA1` вычисляет параметры строки через `ES:$0BA2`; `$1B3E` после countdown копирует прямоугольник из ROM в foreground VRAM, учитывая `$0120` line bias и cleanup latch |
| `$8E15/$8EA9/$8ECC/$8EFA` | полный автомат enemy `$8E15`: countdown, Q8 X/Y `$0672/$0689`, phase descriptor, renderer; `$8EA9` временно подменяет palette при hit-flash; `$8ECC` задаёт вертикальный заход; `$8EFA` через RNG выбирает следующий ROM motion/descriptor record |
| `$A107` | terminal child boss-controller: следует background scroll и рисует `object+$20`; по timer освобождает resource, RNG выбирает sound `$50…$53`, затем объект удаляется |
| `$A2B0/$A334/$A375/$A3B3/$A578` | три state boss-terrain transition: probe фиксированной точки `(01EC,010C)`, выбор ROM strip pointer из `ES:$51CA/$51DA`; общий `$A578` копирует четыре строки по 12 code words из World ROM в foreground VRAM, ставя attribute `$0088` |
| `$A523` | transition countdown: на `$0100/$0080` посылает sounds `$1A/$1C`, переключает scroll/palette flags; по нулю возвращается в `$A473` |
| `$B1AC` | boss/stage terminal countdown: на `$0080` sounds `$1A/$1C` и latch `$2FC1`; по нулю задаёт scroll `$2EEC=$0080`, выполняет palette/job transition |
| `$C238/$C275` | два terminal timer state: `$C238` сбрасывает palette slots 1–3 через `$54E4`; `$C275` по нулю sound `$2B` и delete `$03EC` |
| `$C5E8` | stage-complete delay: по нулю вызывает `$F01B` со stage 7 и удаляет controller |
| `$D608/$D697` | parent-linked late enemy: damage hitbox `$7E46=(-12,+12,-10,+10)`; death/parent termination переводит в `$D71D` |
| `$D807/$D892` | его child projectile: Q8 velocity, render/terrain и player hitbox `$7E4E=(-8,+8,-8,+8)`; terminal animation выбирается знаком Y velocity |
| `$D90E` | progression-driven phase state: последовательно читает 16 записей `$7E56` `(parent threshold, descriptor-table offset|spawn bit $8000)`, при установленном bit создаёт `$DAC8`; запись `($FFFF,4)` завершает timeline |
| `$E71C/$E75C` | scrolling explosion/visual: timer вызывает `$E75C`, основной state следует background delta, берёт descriptor pointer из `(duration,pointer)` stream; `$E75C` вычисляет background VRAM cell, стирает/заменяет terrain и сохраняет адрес в `object+$20` |
| `$EF1E` | каждые `$40` VBlank читает следующий word job из ROM stream `object+$10`, вызывает `$ED93`; нулевой word завершает stream и переводит state |
| `$EF83/$EF97` | два последовательных timer: первый вызывает collision-table job `$5596`; второй ставит foreground clear `$E883`, scroll `$2EEC=$0080` и удаляет object |
| `$EFB8` | после `$0120` VBlank обнуляет оба scroll position/velocity, выбирает player-dependent state по `$2F20/$2F32/$2F42` и продолжает stage transition |
| `$F012` | terminal stage-transition marker: ставит `$2FC2=$FF` и удаляет object |
| `$FAD7/$FAE1` | `$FAD7` создаёт controller `$0200/$FAE1`; `$FAE1` раз в 8 VBlank использует RNG, при разрешённой маске строит command `CH=$6C, CL=RNG&$0F` и вызывает stage-event dispatch table `ES:$B92D`, при cleanup удаляется |

## Полное доказательство sprite descriptor consumers — 2026-08-12

Статический producer-aware проход теперь разрешает все **241/241** вызовов
renderer `$1BCC/$1BE9/$1C1B/$1CA6`. Получено **2436** точных рёбер
`descriptor → renderer call` и **647** sprite codes с реально достигнутыми
потребителями. Для остальных codes отсутствие consumer list означает
неиспользование достигнутым игровым графом, а не потерянный адрес.

Проход не сканирует ROM по внешнему виду шестибайтной записи. Адрес становится
descriptor только после доказанной цепочки producer → `BX` → renderer и
проверки полей `(signed dx, signed dy, code<4096, attribute low byte=0)`.
Закрыты literal domains, object fields, таблицы указателей, direction table
`$1D89`, flash wrappers с сохранением `BX`, zero-terminated streams,
duration/pointer streams и cumulative-time streams. В частности, явно
разобраны поздние таблицы `$7A94`, `$7B4E…$7BCE`, `$7C30…$7CD0`, `$7E56`,
`$7ED2`, `$8006…$804E`, `$81FA`, `$8258/$8278`, `$83AC`, `$9384`, `$945C`
и матрица `$3FC6`. Полные адреса, коды, атрибуты и sites находятся в
`Build/Analysis/rtype_world_rom_complete.json` →
`graphics.sprite_consumers.descriptor_consumer_edges`.

## Очередь дальнейшей расшифровки

Очередь scripts/stages закрыта полным fixed-point runtime graph: все восемь
event streams содержат 788 записей, все 48 dispatch handlers именованы, а
каждый из 825 достигнутых procedure/state entry имеет semantic context.
Оставшиеся строгие проверки пространств данных перечисляются генератором
отдельно и не скрываются в этом разделе.

## Дополнение 2026-08-12: service/reset data и task ring

Полный fixed-point проход по service-state word `$3090` дал состояния
`$0000,$02FD,$0323,$038D,$039F,$03DD,$03FA,$0445,$0465,$049B,$0500,$053C`:
634 instructions и 1597 code bytes сегмента `$3900`. Его непрерывные World
данные `$EB07…$EF54` теперь разложены на 16 проверяемых форматов — dispatch,
строки, 65 sound records и sentinel, menu/I/O/DIP/input patterns, DS-copy,
cross-hatch и raw-sprite diagnostics.

Reset consumers `$3F00:$0B6A/$0C15` доказывают единый блок `$0400…$0819`:
lives/options, coinage records, фиксированные ASCII labels и десять initial
high-score/name records. Runtime `$ED3A/$ED58` читает скопированные labels.

Полный union вызовов allocator `$0384` создаёт 16 task-ring callbacks:
`$E865,$E883,$E8A0,$E8BD,$EA1F,$EA39,$EA41,$EA49,$EA51,$EA73,$EBF1,$EC14,$EC7B,
$ED3A,$ED58,$ED93`. Исправление 2026-09-14: `$EA1F` приходит не через `MOV CX,imm`,
а через `MOV DX,$EA1F` (`$1156`) и `MOV CX,DX` (`$1175`) при DSW bit 9 (`$2F2B`, маска
`$0200`) и bit 4 счётчика `$2EB6`; вызов `$1177` тогда чередует `$EA1F` с `$EA39` каждые
16 кадров. Оба callback копируют 8 слов из `ES=$1000` (`$8744` или `$8734`) в VRAM
`$D000:$012C` через `$EA25` — мигающая надпись. Прежний список из 15 callbacks был неполным;
трасса эталона исполняет `$EA1F`. Вместе с входами IRQ из таблицы векторов ROM
(`$00FA`, `$00FC`, `$00FE`, `$02EE`) актуальный runtime graph содержит 21 920
instructions и 830 entries; прежние значения 21 911/825, 21 825/821 и 15 или 11 task
callbacks были неполными. Сгенерированная побайтовая карта сейчас строго доказывает
37 051/65 536 World bytes и оставляет 28 485 bytes в явных unresolved-runs.

## Строгое закрытие полного World ES — 2026-08-13

Полный генератор теперь доказательно классифицирует все `65536/65536` байт
`ES:$0000…$FFFF`. У каждого явного data range есть точный формат записи и
полный список машинных consumers; отсутствие consumer записано только для
проверенных dormant/orphan/erased блоков. В машинный контракт отдельно входят
50-word stage dispatcher `$B92D…$B990`, 788 четырёхбайтных событий восьми
уровней `$B993…$C5E2`, foreground/background metatile descriptors
`$C627…$EB06` и erased tail `$EF55…$FFFF`.

Воспроизводимый результат:

```text
ROM files: 20/20
runtime instructions: 21920
runtime function entries: 830
unclassified main bytes: 0
semantic unresolved items: 0
AUTOCHECK OK
```

(Числа актуализированы 2026-09-14: входы IRQ `$00FA/$00FC/$00FE/$02EE` из таблицы векторов
ROM и task callback `$EA1F`.)

Команда проверки:

```powershell
$env:PYTHONPATH='Build\PythonDeps;Source\Tools;Source\Python'
python Source/Tools/m72_rom_complete_map.py --check
```

Полная таблица диапазонов, форматов и consumers генерируется в
`Docs/RTYPE_WORLD_ROM_COMPLETE.md`; JSON-представление —
`Build/Analysis/rtype_world_rom_complete.json`.

## Общий ROM-конвертер ландшафта восьми stages — 2026-08-13

`Source/Tools/m72_all_stage_terrain.py` использует checkpoint table
`$87FA…$88E7`, оба descriptor streams `$C627…$EB06` и metatile bank
`$30000…$38FFF`. Он буквально повторяет `$EA95/$EB02` и четыре flip-ветки:
пять descriptors дают пять блоков 8×6, то есть одну готовую полосу 8×30.

Все source bytes разделены между уровнями без дыр и перекрытий:

| Stage | FG strips | BG strips | Event records |
|---:|---:|---:|---:|
| 1 | 66 | 84 | 161 |
| 2 | 48 | 48 | 43 |
| 3 | 48 | 48 | 15 |
| 4 | 48 | 96 | 140 |
| 5 | 48 | 48 | 79 |
| 6 | 48 | 96 | 123 |
| 7 | 48 | 36 | 177 |
| 8 | 66 | 68 | 50 |

Итого: 420 foreground, 524 background, 788 событий. Generated manifest и
SHA-256 лежат в `Assets/Converted/Arcade/AllStages/Terrain`. Общий Python
runtime `rtype_port.world_terrain.M72WorldTerrain` выполняет checkpoint init,
семь preload-полос, Q8 X-scroll, ring crossing/pump и ROM event pointer.
Обработчики `$F0F3`, `$F429`, `$F130` и `$F01B` исполняются по дизассемблеру;
неперенесённые object-specific handlers остаются исходными event records, а не
заменяются вымышленным поведением.
