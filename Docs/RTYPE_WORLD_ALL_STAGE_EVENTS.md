# R-Type World — event streams всех 8 stages

Сгенерировано `Source/Tools/m72_stage_event_map.py` напрямую из World ROM.
Запись имеет вид `threshold word, command word`. Процедура `$1BA7`
сравнивает threshold с `RAM:$2F4B`, затем вычисляет offset обработчика
как `((CH >> 1) & $7E)` в таблице `ES:$B92D`.

MAME frames в таблице отсутствуют намеренно: trigger — progression ROM,
а не номер кадра.

| ES | File | HEX | Threshold | Command | Opcode | Handler | Смысл |
|---:|---:|---|---:|---:|---:|---:|---|

## Stage 1: `ES:$B993..$BC13`

| `$B993` | `$1B993` | `00 06 00 00` | `$0600` | `$0000` | `$00` | `$F0F3` | stage speed/config |
| `$B997` | `$1B997` | `04 06 00 84` | `$0604` | `$8400` | `$21` | `$E430` | stage resource owner |
| `$B99B` | `$1B99B` | `04 06 04 80` | `$0604` | `$8004` | `$20` | `$FB9C` | stage resource/control event |
| `$B99F` | `$1B99F` | `04 06 05 80` | `$0604` | `$8005` | `$20` | `$FB9C` | stage resource/control event |
| `$B9A3` | `$1B9A3` | `04 06 06 80` | `$0604` | `$8006` | `$20` | `$FB9C` | stage resource/control event |
| `$B9A7` | `$1B9A7` | `04 06 07 80` | `$0604` | `$8007` | `$20` | `$FB9C` | stage resource/control event |
| `$B9AB` | `$1B9AB` | `04 06 08 80` | `$0604` | `$8008` | `$20` | `$FB9C` | stage resource/control event |
| `$B9AF` | `$1B9AF` | `04 06 09 80` | `$0604` | `$8009` | `$20` | `$FB9C` | stage resource/control event |
| `$B9B3` | `$1B9B3` | `c0 06 01 00` | `$06C0` | `$0001` | `$00` | `$F0F3` | stage speed/config |
| `$B9B7` | `$1B9B7` | `c0 06 00 04` | `$06C0` | `$0400` | `$01` | `$F461` | stage control |
| `$B9BB` | `$1B9BB` | `c6 06 02 84` | `$06C6` | `$8402` | `$21` | `$E430` | stage resource owner |
| `$B9BF` | `$1B9BF` | `c6 06 0a 80` | `$06C6` | `$800A` | `$20` | `$FB9C` | stage resource/control event |
| `$B9C3` | `$1B9C3` | `c6 06 0b 80` | `$06C6` | `$800B` | `$20` | `$FB9C` | stage resource/control event |
| `$B9C7` | `$1B9C7` | `c6 06 0c 80` | `$06C6` | `$800C` | `$20` | `$FB9C` | stage resource/control event |
| `$B9CB` | `$1B9CB` | `c6 06 0d 80` | `$06C6` | `$800D` | `$20` | `$FB9C` | stage resource/control event |
| `$B9CF` | `$1B9CF` | `c6 06 0e 80` | `$06C6` | `$800E` | `$20` | `$FB9C` | stage resource/control event |
| `$B9D3` | `$1B9D3` | `c6 06 0f 80` | `$06C6` | `$800F` | `$20` | `$FB9C` | stage resource/control event |
| `$B9D7` | `$1B9D7` | `fc 06 04 6c` | `$06FC` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$B9DB` | `$1B9DB` | `03 07 03 6c` | `$0703` | `$6C03` | `$1B` | `$596D` | red scripted flyer |
| `$B9DF` | `$1B9DF` | `0d 07 05 6c` | `$070D` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$B9E3` | `$1B9E3` | `15 07 13 6c` | `$0715` | `$6C13` | `$1B` | `$596D` | red scripted flyer |
| `$B9E7` | `$1B9E7` | `2f 07 0a 6c` | `$072F` | `$6C0A` | `$1B` | `$596D` | red scripted flyer |
| `$B9EB` | `$1B9EB` | `38 07 0b 6c` | `$0738` | `$6C0B` | `$1B` | `$596D` | red scripted flyer |
| `$B9EF` | `$1B9EF` | `3f 07 2a 6c` | `$073F` | `$6C2A` | `$1B` | `$596D` | red scripted flyer |
| `$B9F3` | `$1B9F3` | `48 07 09 6c` | `$0748` | `$6C09` | `$1B` | `$596D` | red scripted flyer |
| `$B9F7` | `$1B9F7` | `5b 07 46 31` | `$075B` | `$3146` | `$0C` | `$5DC8` | patrol formation parent |
| `$B9FB` | `$1B9FB` | `76 07 88 14` | `$0776` | `$1488` | `$05` | `$5A02` | ground walker |
| `$B9FF` | `$1B9FF` | `a0 07 37 31` | `$07A0` | `$3137` | `$0C` | `$5DC8` | patrol formation parent |
| `$BA03` | `$1BA03` | `ee 07 0a 6c` | `$07EE` | `$6C0A` | `$1B` | `$596D` | red scripted flyer |
| `$BA07` | `$1BA07` | `f3 07 09 6c` | `$07F3` | `$6C09` | `$1B` | `$596D` | red scripted flyer |
| `$BA0B` | `$1BA0B` | `fa 07 0a 6c` | `$07FA` | `$6C0A` | `$1B` | `$596D` | red scripted flyer |
| `$BA0F` | `$1BA0F` | `20 08 07 6c` | `$0820` | `$6C07` | `$1B` | `$596D` | red scripted flyer |
| `$BA13` | `$1BA13` | `24 08 85 6c` | `$0824` | `$6C85` | `$1B` | `$596D` | red scripted flyer |
| `$BA17` | `$1BA17` | `2a 08 02 6c` | `$082A` | `$6C02` | `$1B` | `$596D` | red scripted flyer |
| `$BA1B` | `$1BA1B` | `2f 08 03 6c` | `$082F` | `$6C03` | `$1B` | `$596D` | red scripted flyer |
| `$BA1F` | `$1BA1F` | `36 08 08 6c` | `$0836` | `$6C08` | `$1B` | `$596D` | red scripted flyer |
| `$BA23` | `$1BA23` | `3b 08 84 6c` | `$083B` | `$6C84` | `$1B` | `$596D` | red scripted flyer |
| `$BA27` | `$1BA27` | `3e 08 05 6c` | `$083E` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BA2B` | `$1BA2B` | `4b 08 07 6c` | `$084B` | `$6C07` | `$1B` | `$596D` | red scripted flyer |
| `$BA2F` | `$1BA2F` | `52 08 83 6c` | `$0852` | `$6C83` | `$1B` | `$596D` | red scripted flyer |
| `$BA33` | `$1BA33` | `59 08 04 6c` | `$0859` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$BA37` | `$1BA37` | `62 08 08 6c` | `$0862` | `$6C08` | `$1B` | `$596D` | red scripted flyer |
| `$BA3B` | `$1BA3B` | `69 08 05 6c` | `$0869` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BA3F` | `$1BA3F` | `7d 08 04 6c` | `$087D` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$BA43` | `$1BA43` | `8a 08 06 6c` | `$088A` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$BA47` | `$1BA47` | `8e 08 82 6c` | `$088E` | `$6C82` | `$1B` | `$596D` | red scripted flyer |
| `$BA4B` | `$1BA4B` | `a4 08 27 6c` | `$08A4` | `$6C27` | `$1B` | `$596D` | red scripted flyer |
| `$BA4F` | `$1BA4F` | `bd 08 09 6c` | `$08BD` | `$6C09` | `$1B` | `$596D` | red scripted flyer |
| `$BA53` | `$1BA53` | `c4 08 06 10` | `$08C4` | `$1006` | `$04` | `$55E9` | terrain-bound enemy |
| `$BA57` | `$1BA57` | `c4 08 07 6c` | `$08C4` | `$6C07` | `$1B` | `$596D` | red scripted flyer |
| `$BA5B` | `$1BA5B` | `e3 08 06 6c` | `$08E3` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$BA5F` | `$1BA5F` | `06 09 88 14` | `$0906` | `$1488` | `$05` | `$5A02` | ground walker |
| `$BA63` | `$1BA63` | `16 09 04 6c` | `$0916` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$BA67` | `$1BA67` | `1f 09 0a 6c` | `$091F` | `$6C0A` | `$1B` | `$596D` | red scripted flyer |
| `$BA6B` | `$1BA6B` | `4c 09 04 6c` | `$094C` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$BA6F` | `$1BA6F` | `56 09 05 6c` | `$0956` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BA73` | `$1BA73` | `56 09 03 60` | `$0956` | `$6003` | `$18` | `$5526` | collision/terrain table control |
| `$BA77` | `$1BA77` | `56 09 04 60` | `$0956` | `$6004` | `$18` | `$5526` | collision/terrain table control |
| `$BA7B` | `$1BA7B` | `56 09 05 60` | `$0956` | `$6005` | `$18` | `$5526` | collision/terrain table control |
| `$BA7F` | `$1BA7F` | `56 09 06 60` | `$0956` | `$6006` | `$18` | `$5526` | collision/terrain table control |
| `$BA83` | `$1BA83` | `56 09 07 60` | `$0956` | `$6007` | `$18` | `$5526` | collision/terrain table control |
| `$BA87` | `$1BA87` | `56 09 08 60` | `$0956` | `$6008` | `$18` | `$5526` | collision/terrain table control |
| `$BA8B` | `$1BA8B` | `60 09 08 14` | `$0960` | `$1408` | `$05` | `$5A02` | ground walker |
| `$BA8F` | `$1BA8F` | `7e 09 05 94` | `$097E` | `$9405` | `$25` | `$80E3` | player-targeting enemy |
| `$BA93` | `$1BA93` | `92 09 08 14` | `$0992` | `$1408` | `$05` | `$5A02` | ground walker |
| `$BA97` | `$1BA97` | `e2 09 08 54` | `$09E2` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BA9B` | `$1BA9B` | `e8 09 08 14` | `$09E8` | `$1408` | `$05` | `$5A02` | ground walker |
| `$BA9F` | `$1BA9F` | `07 0a 0c 15` | `$0A07` | `$150C` | `$05` | `$5A02` | ground walker |
| `$BAA3` | `$1BAA3` | `36 0a 17 14` | `$0A36` | `$1417` | `$05` | `$5A02` | ground walker |
| `$BAA7` | `$1BAA7` | `46 0a 34 31` | `$0A46` | `$3134` | `$0C` | `$5DC8` | patrol formation parent |
| `$BAAB` | `$1BAAB` | `80 0a 02 00` | `$0A80` | `$0002` | `$00` | `$F0F3` | stage speed/config |
| `$BAAF` | `$1BAAF` | `a6 0a 36 30` | `$0AA6` | `$3036` | `$0C` | `$5DC8` | patrol formation parent |
| `$BAB3` | `$1BAB3` | `c6 0a 1c 15` | `$0AC6` | `$151C` | `$05` | `$5A02` | ground walker |
| `$BAB7` | `$1BAB7` | `c6 0a 12 14` | `$0AC6` | `$1412` | `$05` | `$5A02` | ground walker |
| `$BABB` | `$1BABB` | `09 0b 06 18` | `$0B09` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BABF` | `$1BABF` | `22 0b 24 18` | `$0B22` | `$1824` | `$06` | `$897E` | terrain-aware enemy |
| `$BAC3` | `$1BAC3` | `49 0b 07 18` | `$0B49` | `$1807` | `$06` | `$897E` | terrain-aware enemy |
| `$BAC7` | `$1BAC7` | `52 0b 03 18` | `$0B52` | `$1803` | `$06` | `$897E` | terrain-aware enemy |
| `$BACB` | `$1BACB` | `5a 0b 05 18` | `$0B5A` | `$1805` | `$06` | `$897E` | terrain-aware enemy |
| `$BACF` | `$1BACF` | `66 0b 06 18` | `$0B66` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BAD3` | `$1BAD3` | `72 0b 03 18` | `$0B72` | `$1803` | `$06` | `$897E` | terrain-aware enemy |
| `$BAD7` | `$1BAD7` | `7f 0b 06 18` | `$0B7F` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BADB` | `$1BADB` | `84 0b 05 18` | `$0B84` | `$1805` | `$06` | `$897E` | terrain-aware enemy |
| `$BADF` | `$1BADF` | `84 0b 07 18` | `$0B84` | `$1807` | `$06` | `$897E` | terrain-aware enemy |
| `$BAE3` | `$1BAE3` | `8e 0b 13 18` | `$0B8E` | `$1813` | `$06` | `$897E` | terrain-aware enemy |
| `$BAE7` | `$1BAE7` | `93 0b 04 18` | `$0B93` | `$1804` | `$06` | `$897E` | terrain-aware enemy |
| `$BAEB` | `$1BAEB` | `9d 0b 07 18` | `$0B9D` | `$1807` | `$06` | `$897E` | terrain-aware enemy |
| `$BAEF` | `$1BAEF` | `ac 0b 05 18` | `$0BAC` | `$1805` | `$06` | `$897E` | terrain-aware enemy |
| `$BAF3` | `$1BAF3` | `b6 0b 03 18` | `$0BB6` | `$1803` | `$06` | `$897E` | terrain-aware enemy |
| `$BAF7` | `$1BAF7` | `c0 0b 06 18` | `$0BC0` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BAFB` | `$1BAFB` | `c8 0b 11 28` | `$0BC8` | `$2811` | `$0A` | `$86A6` | animated enemy |
| `$BAFF` | `$1BAFF` | `c8 0b 04 28` | `$0BC8` | `$2804` | `$0A` | `$86A6` | animated enemy |
| `$BB03` | `$1BB03` | `c9 0b 03 18` | `$0BC9` | `$1803` | `$06` | `$897E` | terrain-aware enemy |
| `$BB07` | `$1BB07` | `cf 0b 06 18` | `$0BCF` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BB0B` | `$1BB0B` | `dc 0b 03 18` | `$0BDC` | `$1803` | `$06` | `$897E` | terrain-aware enemy |
| `$BB0F` | `$1BB0F` | `e8 0b 01 28` | `$0BE8` | `$2801` | `$0A` | `$86A6` | animated enemy |
| `$BB13` | `$1BB13` | `e8 0b 04 28` | `$0BE8` | `$2804` | `$0A` | `$86A6` | animated enemy |
| `$BB17` | `$1BB17` | `ef 0b 16 18` | `$0BEF` | `$1816` | `$06` | `$897E` | terrain-aware enemy |
| `$BB1B` | `$1BB1B` | `f2 0b 07 14` | `$0BF2` | `$1407` | `$05` | `$5A02` | ground walker |
| `$BB1F` | `$1BB1F` | `fe 0b 03 18` | `$0BFE` | `$1803` | `$06` | `$897E` | terrain-aware enemy |
| `$BB23` | `$1BB23` | `06 0c 06 18` | `$0C06` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BB27` | `$1BB27` | `08 0c 12 28` | `$0C08` | `$2812` | `$0A` | `$86A6` | animated enemy |
| `$BB2B` | `$1BB2B` | `08 0c 03 28` | `$0C08` | `$2803` | `$0A` | `$86A6` | animated enemy |
| `$BB2F` | `$1BB2F` | `28 0c 02 28` | `$0C28` | `$2802` | `$0A` | `$86A6` | animated enemy |
| `$BB33` | `$1BB33` | `28 0c 03 28` | `$0C28` | `$2803` | `$0A` | `$86A6` | animated enemy |
| `$BB37` | `$1BB37` | `2e 0c 24 18` | `$0C2E` | `$1824` | `$06` | `$897E` | terrain-aware enemy |
| `$BB3B` | `$1BB3B` | `2f 0c 17 14` | `$0C2F` | `$1417` | `$05` | `$5A02` | ground walker |
| `$BB3F` | `$1BB3F` | `40 0c 00 60` | `$0C40` | `$6000` | `$18` | `$5526` | collision/terrain table control |
| `$BB43` | `$1BB43` | `7c 0c 27 18` | `$0C7C` | `$1827` | `$06` | `$897E` | terrain-aware enemy |
| `$BB47` | `$1BB47` | `7e 0c 08 54` | `$0C7E` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BB4B` | `$1BB4B` | `c4 0c 35 10` | `$0CC4` | `$1035` | `$04` | `$55E9` | terrain-bound enemy |
| `$BB4F` | `$1BB4F` | `08 0d 00 28` | `$0D08` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BB53` | `$1BB53` | `16 0d 04 10` | `$0D16` | `$1004` | `$04` | `$55E9` | terrain-bound enemy |
| `$BB57` | `$1BB57` | `28 0d 22 31` | `$0D28` | `$3122` | `$0C` | `$5DC8` | patrol formation parent |
| `$BB5B` | `$1BB5B` | `28 0d 00 28` | `$0D28` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BB5F` | `$1BB5F` | `2c 0d 00 44` | `$0D2C` | `$4400` | `$11` | `$6A9B` | foreground terrain parent |
| `$BB63` | `$1BB63` | `40 0d 00 80` | `$0D40` | `$8000` | `$20` | `$FB9C` | stage resource/control event |
| `$BB67` | `$1BB67` | `88 0e 01 28` | `$0E88` | `$2801` | `$0A` | `$86A6` | animated enemy |
| `$BB6B` | `$1BB6B` | `a8 0e 01 28` | `$0EA8` | `$2801` | `$0A` | `$86A6` | animated enemy |
| `$BB6F` | `$1BB6F` | `ae 0e 27 14` | `$0EAE` | `$1427` | `$05` | `$5A02` | ground walker |
| `$BB73` | `$1BB73` | `c8 0e 10 28` | `$0EC8` | `$2810` | `$0A` | `$86A6` | animated enemy |
| `$BB77` | `$1BB77` | `e8 0e 00 28` | `$0EE8` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BB7B` | `$1BB7B` | `ed 0e 2a 6c` | `$0EED` | `$6C2A` | `$1B` | `$596D` | red scripted flyer |
| `$BB7F` | `$1BB7F` | `f6 0e 29 6c` | `$0EF6` | `$6C29` | `$1B` | `$596D` | red scripted flyer |
| `$BB83` | `$1BB83` | `05 0f 3a 6c` | `$0F05` | `$6C3A` | `$1B` | `$596D` | red scripted flyer |
| `$BB87` | `$1BB87` | `08 0f 10 28` | `$0F08` | `$2810` | `$0A` | `$86A6` | animated enemy |
| `$BB8B` | `$1BB8B` | `28 0f 30 28` | `$0F28` | `$2830` | `$0A` | `$86A6` | animated enemy |
| `$BB8F` | `$1BB8F` | `29 0f 08 54` | `$0F29` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BB93` | `$1BB93` | `30 0f 24 6c` | `$0F30` | `$6C24` | `$1B` | `$596D` | red scripted flyer |
| `$BB97` | `$1BB97` | `41 0f 57 10` | `$0F41` | `$1057` | `$04` | `$55E9` | terrain-bound enemy |
| `$BB9B` | `$1BB9B` | `48 0f 00 28` | `$0F48` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BB9F` | `$1BB9F` | `62 0f 08 6c` | `$0F62` | `$6C08` | `$1B` | `$596D` | red scripted flyer |
| `$BBA3` | `$1BBA3` | `68 0f 20 28` | `$0F68` | `$2820` | `$0A` | `$86A6` | animated enemy |
| `$BBA7` | `$1BBA7` | `8f 0f 47 10` | `$0F8F` | `$1047` | `$04` | `$55E9` | terrain-bound enemy |
| `$BBAB` | `$1BBAB` | `c0 0f 03 00` | `$0FC0` | `$0003` | `$00` | `$F0F3` | stage speed/config |
| `$BBAF` | `$1BBAF` | `c8 0f 02 28` | `$0FC8` | `$2802` | `$0A` | `$86A6` | animated enemy |
| `$BBB3` | `$1BBB3` | `c8 0f 03 28` | `$0FC8` | `$2803` | `$0A` | `$86A6` | animated enemy |
| `$BBB7` | `$1BBB7` | `cf 0f 16 14` | `$0FCF` | `$1416` | `$05` | `$5A02` | ground walker |
| `$BBBB` | `$1BBBB` | `e0 0f 01 80` | `$0FE0` | `$8001` | `$20` | `$FB9C` | stage resource/control event |
| `$BBBF` | `$1BBBF` | `e4 0f 22 32` | `$0FE4` | `$3222` | `$0C` | `$5DC8` | patrol formation parent |
| `$BBC3` | `$1BBC3` | `e8 0f 02 28` | `$0FE8` | `$2802` | `$0A` | `$86A6` | animated enemy |
| `$BBC7` | `$1BBC7` | `e8 0f 13 28` | `$0FE8` | `$2813` | `$0A` | `$86A6` | animated enemy |
| `$BBCB` | `$1BBCB` | `0b 10 32 14` | `$100B` | `$1432` | `$05` | `$5A02` | ground walker |
| `$BBCF` | `$1BBCF` | `5c 10 75 10` | `$105C` | `$1075` | `$04` | `$55E9` | terrain-bound enemy |
| `$BBD3` | `$1BBD3` | `08 11 00 28` | `$1108` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BBD7` | `$1BBD7` | `28 11 00 28` | `$1128` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BBDB` | `$1BBDB` | `48 11 20 28` | `$1148` | `$2820` | `$0A` | `$86A6` | animated enemy |
| `$BBDF` | `$1BBDF` | `68 11 00 28` | `$1168` | `$2800` | `$0A` | `$86A6` | animated enemy |
| `$BBE3` | `$1BBE3` | `6a 11 07 2c` | `$116A` | `$2C07` | `$0B` | `$60BA` | player-tracking enemy |
| `$BBE7` | `$1BBE7` | `88 11 01 28` | `$1188` | `$2801` | `$0A` | `$86A6` | animated enemy |
| `$BBEB` | `$1BBEB` | `a8 11 11 28` | `$11A8` | `$2811` | `$0A` | `$86A6` | animated enemy |
| `$BBEF` | `$1BBEF` | `11 12 04 10` | `$1211` | `$1004` | `$04` | `$55E9` | terrain-bound enemy |
| `$BBF3` | `$1BBF3` | `35 12 06 2c` | `$1235` | `$2C06` | `$0B` | `$60BA` | player-tracking enemy |
| `$BBF7` | `$1BBF7` | `b4 12 01 60` | `$12B4` | `$6001` | `$18` | `$5526` | collision/terrain table control |
| `$BBFB` | `$1BBFB` | `b4 12 02 60` | `$12B4` | `$6002` | `$18` | `$5526` | collision/terrain table control |
| `$BBFF` | `$1BBFF` | `18 13 00 9c` | `$1318` | `$9C00` | `$27` | `$F366` | stage transition control |
| `$BC03` | `$1BC03` | `a0 13 00 58` | `$13A0` | `$5800` | `$16` | `$98FD` | Dobkeratops multipart parent |
| `$BC07` | `$1BC07` | `8a 14 00 08` | `$148A` | `$0800` | `$02` | `$F429` | stop X scroll |
| `$BC0B` | `$1BC0B` | `c0 14 00 68` | `$14C0` | `$6800` | `$1A` | `$5596` | boss arena collision-table setup |
| `$BC0F` | `$1BC0F` | `fe 14 00 a0` | `$14FE` | `$A000` | `$28` | `$F130` | stop all scroll velocities |
| `$BC13` | `$1BC13` | `00 15 04 64` | `$1500` | `$6404` | `$19` | `$F01B` | next-stage init |

## Stage 2: `ES:$BC17..$BCBF`

| `$BC17` | `$1BC17` | `00 15 00 04` | `$1500` | `$0400` | `$01` | `$F461` | stage control |
| `$BC1B` | `$1BC1B` | `64 15 0a 34` | `$1564` | `$340A` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC1F` | `$1BC1F` | `c8 15 00 34` | `$15C8` | `$3400` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC23` | `$1BC23` | `03 16 35 10` | `$1603` | `$1035` | `$04` | `$55E9` | terrain-bound enemy |
| `$BC27` | `$1BC27` | `2c 16 01 34` | `$162C` | `$3401` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC2B` | `$1BC2B` | `90 16 07 34` | `$1690` | `$3407` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC2F` | `$1BC2F` | `ea 16 01 34` | `$16EA` | `$3401` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC33` | `$1BC33` | `26 17 02 34` | `$1726` | `$3402` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC37` | `$1BC37` | `2b 17 00 34` | `$172B` | `$3400` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC3B` | `$1BC3B` | `30 17 0e 34` | `$1730` | `$340E` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC3F` | `$1BC3F` | `9e 17 07 34` | `$179E` | `$3407` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC43` | `$1BC43` | `9e 17 05 34` | `$179E` | `$3405` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC47` | `$1BC47` | `e4 17 02 34` | `$17E4` | `$3402` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC4B` | `$1BC4B` | `20 18 01 34` | `$1820` | `$3401` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC4F` | `$1BC4F` | `2a 18 00 3c` | `$182A` | `$3C00` | `$0F` | `$875D` | fixed object $8000/$8798 at ($02C0,$0120) |
| `$BC53` | `$1BC53` | `34 18 03 34` | `$1834` | `$3403` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC57` | `$1BC57` | `70 18 01 90` | `$1870` | `$9001` | `$24` | `$7D68` | enemy entry $A000/$7DBB, two command variants |
| `$BC5B` | `$1BC5B` | `84 18 00 34` | `$1884` | `$3400` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC5F` | `$1BC5F` | `ed 18 03 34` | `$18ED` | `$3403` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC63` | `$1BC63` | `f2 18 0c 34` | `$18F2` | `$340C` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC67` | `$1BC67` | `10 19 14 10` | `$1910` | `$1014` | `$04` | `$55E9` | terrain-bound enemy |
| `$BC6B` | `$1BC6B` | `1a 19 03 34` | `$191A` | `$3403` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC6F` | `$1BC6F` | `5a 19 00 90` | `$195A` | `$9000` | `$24` | `$7D68` | enemy entry $A000/$7DBB, two command variants |
| `$BC73` | `$1BC73` | `88 19 00 34` | `$1988` | `$3400` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC77` | `$1BC77` | `a6 19 02 34` | `$19A6` | `$3402` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC7B` | `$1BC7B` | `1e 1a 01 34` | `$1A1E` | `$3401` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC7F` | `$1BC7F` | `28 1a 04 34` | `$1A28` | `$3404` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC83` | `$1BC83` | `40 1a 05 00` | `$1A40` | `$0005` | `$00` | `$F0F3` | stage speed/config |
| `$BC87` | `$1BC87` | `5e 1a 07 34` | `$1A5E` | `$3407` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC8B` | `$1BC8B` | `78 1a 01 34` | `$1A78` | `$3401` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC8F` | `$1BC8F` | `cc 1a 02 34` | `$1ACC` | `$3402` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC93` | `$1BC93` | `2c 1b 02 34` | `$1B2C` | `$3402` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC97` | `$1BC97` | `a4 1b 03 34` | `$1BA4` | `$3403` | `$0D` | `$6F89` | post-boss/stage object |
| `$BC9B` | `$1BC9B` | `da 1b 06 10` | `$1BDA` | `$1006` | `$04` | `$55E9` | terrain-bound enemy |
| `$BC9F` | `$1BC9F` | `08 1c 02 34` | `$1C08` | `$3402` | `$0D` | `$6F89` | post-boss/stage object |
| `$BCA3` | `$1BCA3` | `08 1c 00 34` | `$1C08` | `$3400` | `$0D` | `$6F89` | post-boss/stage object |
| `$BCA7` | `$1BCA7` | `3e 1c 01 34` | `$1C3E` | `$3401` | `$0D` | `$6F89` | post-boss/stage object |
| `$BCAB` | `$1BCAB` | `44 1c 04 74` | `$1C44` | `$7404` | `$1D` | `$915B` | multipart object root $1800/$91CC |
| `$BCAF` | `$1BCAF` | `b2 1c 07 10` | `$1CB2` | `$1007` | `$04` | `$55E9` | terrain-bound enemy |
| `$BCB3` | `$1BCB3` | `b0 1e 00 9c` | `$1EB0` | `$9C00` | `$27` | `$F366` | stage transition control |
| `$BCB7` | `$1BCB7` | `40 1f 00 70` | `$1F40` | `$7000` | `$1C` | `$A22E` | boss/stage controller $3800/$A290; stops all scroll |
| `$BCBB` | `$1BCBB` | `7e 1f 00 a0` | `$1F7E` | `$A000` | `$28` | `$F130` | stop all scroll velocities |
| `$BCBF` | `$1BCBF` | `80 1f 06 64` | `$1F80` | `$6406` | `$19` | `$F01B` | next-stage init |

## Stage 3: `ES:$BCC3..$BCFB`

| `$BCC3` | `$1BCC3` | `80 1f 00 04` | `$1F80` | `$0400` | `$01` | `$F461` | stage control |
| `$BCC7` | `$1BCC7` | `00 20 00 5c` | `$2000` | `$5C00` | `$17` | `$C46E` | stage-control object $FF00/$C4BC |
| `$BCCB` | `$1BCCB` | `48 20 14 10` | `$2048` | `$1014` | `$04` | `$55E9` | terrain-bound enemy |
| `$BCCF` | `$1BCCF` | `43 21 16 10` | `$2143` | `$1016` | `$04` | `$55E9` | terrain-bound enemy |
| `$BCD3` | `$1BCD3` | `22 23 2c 6c` | `$2322` | `$6C2C` | `$1B` | `$596D` | red scripted flyer |
| `$BCD7` | `$1BCD7` | `68 23 3d 6c` | `$2368` | `$6C3D` | `$1B` | `$596D` | red scripted flyer |
| `$BCDB` | `$1BCDB` | `e3 23 2b 6c` | `$23E3` | `$6C2B` | `$1B` | `$596D` | red scripted flyer |
| `$BCDF` | `$1BCDF` | `fa 23 47 10` | `$23FA` | `$1047` | `$04` | `$55E9` | terrain-bound enemy |
| `$BCE3` | `$1BCE3` | `84 24 28 14` | `$2484` | `$1428` | `$05` | `$5A02` | ground walker |
| `$BCE7` | `$1BCE7` | `93 24 38 14` | `$2493` | `$1438` | `$05` | `$5A02` | ground walker |
| `$BCEB` | `$1BCEB` | `c8 27 0e 10` | `$27C8` | `$100E` | `$04` | `$55E9` | terrain-bound enemy |
| `$BCEF` | `$1BCEF` | `a8 29 07 10` | `$29A8` | `$1007` | `$04` | `$55E9` | terrain-bound enemy |
| `$BCF3` | `$1BCF3` | `c0 29 00 08` | `$29C0` | `$0800` | `$02` | `$F429` | stop X scroll |
| `$BCF7` | `$1BCF7` | `c4 29 00 08` | `$29C4` | `$0800` | `$02` | `$F429` | stop X scroll |
| `$BCFB` | `$1BCFB` | `00 2a 07 64` | `$2A00` | `$6407` | `$19` | `$F01B` | next-stage init |

## Stage 4: `ES:$BCFF..$BF2B`

| `$BCFF` | `$1BCFF` | `00 2a 00 04` | `$2A00` | `$0400` | `$01` | `$F461` | stage control |
| `$BD03` | `$1BD03` | `08 2a 04 80` | `$2A08` | `$8004` | `$20` | `$FB9C` | stage resource/control event |
| `$BD07` | `$1BD07` | `08 2a 05 80` | `$2A08` | `$8005` | `$20` | `$FB9C` | stage resource/control event |
| `$BD0B` | `$1BD0B` | `08 2a 06 80` | `$2A08` | `$8006` | `$20` | `$FB9C` | stage resource/control event |
| `$BD0F` | `$1BD0F` | `08 2a 07 80` | `$2A08` | `$8007` | `$20` | `$FB9C` | stage resource/control event |
| `$BD13` | `$1BD13` | `08 2a 08 80` | `$2A08` | `$8008` | `$20` | `$FB9C` | stage resource/control event |
| `$BD17` | `$1BD17` | `08 2a 09 80` | `$2A08` | `$8009` | `$20` | `$FB9C` | stage resource/control event |
| `$BD1B` | `$1BD1B` | `53 2a 45 38` | `$2A53` | `$3845` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD1F` | `$1BD1F` | `5e 2a 06 38` | `$2A5E` | `$3806` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD23` | `$1BD23` | `9b 2a 07 10` | `$2A9B` | `$1007` | `$04` | `$55E9` | terrain-bound enemy |
| `$BD27` | `$1BD27` | `dc 2a 08 54` | `$2ADC` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BD2B` | `$1BD2B` | `0d 2b 03 38` | `$2B0D` | `$3803` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD2F` | `$1BD2F` | `22 2b 06 6c` | `$2B22` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$BD33` | `$1BD33` | `23 2b 36 18` | `$2B23` | `$1836` | `$06` | `$897E` | terrain-aware enemy |
| `$BD37` | `$1BD37` | `29 2b 23 6c` | `$2B29` | `$6C23` | `$1B` | `$596D` | red scripted flyer |
| `$BD3B` | `$1BD3B` | `2c 2b 48 18` | `$2B2C` | `$1848` | `$06` | `$897E` | terrain-aware enemy |
| `$BD3F` | `$1BD3F` | `3a 2b 05 6c` | `$2B3A` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BD43` | `$1BD43` | `48 2b 02 6c` | `$2B48` | `$6C02` | `$1B` | `$596D` | red scripted flyer |
| `$BD47` | `$1BD47` | `4e 2b 06 6c` | `$2B4E` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$BD4B` | `$1BD4B` | `5a 2b 23 6c` | `$2B5A` | `$6C23` | `$1B` | `$596D` | red scripted flyer |
| `$BD4F` | `$1BD4F` | `5e 2b 05 6c` | `$2B5E` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BD53` | `$1BD53` | `5e 2b 08 54` | `$2B5E` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BD57` | `$1BD57` | `75 2b 29 6c` | `$2B75` | `$6C29` | `$1B` | `$596D` | red scripted flyer |
| `$BD5B` | `$1BD5B` | `82 2b 06 6c` | `$2B82` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$BD5F` | `$1BD5F` | `8e 2b 05 6c` | `$2B8E` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BD63` | `$1BD63` | `9e 2b 81 38` | `$2B9E` | `$3881` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD67` | `$1BD67` | `a0 2b 03 6c` | `$2BA0` | `$6C03` | `$1B` | `$596D` | red scripted flyer |
| `$BD6B` | `$1BD6B` | `aa 2b 16 6c` | `$2BAA` | `$6C16` | `$1B` | `$596D` | red scripted flyer |
| `$BD6F` | `$1BD6F` | `b6 2b 05 6c` | `$2BB6` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BD73` | `$1BD73` | `c9 2b 05 6c` | `$2BC9` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$BD77` | `$1BD77` | `dd 2b 34 10` | `$2BDD` | `$1034` | `$04` | `$55E9` | terrain-bound enemy |
| `$BD7B` | `$1BD7B` | `fe 2b 5f 38` | `$2BFE` | `$385F` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD7F` | `$1BD7F` | `00 2c 16 6c` | `$2C00` | `$6C16` | `$1B` | `$596D` | red scripted flyer |
| `$BD83` | `$1BD83` | `0b 2c 03 6c` | `$2C0B` | `$6C03` | `$1B` | `$596D` | red scripted flyer |
| `$BD87` | `$1BD87` | `0b 2c a2 38` | `$2C0B` | `$38A2` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD8B` | `$1BD8B` | `1f 2c 24 6c` | `$2C1F` | `$6C24` | `$1B` | `$596D` | red scripted flyer |
| `$BD8F` | `$1BD8F` | `26 2c 48 14` | `$2C26` | `$1448` | `$05` | `$5A02` | ground walker |
| `$BD93` | `$1BD93` | `30 2c 28 6c` | `$2C30` | `$6C28` | `$1B` | `$596D` | red scripted flyer |
| `$BD97` | `$1BD97` | `36 2c 05 38` | `$2C36` | `$3805` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BD9B` | `$1BD9B` | `3a 2c 13 6c` | `$2C3A` | `$6C13` | `$1B` | `$596D` | red scripted flyer |
| `$BD9F` | `$1BD9F` | `3f 2c 08 54` | `$2C3F` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BDA3` | `$1BDA3` | `6c 2c 43 10` | `$2C6C` | `$1043` | `$04` | `$55E9` | terrain-bound enemy |
| `$BDA7` | `$1BDA7` | `a6 2c 80 38` | `$2CA6` | `$3880` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDAB` | `$1BDAB` | `a6 2c 31 14` | `$2CA6` | `$1431` | `$05` | `$5A02` | ground walker |
| `$BDAF` | `$1BDAF` | `ba 2c 21 15` | `$2CBA` | `$1521` | `$05` | `$5A02` | ground walker |
| `$BDB3` | `$1BDB3` | `bc 2c 47 18` | `$2CBC` | `$1847` | `$06` | `$897E` | terrain-aware enemy |
| `$BDB7` | `$1BDB7` | `20 2d 22 32` | `$2D20` | `$3222` | `$0C` | `$5DC8` | patrol formation parent |
| `$BDBB` | `$1BDBB` | `ae 2d 9a 38` | `$2DAE` | `$389A` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDBF` | `$1BDBF` | `b0 2d 04 38` | `$2DB0` | `$3804` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDC3` | `$1BDC3` | `bb 2d 81 38` | `$2DBB` | `$3881` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDC7` | `$1BDC7` | `c0 2d 5f 38` | `$2DC0` | `$385F` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDCB` | `$1BDCB` | `cc 2d 47 18` | `$2DCC` | `$1847` | `$06` | `$897E` | terrain-aware enemy |
| `$BDCF` | `$1BDCF` | `e8 2d 06 3a` | `$2DE8` | `$3A06` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDD3` | `$1BDD3` | `ea 2d 00 50` | `$2DEA` | `$5000` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BDD7` | `$1BDD7` | `00 2e 3d 18` | `$2E00` | `$183D` | `$06` | `$897E` | terrain-aware enemy |
| `$BDDB` | `$1BDDB` | `06 2e 5d 38` | `$2E06` | `$385D` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDDF` | `$1BDDF` | `4b 2e 05 38` | `$2E4B` | `$3805` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDE3` | `$1BDE3` | `4b 2e 10 15` | `$2E4B` | `$1510` | `$05` | `$5A02` | ground walker |
| `$BDE7` | `$1BDE7` | `5f 2e 10 15` | `$2E5F` | `$1510` | `$05` | `$5A02` | ground walker |
| `$BDEB` | `$1BDEB` | `73 2e 20 15` | `$2E73` | `$1520` | `$05` | `$5A02` | ground walker |
| `$BDEF` | `$1BDEF` | `73 2e 21 14` | `$2E73` | `$1421` | `$05` | `$5A02` | ground walker |
| `$BDF3` | `$1BDF3` | `79 2e 06 38` | `$2E79` | `$3806` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BDF7` | `$1BDF7` | `92 2e 54 10` | `$2E92` | `$1054` | `$04` | `$55E9` | terrain-bound enemy |
| `$BDFB` | `$1BDFB` | `ce 2e 78 10` | `$2ECE` | `$1078` | `$04` | `$55E9` | terrain-bound enemy |
| `$BDFF` | `$1BDFF` | `d1 2e 02 50` | `$2ED1` | `$5002` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BE03` | `$1BE03` | `d8 2e 04 38` | `$2ED8` | `$3804` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE07` | `$1BE07` | `00 2f 21 15` | `$2F00` | `$1521` | `$05` | `$5A02` | ground walker |
| `$BE0B` | `$1BE0B` | `00 2f 5f 38` | `$2F00` | `$385F` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE0F` | `$1BE0F` | `1e 2f 38 14` | `$2F1E` | `$1438` | `$05` | `$5A02` | ground walker |
| `$BE13` | `$1BE13` | `32 2f 28 14` | `$2F32` | `$1428` | `$05` | `$5A02` | ground walker |
| `$BE17` | `$1BE17` | `32 2f 30 15` | `$2F32` | `$1530` | `$05` | `$5A02` | ground walker |
| `$BE1B` | `$1BE1B` | `32 2f 2f 15` | `$2F32` | `$152F` | `$05` | `$5A02` | ground walker |
| `$BE1F` | `$1BE1F` | `35 2f 08 54` | `$2F35` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$BE23` | `$1BE23` | `3a 2f 4c 15` | `$2F3A` | `$154C` | `$05` | `$5A02` | ground walker |
| `$BE27` | `$1BE27` | `3b 2f c2 38` | `$2F3B` | `$38C2` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE2B` | `$1BE2B` | `3c 2f 2c 15` | `$2F3C` | `$152C` | `$05` | `$5A02` | ground walker |
| `$BE2F` | `$1BE2F` | `3e 2f bd 38` | `$2F3E` | `$38BD` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE33` | `$1BE33` | `3f 2f 0c 54` | `$2F3F` | `$540C` | `$15` | `$74B4` | large terrain enemy |
| `$BE37` | `$1BE37` | `40 2f 08 00` | `$2F40` | `$0008` | `$00` | `$F0F3` | stage speed/config |
| `$BE3B` | `$1BE3B` | `48 2f 04 80` | `$2F48` | `$8004` | `$20` | `$FB9C` | stage resource/control event |
| `$BE3F` | `$1BE3F` | `48 2f 05 80` | `$2F48` | `$8005` | `$20` | `$FB9C` | stage resource/control event |
| `$BE43` | `$1BE43` | `48 2f 06 80` | `$2F48` | `$8006` | `$20` | `$FB9C` | stage resource/control event |
| `$BE47` | `$1BE47` | `48 2f 07 80` | `$2F48` | `$8007` | `$20` | `$FB9C` | stage resource/control event |
| `$BE4B` | `$1BE4B` | `48 2f 08 80` | `$2F48` | `$8008` | `$20` | `$FB9C` | stage resource/control event |
| `$BE4F` | `$1BE4F` | `48 2f 09 80` | `$2F48` | `$8009` | `$20` | `$FB9C` | stage resource/control event |
| `$BE53` | `$1BE53` | `8c 2f 34 18` | `$2F8C` | `$1834` | `$06` | `$897E` | terrain-aware enemy |
| `$BE57` | `$1BE57` | `91 2f 81 38` | `$2F91` | `$3881` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE5B` | `$1BE5B` | `a0 2f 80 38` | `$2FA0` | `$3880` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE5F` | `$1BE5F` | `00 30 9a 38` | `$3000` | `$389A` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE63` | `$1BE63` | `0b 30 13 10` | `$300B` | `$1013` | `$04` | `$55E9` | terrain-bound enemy |
| `$BE67` | `$1BE67` | `0c 30 09 50` | `$300C` | `$5009` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BE6B` | `$1BE6B` | `0e 30 99 38` | `$300E` | `$3899` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE6F` | `$1BE6F` | `18 30 05 38` | `$3018` | `$3805` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE73` | `$1BE73` | `22 30 04 38` | `$3022` | `$3804` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE77` | `$1BE77` | `34 30 07 38` | `$3034` | `$3807` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE7B` | `$1BE7B` | `55 30 22 14` | `$3055` | `$1422` | `$05` | `$5A02` | ground walker |
| `$BE7F` | `$1BE7F` | `5f 30 21 15` | `$305F` | `$1521` | `$05` | `$5A02` | ground walker |
| `$BE83` | `$1BE83` | `82 30 35 10` | `$3082` | `$1035` | `$04` | `$55E9` | terrain-bound enemy |
| `$BE87` | `$1BE87` | `89 30 2e 18` | `$3089` | `$182E` | `$06` | `$897E` | terrain-aware enemy |
| `$BE8B` | `$1BE8B` | `93 30 60 18` | `$3093` | `$1860` | `$06` | `$897E` | terrain-aware enemy |
| `$BE8F` | `$1BE8F` | `9b 30 32 18` | `$309B` | `$1832` | `$06` | `$897E` | terrain-aware enemy |
| `$BE93` | `$1BE93` | `a0 30 7b 38` | `$30A0` | `$387B` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE97` | `$1BE97` | `cd 30 bd 38` | `$30CD` | `$38BD` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE9B` | `$1BE9B` | `12 31 a2 38` | `$3112` | `$38A2` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BE9F` | `$1BE9F` | `5a 31 05 38` | `$315A` | `$3805` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BEA3` | `$1BEA3` | `61 31 04 38` | `$3161` | `$3804` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BEA7` | `$1BEA7` | `64 31 07 38` | `$3164` | `$3807` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BEAB` | `$1BEAB` | `6c 31 06 38` | `$316C` | `$3806` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BEAF` | `$1BEAF` | `6f 31 03 38` | `$316F` | `$3803` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BEB3` | `$1BEB3` | `6f 31 5e 38` | `$316F` | `$385E` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BEB7` | `$1BEB7` | `8d 31 47 10` | `$318D` | `$1047` | `$04` | `$55E9` | terrain-bound enemy |
| `$BEBB` | `$1BEBB` | `0c 32 05 18` | `$320C` | `$1805` | `$06` | `$897E` | terrain-aware enemy |
| `$BEBF` | `$1BEBF` | `31 32 02 18` | `$3231` | `$1802` | `$06` | `$897E` | terrain-aware enemy |
| `$BEC3` | `$1BEC3` | `45 32 01 50` | `$3245` | `$5001` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEC7` | `$1BEC7` | `5e 32 07 18` | `$325E` | `$1807` | `$06` | `$897E` | terrain-aware enemy |
| `$BECB` | `$1BECB` | `6c 32 06 18` | `$326C` | `$1806` | `$06` | `$897E` | terrain-aware enemy |
| `$BECF` | `$1BECF` | `7c 32 53 10` | `$327C` | `$1053` | `$04` | `$55E9` | terrain-bound enemy |
| `$BED3` | `$1BED3` | `7c 32 35 10` | `$327C` | `$1035` | `$04` | `$55E9` | terrain-bound enemy |
| `$BED7` | `$1BED7` | `84 32 08 10` | `$3284` | `$1008` | `$04` | `$55E9` | terrain-bound enemy |
| `$BEDB` | `$1BEDB` | `8b 32 09 50` | `$328B` | `$5009` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEDF` | `$1BEDF` | `98 32 36 18` | `$3298` | `$1836` | `$06` | `$897E` | terrain-aware enemy |
| `$BEE3` | `$1BEE3` | `9d 32 0a 50` | `$329D` | `$500A` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEE7` | `$1BEE7` | `a2 32 0c 50` | `$32A2` | `$500C` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEEB` | `$1BEEB` | `a2 32 0d 50` | `$32A2` | `$500D` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEEF` | `$1BEEF` | `a2 32 0e 50` | `$32A2` | `$500E` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEF3` | `$1BEF3` | `a2 32 0f 50` | `$32A2` | `$500F` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEF7` | `$1BEF7` | `ac 32 43 18` | `$32AC` | `$1843` | `$06` | `$897E` | terrain-aware enemy |
| `$BEFB` | `$1BEFB` | `db 32 0e 50` | `$32DB` | `$500E` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BEFF` | `$1BEFF` | `e8 32 01 50` | `$32E8` | `$5001` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BF03` | `$1BF03` | `f2 32 02 50` | `$32F2` | `$5002` | `$14` | `$8F5E` | enemy entry $8230/$8F86, table ES:$3F76 |
| `$BF07` | `$1BF07` | `1a 33 30 18` | `$331A` | `$1830` | `$06` | `$897E` | terrain-aware enemy |
| `$BF0B` | `$1BF0B` | `29 33 80 18` | `$3329` | `$1880` | `$06` | `$897E` | terrain-aware enemy |
| `$BF0F` | `$1BF0F` | `2e 33 60 18` | `$332E` | `$1860` | `$06` | `$897E` | terrain-aware enemy |
| `$BF13` | `$1BF13` | `c4 33 23 3a` | `$33C4` | `$3A23` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BF17` | `$1BF17` | `0a 34 04 38` | `$340A` | `$3804` | `$0E` | `$696E` | enemy entry $8010/$69B4, position/animation decoders |
| `$BF1B` | `$1BF1B` | `de 32 00 9c` | `$32DE` | `$9C00` | `$27` | `$F366` | stage transition control |
| `$BF1F` | `$1BF1F` | `7a 34 01 84` | `$347A` | `$8401` | `$21` | `$E430` | stage resource owner |
| `$BF23` | `$1BF23` | `7c 34 00 8c` | `$347C` | `$8C00` | `$23` | `$A71D` | randomized stage object $1000/$A762 |
| `$BF27` | `$1BF27` | `7e 34 00 a0` | `$347E` | `$A000` | `$28` | `$F130` | stop all scroll velocities |
| `$BF2B` | `$1BF2B` | `80 34 09 64` | `$3480` | `$6409` | `$19` | `$F01B` | next-stage init |

## Stage 5: `ES:$BF2F..$C067`

| `$BF2F` | `$1BF2F` | `80 34 00 04` | `$3480` | `$0400` | `$01` | `$F461` | stage control |
| `$BF33` | `$1BF33` | `d9 34 26 1c` | `$34D9` | `$1C26` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF37` | `$1BF37` | `19 35 74 1f` | `$3519` | `$1F74` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF3B` | `$1BF3B` | `6b 35 36 10` | `$356B` | `$1036` | `$04` | `$55E9` | terrain-bound enemy |
| `$BF3F` | `$1BF3F` | `a6 35 1a 1e` | `$35A6` | `$1E1A` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF43` | `$1BF43` | `2d 36 66 10` | `$362D` | `$1066` | `$04` | `$55E9` | terrain-bound enemy |
| `$BF47` | `$1BF47` | `42 36 1b 1d` | `$3642` | `$1D1B` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF4B` | `$1BF4B` | `6b 36 81 1f` | `$366B` | `$1F81` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF4F` | `$1BF4F` | `94 36 52 78` | `$3694` | `$7852` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF53` | `$1BF53` | `d8 36 61 78` | `$36D8` | `$7861` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF57` | `$1BF57` | `d8 36 27 1f` | `$36D8` | `$1F27` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF5B` | `$1BF5B` | `91 37 63 78` | `$3791` | `$7863` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF5F` | `$1BF5F` | `a0 37 59 78` | `$37A0` | `$7859` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF63` | `$1BF63` | `b4 37 1b 1d` | `$37B4` | `$1D1B` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF67` | `$1BF67` | `fa 37 02 1e` | `$37FA` | `$1E02` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF6B` | `$1BF6B` | `1b 38 74 1c` | `$381B` | `$1C74` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BF6F` | `$1BF6F` | `68 38 14 10` | `$3868` | `$1014` | `$04` | `$55E9` | terrain-bound enemy |
| `$BF73` | `$1BF73` | `72 38 51 78` | `$3872` | `$7851` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF77` | `$1BF77` | `9a 38 49 78` | `$389A` | `$7849` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF7B` | `$1BF7B` | `ea 38 61 78` | `$38EA` | `$7861` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF7F` | `$1BF7F` | `f9 38 53 78` | `$38F9` | `$7853` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BF83` | `$1BF83` | `f9 38 46 18` | `$38F9` | `$1846` | `$06` | `$897E` | terrain-aware enemy |
| `$BF87` | `$1BF87` | `2f 39 0a 4c` | `$392F` | `$4C0A` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BF8B` | `$1BF8B` | `38 39 03 4c` | `$3938` | `$4C03` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BF8F` | `$1BF8F` | `3a 39 09 4c` | `$393A` | `$4C09` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BF93` | `$1BF93` | `44 39 02 4c` | `$3944` | `$4C02` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BF97` | `$1BF97` | `58 39 0b 4c` | `$3958` | `$4C0B` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BF9B` | `$1BF9B` | `5d 39 0a 4c` | `$395D` | `$4C0A` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BF9F` | `$1BF9F` | `5e 39 04 4c` | `$395E` | `$4C04` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFA3` | `$1BFA3` | `5e 39 1b 1c` | `$395E` | `$1C1B` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BFA7` | `$1BFA7` | `62 39 0b 4c` | `$3962` | `$4C0B` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFAB` | `$1BFAB` | `66 39 03 4c` | `$3966` | `$4C03` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFAF` | `$1BFAF` | `72 39 0a 4c` | `$3972` | `$4C0A` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFB3` | `$1BFB3` | `78 39 01 4c` | `$3978` | `$4C01` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFB7` | `$1BFB7` | `80 39 09 4c` | `$3980` | `$4C09` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFBB` | `$1BFBB` | `8a 39 02 4c` | `$398A` | `$4C02` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFBF` | `$1BFBF` | `94 39 0b 4c` | `$3994` | `$4C0B` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$BFC3` | `$1BFC3` | `94 39 1a 1d` | `$3994` | `$1D1A` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BFC7` | `$1BFC7` | `ee 39 48 1f` | `$39EE` | `$1F48` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BFCB` | `$1BFCB` | `ee 39 53 1e` | `$39EE` | `$1E53` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$BFCF` | `$1BFCF` | `16 3a 6a 78` | `$3A16` | `$786A` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BFD3` | `$1BFD3` | `34 3a 50 78` | `$3A34` | `$7850` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BFD7` | `$1BFD7` | `7f 3a 52 78` | `$3A7F` | `$7852` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BFDB` | `$1BFDB` | `8b 3a 68 78` | `$3A8B` | `$7868` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BFDF` | `$1BFDF` | `b5 3a 60 78` | `$3AB5` | `$7860` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BFE3` | `$1BFE3` | `c0 3a 0a 00` | `$3AC0` | `$000A` | `$00` | `$F0F3` | stage speed/config |
| `$BFE7` | `$1BFE7` | `d4 3a 0d b4` | `$3AD4` | `$B40D` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$BFEB` | `$1BFEB` | `e4 3a 0a b4` | `$3AE4` | `$B40A` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$BFEF` | `$1BFEF` | `0e 3b 74 10` | `$3B0E` | `$1074` | `$04` | `$55E9` | terrain-bound enemy |
| `$BFF3` | `$1BFF3` | `74 3b 03 b4` | `$3B74` | `$B403` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$BFF7` | `$1BFF7` | `8a 3b 5a 18` | `$3B8A` | `$185A` | `$06` | `$897E` | terrain-aware enemy |
| `$BFFB` | `$1BFFB` | `8d 3b 67 78` | `$3B8D` | `$7867` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$BFFF` | `$1BFFF` | `92 3b 52 78` | `$3B92` | `$7852` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C003` | `$1C003` | `d7 3b 34 10` | `$3BD7` | `$1034` | `$04` | `$55E9` | terrain-bound enemy |
| `$C007` | `$1C007` | `f1 3b 49 78` | `$3BF1` | `$7849` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C00B` | `$1C00B` | `50 3c 37 10` | `$3C50` | `$1037` | `$04` | `$55E9` | terrain-bound enemy |
| `$C00F` | `$1C00F` | `64 3c 68 78` | `$3C64` | `$7868` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C013` | `$1C013` | `92 3c 69 78` | `$3C92` | `$7869` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C017` | `$1C017` | `96 3c 07 b4` | `$3C96` | `$B407` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$C01B` | `$1C01B` | `be 3c 0c b4` | `$3CBE` | `$B40C` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$C01F` | `$1C01F` | `dc 3c 42 78` | `$3CDC` | `$7842` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C023` | `$1C023` | `dc 3c 05 b4` | `$3CDC` | `$B405` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$C027` | `$1C027` | `fa 3c 59 78` | `$3CFA` | `$7859` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C02B` | `$1C02B` | `4a 3d 49 18` | `$3D4A` | `$1849` | `$06` | `$897E` | terrain-aware enemy |
| `$C02F` | `$1C02F` | `54 3d 60 78` | `$3D54` | `$7860` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C033` | `$1C033` | `68 3d 59 78` | `$3D68` | `$7859` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C037` | `$1C037` | `90 3d 04 b4` | `$3D90` | `$B404` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$C03B` | `$1C03B` | `9a 3d 09 b4` | `$3D9A` | `$B409` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$C03F` | `$1C03F` | `a8 3d 64 78` | `$3DA8` | `$7864` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C043` | `$1C043` | `ae 3d 0d b4` | `$3DAE` | `$B40D` | `$2D` | `$8561` | enemy entry $8020/$85B0, difficulty table |
| `$C047` | `$1C047` | `b2 3d 5a 78` | `$3DB2` | `$785A` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C04B` | `$1C04B` | `fe 3d 01 1f` | `$3DFE` | `$1F01` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$C04F` | `$1C04F` | `1c 3e 1a 1e` | `$3E1C` | `$1E1A` | `$07` | `$78F8` | enemy entry: priority из ES:$34AE, runtime $7935 |
| `$C053` | `$1C053` | `4e 3e 50 78` | `$3E4E` | `$7850` | `$1E` | `$7182` | enemy entry $8020/$71C7, fire table + ES:$31FE |
| `$C057` | `$1C057` | `58 3e 00 9c` | `$3E58` | `$9C00` | `$27` | `$F366` | stage transition control |
| `$C05B` | `$1C05B` | `a8 3e 15 10` | `$3EA8` | `$1015` | `$04` | `$55E9` | terrain-bound enemy |
| `$C05F` | `$1C05F` | `fc 3e 00 a4` | `$3EFC` | `$A400` | `$29` | `$B1D8` | boss/stage controller $7D00/$B1FA |
| `$C063` | `$1C063` | `fe 3e 00 a0` | `$3EFE` | `$A000` | `$28` | `$F130` | stop all scroll velocities |
| `$C067` | `$1C067` | `00 3f 0b 64` | `$3F00` | `$640B` | `$19` | `$F01B` | next-stage init |

## Stage 6: `ES:$C06B..$C253`

| `$C06B` | `$1C06B` | `00 3f 00 04` | `$3F00` | `$0400` | `$01` | `$F461` | stage control |
| `$C06F` | `$1C06F` | `08 3f 41 7d` | `$3F08` | `$7D41` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C073` | `$1C073` | `08 3f 55 7d` | `$3F08` | `$7D55` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C077` | `$1C077` | `14 3f 12 80` | `$3F14` | `$8012` | `$20` | `$FB9C` | stage resource/control event |
| `$C07B` | `$1C07B` | `14 3f 13 80` | `$3F14` | `$8013` | `$20` | `$FB9C` | stage resource/control event |
| `$C07F` | `$1C07F` | `14 3f 14 80` | `$3F14` | `$8014` | `$20` | `$FB9C` | stage resource/control event |
| `$C083` | `$1C083` | `14 3f 15 80` | `$3F14` | `$8015` | `$20` | `$FB9C` | stage resource/control event |
| `$C087` | `$1C087` | `14 3f 16 80` | `$3F14` | `$8016` | `$20` | `$FB9C` | stage resource/control event |
| `$C08B` | `$1C08B` | `70 3f 06 10` | `$3F70` | `$1006` | `$04` | `$55E9` | terrain-bound enemy |
| `$C08F` | `$1C08F` | `8f 3f 22 20` | `$3F8F` | `$2022` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C093` | `$1C093` | `a4 3f 20 20` | `$3FA4` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C097` | `$1C097` | `c8 3f 17 7c` | `$3FC8` | `$7C17` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C09B` | `$1C09B` | `c8 3f 12 7c` | `$3FC8` | `$7C12` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C09F` | `$1C09F` | `df 3f 20 20` | `$3FDF` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0A3` | `$1C0A3` | `02 40 20 20` | `$4002` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0A7` | `$1C0A7` | `14 40 10 7c` | `$4014` | `$7C10` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C0AB` | `$1C0AB` | `1a 40 20 20` | `$401A` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0AF` | `$1C0AF` | `3b 40 20 20` | `$403B` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0B3` | `$1C0B3` | `54 40 15 7c` | `$4054` | `$7C15` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C0B7` | `$1C0B7` | `71 40 20 20` | `$4071` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0BB` | `$1C0BB` | `d3 40 2f 21` | `$40D3` | `$212F` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0BF` | `$1C0BF` | `ea 40 07 7c` | `$40EA` | `$7C07` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C0C3` | `$1C0C3` | `05 41 27 20` | `$4105` | `$2027` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0C7` | `$1C0C7` | `22 41 2e 21` | `$4122` | `$212E` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0CB` | `$1C0CB` | `3d 41 20 21` | `$413D` | `$2120` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0CF` | `$1C0CF` | `64 41 67 14` | `$4164` | `$1467` | `$05` | `$5A02` | ground walker |
| `$C0D3` | `$1C0D3` | `6d 41 29 20` | `$416D` | `$2029` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0D7` | `$1C0D7` | `6e 41 64 14` | `$416E` | `$1464` | `$05` | `$5A02` | ground walker |
| `$C0DB` | `$1C0DB` | `80 41 2d 20` | `$4180` | `$202D` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0DF` | `$1C0DF` | `84 41 64 14` | `$4184` | `$1464` | `$05` | `$5A02` | ground walker |
| `$C0E3` | `$1C0E3` | `8a 41 64 14` | `$418A` | `$1464` | `$05` | `$5A02` | ground walker |
| `$C0E7` | `$1C0E7` | `94 41 29 20` | `$4194` | `$2029` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0EB` | `$1C0EB` | `b3 41 10 7c` | `$41B3` | `$7C10` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C0EF` | `$1C0EF` | `bc 41 20 21` | `$41BC` | `$2120` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0F3` | `$1C0F3` | `c6 41 29 20` | `$41C6` | `$2029` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0F7` | `$1C0F7` | `f7 41 29 20` | `$41F7` | `$2029` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C0FB` | `$1C0FB` | `fc 41 12 7c` | `$41FC` | `$7C12` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C0FF` | `$1C0FF` | `2a 42 24 21` | `$422A` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C103` | `$1C103` | `38 42 0f 7c` | `$4238` | `$7C0F` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C107` | `$1C107` | `48 42 24 21` | `$4248` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C10B` | `$1C10B` | `48 42 20 21` | `$4248` | `$2120` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C10F` | `$1C10F` | `50 42 69 20` | `$4250` | `$2069` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C113` | `$1C113` | `70 42 24 21` | `$4270` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C117` | `$1C117` | `9a 42 2b 21` | `$429A` | `$212B` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C11B` | `$1C11B` | `c0 42 2b 21` | `$42C0` | `$212B` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C11F` | `$1C11F` | `19 43 20 20` | `$4319` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C123` | `$1C123` | `a5 43 39 20` | `$43A5` | `$2039` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C127` | `$1C127` | `a8 43 15 7d` | `$43A8` | `$7D15` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C12B` | `$1C12B` | `b6 43 26 20` | `$43B6` | `$2026` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C12F` | `$1C12F` | `be 43 25 21` | `$43BE` | `$2125` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C133` | `$1C133` | `23 44 2f 21` | `$4423` | `$212F` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C137` | `$1C137` | `8c 44 62 14` | `$448C` | `$1462` | `$05` | `$5A02` | ground walker |
| `$C13B` | `$1C13B` | `af 44 26 21` | `$44AF` | `$2126` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C13F` | `$1C13F` | `08 45 61 14` | `$4508` | `$1461` | `$05` | `$5A02` | ground walker |
| `$C143` | `$1C143` | `0b 45 60 15` | `$450B` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C147` | `$1C147` | `18 45 62 14` | `$4518` | `$1462` | `$05` | `$5A02` | ground walker |
| `$C14B` | `$1C14B` | `1d 45 60 15` | `$451D` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C14F` | `$1C14F` | `20 45 62 14` | `$4520` | `$1462` | `$05` | `$5A02` | ground walker |
| `$C153` | `$1C153` | `2b 45 60 15` | `$452B` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C157` | `$1C157` | `40 45 0c 00` | `$4540` | `$000C` | `$00` | `$F0F3` | stage speed/config |
| `$C15B` | `$1C15B` | `40 45 60 15` | `$4540` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C15F` | `$1C15F` | `4b 45 60 15` | `$454B` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C163` | `$1C163` | `54 45 12 80` | `$4554` | `$8012` | `$20` | `$FB9C` | stage resource/control event |
| `$C167` | `$1C167` | `54 45 13 80` | `$4554` | `$8013` | `$20` | `$FB9C` | stage resource/control event |
| `$C16B` | `$1C16B` | `54 45 14 80` | `$4554` | `$8014` | `$20` | `$FB9C` | stage resource/control event |
| `$C16F` | `$1C16F` | `54 45 15 80` | `$4554` | `$8015` | `$20` | `$FB9C` | stage resource/control event |
| `$C173` | `$1C173` | `54 45 16 80` | `$4554` | `$8016` | `$20` | `$FB9C` | stage resource/control event |
| `$C177` | `$1C177` | `56 45 60 15` | `$4556` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C17B` | `$1C17B` | `60 45 21 20` | `$4560` | `$2021` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C17F` | `$1C17F` | `61 45 60 15` | `$4561` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C183` | `$1C183` | `6c 45 70 15` | `$456C` | `$1570` | `$05` | `$5A02` | ground walker |
| `$C187` | `$1C187` | `77 45 60 15` | `$4577` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C18B` | `$1C18B` | `82 45 50 15` | `$4582` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C18F` | `$1C18F` | `8d 45 60 15` | `$458D` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C193` | `$1C193` | `98 45 50 15` | `$4598` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C197` | `$1C197` | `a3 45 60 15` | `$45A3` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C19B` | `$1C19B` | `a4 45 60 15` | `$45A4` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C19F` | `$1C19F` | `a5 45 15 10` | `$45A5` | `$1015` | `$04` | `$55E9` | terrain-bound enemy |
| `$C1A3` | `$1C1A3` | `af 45 50 15` | `$45AF` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1A7` | `$1C1A7` | `ba 45 60 15` | `$45BA` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C1AB` | `$1C1AB` | `c5 45 50 15` | `$45C5` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1AF` | `$1C1AF` | `d0 45 50 15` | `$45D0` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1B3` | `$1C1B3` | `db 45 50 15` | `$45DB` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1B7` | `$1C1B7` | `e6 45 60 15` | `$45E6` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C1BB` | `$1C1BB` | `f1 45 50 15` | `$45F1` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1BF` | `$1C1BF` | `fc 45 50 15` | `$45FC` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1C3` | `$1C1C3` | `07 46 50 15` | `$4607` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1C7` | `$1C1C7` | `08 46 60 15` | `$4608` | `$1560` | `$05` | `$5A02` | ground walker |
| `$C1CB` | `$1C1CB` | `13 46 40 15` | `$4613` | `$1540` | `$05` | `$5A02` | ground walker |
| `$C1CF` | `$1C1CF` | `1e 46 50 15` | `$461E` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1D3` | `$1C1D3` | `29 46 50 15` | `$4629` | `$1550` | `$05` | `$5A02` | ground walker |
| `$C1D7` | `$1C1D7` | `34 46 24 21` | `$4634` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C1DB` | `$1C1DB` | `3a 46 17 7c` | `$463A` | `$7C17` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C1DF` | `$1C1DF` | `4e 46 24 21` | `$464E` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C1E3` | `$1C1E3` | `6b 46 02 7c` | `$466B` | `$7C02` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C1E7` | `$1C1E7` | `6c 46 24 21` | `$466C` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C1EB` | `$1C1EB` | `80 46 14 7c` | `$4680` | `$7C14` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C1EF` | `$1C1EF` | `8a 46 24 21` | `$468A` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C1F3` | `$1C1F3` | `9e 46 06 10` | `$469E` | `$1006` | `$04` | `$55E9` | terrain-bound enemy |
| `$C1F7` | `$1C1F7` | `a8 46 24 21` | `$46A8` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C1FB` | `$1C1FB` | `ae 46 00 7c` | `$46AE` | `$7C00` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C1FF` | `$1C1FF` | `d0 46 24 21` | `$46D0` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C203` | `$1C203` | `f8 46 17 7c` | `$46F8` | `$7C17` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C207` | `$1C207` | `53 47 02 7c` | `$4753` | `$7C02` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C20B` | `$1C20B` | `53 47 14 7c` | `$4753` | `$7C14` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C20F` | `$1C20F` | `66 47 2b 21` | `$4766` | `$212B` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C213` | `$1C213` | `93 47 2b 21` | `$4793` | `$212B` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C217` | `$1C217` | `98 47 32 21` | `$4798` | `$2132` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C21B` | `$1C21B` | `fc 47 20 20` | `$47FC` | `$2020` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C21F` | `$1C21F` | `fc 47 24 21` | `$47FC` | `$2124` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C223` | `$1C223` | `08 48 11 7d` | `$4808` | `$7D11` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C227` | `$1C227` | `08 48 15 7d` | `$4808` | `$7D15` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C22B` | `$1C22B` | `38 48 22 21` | `$4838` | `$2122` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C22F` | `$1C22F` | `7e 48 2d 21` | `$487E` | `$212D` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C233` | `$1C233` | `8a 48 10 7c` | `$488A` | `$7C10` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C237` | `$1C237` | `8c 48 37 10` | `$488C` | `$1037` | `$04` | `$55E9` | terrain-bound enemy |
| `$C23B` | `$1C23B` | `c4 48 00 9c` | `$48C4` | `$9C00` | `$27` | `$F366` | stage transition control |
| `$C23F` | `$1C23F` | `e2 48 2a 20` | `$48E2` | `$202A` | `$08` | `$5EED` | enemy entry $4030/$5F3C с direction из command |
| `$C243` | `$1C243` | `4c 49 17 7c` | `$494C` | `$7C17` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C247` | `$1C247` | `50 49 10 7c` | `$4950` | `$7C10` | `$1F` | `$7294` | enemy entry $4020/$72D2, command direction |
| `$C24B` | `$1C24B` | `7c 49 00 88` | `$497C` | `$8800` | `$22` | `$B0E1` | boss/stage controller $1000/$B111; stops all scroll |
| `$C24F` | `$1C24F` | `7e 49 00 a0` | `$497E` | `$A000` | `$28` | `$F130` | stop all scroll velocities |
| `$C253` | `$1C253` | `80 49 0d 64` | `$4980` | `$640D` | `$19` | `$F01B` | next-stage init |

## Stage 7: `ES:$C257..$C517`

| `$C257` | `$1C257` | `80 49 00 04` | `$4980` | `$0400` | `$01` | `$F461` | stage control |
| `$C25B` | `$1C25B` | `98 49 02 80` | `$4998` | `$8002` | `$20` | `$FB9C` | stage resource/control event |
| `$C25F` | `$1C25F` | `be 49 47 6c` | `$49BE` | `$6C47` | `$1B` | `$596D` | red scripted flyer |
| `$C263` | `$1C263` | `c6 49 38 6c` | `$49C6` | `$6C38` | `$1B` | `$596D` | red scripted flyer |
| `$C267` | `$1C267` | `cc 49 47 6c` | `$49CC` | `$6C47` | `$1B` | `$596D` | red scripted flyer |
| `$C26B` | `$1C26B` | `d0 49 36 10` | `$49D0` | `$1036` | `$04` | `$55E9` | terrain-bound enemy |
| `$C26F` | `$1C26F` | `e1 49 57 6c` | `$49E1` | `$6C57` | `$1B` | `$596D` | red scripted flyer |
| `$C273` | `$1C273` | `ee 49 38 6c` | `$49EE` | `$6C38` | `$1B` | `$596D` | red scripted flyer |
| `$C277` | `$1C277` | `fa 49 47 6c` | `$49FA` | `$6C47` | `$1B` | `$596D` | red scripted flyer |
| `$C27B` | `$1C27B` | `04 4a 38 6c` | `$4A04` | `$6C38` | `$1B` | `$596D` | red scripted flyer |
| `$C27F` | `$1C27F` | `10 4a 37 6c` | `$4A10` | `$6C37` | `$1B` | `$596D` | red scripted flyer |
| `$C283` | `$1C283` | `24 4a 47 6c` | `$4A24` | `$6C47` | `$1B` | `$596D` | red scripted flyer |
| `$C287` | `$1C287` | `24 4a 05 40` | `$4A24` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C28B` | `$1C28B` | `33 4a 38 6c` | `$4A33` | `$6C38` | `$1B` | `$596D` | red scripted flyer |
| `$C28F` | `$1C28F` | `47 4a 57 6c` | `$4A47` | `$6C57` | `$1B` | `$596D` | red scripted flyer |
| `$C293` | `$1C293` | `52 4a 08 54` | `$4A52` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C297` | `$1C297` | `64 4a 05 40` | `$4A64` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C29B` | `$1C29B` | `69 4a 48 6c` | `$4A69` | `$6C48` | `$1B` | `$596D` | red scripted flyer |
| `$C29F` | `$1C29F` | `83 4a 37 6c` | `$4A83` | `$6C37` | `$1B` | `$596D` | red scripted flyer |
| `$C2A3` | `$1C2A3` | `a2 4a 58 6c` | `$4AA2` | `$6C58` | `$1B` | `$596D` | red scripted flyer |
| `$C2A7` | `$1C2A7` | `a2 4a 44 18` | `$4AA2` | `$1844` | `$06` | `$897E` | terrain-aware enemy |
| `$C2AB` | `$1C2AB` | `a4 4a 05 40` | `$4AA4` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C2AF` | `$1C2AF` | `a4 4a 04 40` | `$4AA4` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C2B3` | `$1C2B3` | `ac 4a 54 18` | `$4AAC` | `$1854` | `$06` | `$897E` | terrain-aware enemy |
| `$C2B7` | `$1C2B7` | `b6 4a 08 54` | `$4AB6` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C2BB` | `$1C2BB` | `bf 4a 4f 18` | `$4ABF` | `$184F` | `$06` | `$897E` | terrain-aware enemy |
| `$C2BF` | `$1C2BF` | `c0 4a 46 14` | `$4AC0` | `$1446` | `$05` | `$5A02` | ground walker |
| `$C2C3` | `$1C2C3` | `c0 4a 58 14` | `$4AC0` | `$1458` | `$05` | `$5A02` | ground walker |
| `$C2C7` | `$1C2C7` | `e4 4a 04 40` | `$4AE4` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C2CB` | `$1C2CB` | `ef 4a 75 10` | `$4AEF` | `$1075` | `$04` | `$55E9` | terrain-bound enemy |
| `$C2CF` | `$1C2CF` | `06 4b 4e 18` | `$4B06` | `$184E` | `$06` | `$897E` | terrain-aware enemy |
| `$C2D3` | `$1C2D3` | `1a 4b 3e 18` | `$4B1A` | `$183E` | `$06` | `$897E` | terrain-aware enemy |
| `$C2D7` | `$1C2D7` | `1e 4b 65 14` | `$4B1E` | `$1465` | `$05` | `$5A02` | ground walker |
| `$C2DB` | `$1C2DB` | `28 4b 22 32` | `$4B28` | `$3222` | `$0C` | `$5DC8` | patrol formation parent |
| `$C2DF` | `$1C2DF` | `49 4b 07 10` | `$4B49` | `$1007` | `$04` | `$55E9` | terrain-bound enemy |
| `$C2E3` | `$1C2E3` | `68 4b 08 54` | `$4B68` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C2E7` | `$1C2E7` | `68 4b 3a 48` | `$4B68` | `$483A` | `$12` | `$8469` | enemy entry $8020/$8490, initial X velocity -$0200 |
| `$C2EB` | `$1C2EB` | `6a 4b 44 18` | `$4B6A` | `$1844` | `$06` | `$897E` | terrain-aware enemy |
| `$C2EF` | `$1C2EF` | `74 4b 3a 48` | `$4B74` | `$483A` | `$12` | `$8469` | enemy entry $8020/$8490, initial X velocity -$0200 |
| `$C2F3` | `$1C2F3` | `84 4b 01 40` | `$4B84` | `$4001` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C2F7` | `$1C2F7` | `8c 4b 37 48` | `$4B8C` | `$4837` | `$12` | `$8469` | enemy entry $8020/$8490, initial X velocity -$0200 |
| `$C2FB` | `$1C2FB` | `9d 4b 56 14` | `$4B9D` | `$1456` | `$05` | `$5A02` | ground walker |
| `$C2FF` | `$1C2FF` | `a3 4b 3a 48` | `$4BA3` | `$483A` | `$12` | `$8469` | enemy entry $8020/$8490, initial X velocity -$0200 |
| `$C303` | `$1C303` | `b9 4b 41 18` | `$4BB9` | `$1841` | `$06` | `$897E` | terrain-aware enemy |
| `$C307` | `$1C307` | `ba 4b 37 18` | `$4BBA` | `$1837` | `$06` | `$897E` | terrain-aware enemy |
| `$C30B` | `$1C30B` | `bc 4b 03 40` | `$4BBC` | `$4003` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C30F` | `$1C30F` | `c4 4b 00 40` | `$4BC4` | `$4000` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C313` | `$1C313` | `f6 4b 46 14` | `$4BF6` | `$1446` | `$05` | `$5A02` | ground walker |
| `$C317` | `$1C317` | `fc 4b 02 40` | `$4BFC` | `$4002` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C31B` | `$1C31B` | `0d 4c 30 18` | `$4C0D` | `$1830` | `$06` | `$897E` | terrain-aware enemy |
| `$C31F` | `$1C31F` | `24 4c 05 40` | `$4C24` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C323` | `$1C323` | `24 4c 0e 10` | `$4C24` | `$100E` | `$04` | `$55E9` | terrain-bound enemy |
| `$C327` | `$1C327` | `32 4c 54 14` | `$4C32` | `$1454` | `$05` | `$5A02` | ground walker |
| `$C32B` | `$1C32B` | `78 4c 00 98` | `$4C78` | `$9800` | `$26` | `$6E9B` | fixed large object $A000/$6EC4 at ($0110,$0108) |
| `$C32F` | `$1C32F` | `84 4c 01 40` | `$4C84` | `$4001` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C333` | `$1C333` | `a4 4c 04 40` | `$4CA4` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C337` | `$1C337` | `b4 4c 47 48` | `$4CB4` | `$4847` | `$12` | `$8469` | enemy entry $8020/$8490, initial X velocity -$0200 |
| `$C33B` | `$1C33B` | `d0 4c 03 40` | `$4CD0` | `$4003` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C33F` | `$1C33F` | `d1 4c 37 48` | `$4CD1` | `$4837` | `$12` | `$8469` | enemy entry $8020/$8490, initial X velocity -$0200 |
| `$C343` | `$1C343` | `f0 4c 46 14` | `$4CF0` | `$1446` | `$05` | `$5A02` | ground walker |
| `$C347` | `$1C347` | `f0 4c 58 14` | `$4CF0` | `$1458` | `$05` | `$5A02` | ground walker |
| `$C34B` | `$1C34B` | `24 4d 05 40` | `$4D24` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C34F` | `$1C34F` | `36 4d 63 14` | `$4D36` | `$1463` | `$05` | `$5A02` | ground walker |
| `$C353` | `$1C353` | `36 4d 56 14` | `$4D36` | `$1456` | `$05` | `$5A02` | ground walker |
| `$C357` | `$1C357` | `36 4d 48 14` | `$4D36` | `$1448` | `$05` | `$5A02` | ground walker |
| `$C35B` | `$1C35B` | `5c 4d 53 14` | `$4D5C` | `$1453` | `$05` | `$5A02` | ground walker |
| `$C35F` | `$1C35F` | `64 4d 05 40` | `$4D64` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C363` | `$1C363` | `64 4d 04 40` | `$4D64` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C367` | `$1C367` | `68 4d 33 14` | `$4D68` | `$1433` | `$05` | `$5A02` | ground walker |
| `$C36B` | `$1C36B` | `9c 4d 45 10` | `$4D9C` | `$1045` | `$04` | `$55E9` | terrain-bound enemy |
| `$C36F` | `$1C36F` | `a7 4d 35 18` | `$4DA7` | `$1835` | `$06` | `$897E` | terrain-aware enemy |
| `$C373` | `$1C373` | `c4 4d 01 40` | `$4DC4` | `$4001` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C377` | `$1C377` | `c4 4d 00 40` | `$4DC4` | `$4000` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C37B` | `$1C37B` | `cc 4d 07 4c` | `$4DCC` | `$4C07` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$C37F` | `$1C37F` | `ea 4d 07 4c` | `$4DEA` | `$4C07` | `$13` | `$5CEA` | enemy entry $8020/$5D2D, difficulty parameters |
| `$C383` | `$1C383` | `f4 4d 45 14` | `$4DF4` | `$1445` | `$05` | `$5A02` | ground walker |
| `$C387` | `$1C387` | `fc 4d 02 40` | `$4DFC` | `$4002` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C38B` | `$1C38B` | `fc 4d 03 40` | `$4DFC` | `$4003` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C38F` | `$1C38F` | `28 4e 08 54` | `$4E28` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C393` | `$1C393` | `64 4e 05 40` | `$4E64` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C397` | `$1C397` | `6c 4e 3e 15` | `$4E6C` | `$153E` | `$05` | `$5A02` | ground walker |
| `$C39B` | `$1C39B` | `86 4e 5f 18` | `$4E86` | `$185F` | `$06` | `$897E` | terrain-aware enemy |
| `$C39F` | `$1C39F` | `93 4e 3e 18` | `$4E93` | `$183E` | `$06` | `$897E` | terrain-aware enemy |
| `$C3A3` | `$1C3A3` | `a4 4e 05 40` | `$4EA4` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C3A7` | `$1C3A7` | `a4 4e 33 18` | `$4EA4` | `$1833` | `$06` | `$897E` | terrain-aware enemy |
| `$C3AB` | `$1C3AB` | `c6 4e 45 18` | `$4EC6` | `$1845` | `$06` | `$897E` | terrain-aware enemy |
| `$C3AF` | `$1C3AF` | `d9 4e 3c 18` | `$4ED9` | `$183C` | `$06` | `$897E` | terrain-aware enemy |
| `$C3B3` | `$1C3B3` | `e4 4e 05 40` | `$4EE4` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C3B7` | `$1C3B7` | `ee 4e 48 18` | `$4EEE` | `$1848` | `$06` | `$897E` | terrain-aware enemy |
| `$C3BB` | `$1C3BB` | `00 4f 0e 00` | `$4F00` | `$000E` | `$00` | `$F0F3` | stage speed/config |
| `$C3BF` | `$1C3BF` | `18 4f 03 80` | `$4F18` | `$8003` | `$20` | `$FB9C` | stage resource/control event |
| `$C3C3` | `$1C3C3` | `24 4f 48 14` | `$4F24` | `$1448` | `$05` | `$5A02` | ground walker |
| `$C3C7` | `$1C3C7` | `38 4f 38 14` | `$4F38` | `$1438` | `$05` | `$5A02` | ground walker |
| `$C3CB` | `$1C3CB` | `46 4f 4e 15` | `$4F46` | `$154E` | `$05` | `$5A02` | ground walker |
| `$C3CF` | `$1C3CF` | `4c 4f 48 14` | `$4F4C` | `$1448` | `$05` | `$5A02` | ground walker |
| `$C3D3` | `$1C3D3` | `60 4f 38 14` | `$4F60` | `$1438` | `$05` | `$5A02` | ground walker |
| `$C3D7` | `$1C3D7` | `74 4f 38 14` | `$4F74` | `$1438` | `$05` | `$5A02` | ground walker |
| `$C3DB` | `$1C3DB` | `88 4f 58 14` | `$4F88` | `$1458` | `$05` | `$5A02` | ground walker |
| `$C3DF` | `$1C3DF` | `9c 4f 48 14` | `$4F9C` | `$1448` | `$05` | `$5A02` | ground walker |
| `$C3E3` | `$1C3E3` | `a4 4f 04 40` | `$4FA4` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C3E7` | `$1C3E7` | `b0 4f 38 14` | `$4FB0` | `$1438` | `$05` | `$5A02` | ground walker |
| `$C3EB` | `$1C3EB` | `c0 4f 38 14` | `$4FC0` | `$1438` | `$05` | `$5A02` | ground walker |
| `$C3EF` | `$1C3EF` | `c0 4f 33 18` | `$4FC0` | `$1833` | `$06` | `$897E` | terrain-aware enemy |
| `$C3F3` | `$1C3F3` | `de 4f 38 14` | `$4FDE` | `$1438` | `$05` | `$5A02` | ground walker |
| `$C3F7` | `$1C3F7` | `e4 4f 04 40` | `$4FE4` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C3FB` | `$1C3FB` | `07 50 38 18` | `$5007` | `$1838` | `$06` | `$897E` | terrain-aware enemy |
| `$C3FF` | `$1C3FF` | `18 50 12 32` | `$5018` | `$3212` | `$0C` | `$5DC8` | patrol formation parent |
| `$C403` | `$1C403` | `24 50 55 14` | `$5024` | `$1455` | `$05` | `$5A02` | ground walker |
| `$C407` | `$1C407` | `38 50 02 33` | `$5038` | `$3302` | `$0C` | `$5DC8` | patrol formation parent |
| `$C40B` | `$1C40B` | `38 50 3e 18` | `$5038` | `$183E` | `$06` | `$897E` | terrain-aware enemy |
| `$C40F` | `$1C40F` | `4b 50 38 10` | `$504B` | `$1038` | `$04` | `$55E9` | terrain-bound enemy |
| `$C413` | `$1C413` | `4c 50 4f 18` | `$504C` | `$184F` | `$06` | `$897E` | terrain-aware enemy |
| `$C417` | `$1C417` | `64 50 05 40` | `$5064` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C41B` | `$1C41B` | `6a 50 53 18` | `$506A` | `$1853` | `$06` | `$897E` | terrain-aware enemy |
| `$C41F` | `$1C41F` | `74 50 56 18` | `$5074` | `$1856` | `$06` | `$897E` | terrain-aware enemy |
| `$C423` | `$1C423` | `87 50 54 18` | `$5087` | `$1854` | `$06` | `$897E` | terrain-aware enemy |
| `$C427` | `$1C427` | `14 51 08 54` | `$5114` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C42B` | `$1C42B` | `24 51 05 40` | `$5124` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C42F` | `$1C42F` | `44 51 08 54` | `$5144` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C433` | `$1C433` | `49 51 64 6c` | `$5149` | `$6C64` | `$1B` | `$596D` | red scripted flyer |
| `$C437` | `$1C437` | `5a 51 46 6c` | `$515A` | `$6C46` | `$1B` | `$596D` | red scripted flyer |
| `$C43B` | `$1C43B` | `64 51 04 40` | `$5164` | `$4004` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C43F` | `$1C43F` | `64 51 05 40` | `$5164` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C443` | `$1C443` | `6a 51 08 54` | `$516A` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C447` | `$1C447` | `7b 51 46 6c` | `$517B` | `$6C46` | `$1B` | `$596D` | red scripted flyer |
| `$C44B` | `$1C44B` | `88 51 04 6c` | `$5188` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$C44F` | `$1C44F` | `8a 51 08 54` | `$518A` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C453` | `$1C453` | `91 51 47 6c` | `$5191` | `$6C47` | `$1B` | `$596D` | red scripted flyer |
| `$C457` | `$1C457` | `98 51 83 6c` | `$5198` | `$6C83` | `$1B` | `$596D` | red scripted flyer |
| `$C45B` | `$1C45B` | `a4 51 05 6c` | `$51A4` | `$6C05` | `$1B` | `$596D` | red scripted flyer |
| `$C45F` | `$1C45F` | `a4 51 05 40` | `$51A4` | `$4005` | `$10` | `$8C12` | timed random stage-control object $DFFF/$8C2E |
| `$C463` | `$1C463` | `b3 51 06 6c` | `$51B3` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$C467` | `$1C467` | `be 51 04 6c` | `$51BE` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$C46B` | `$1C46B` | `c4 51 08 54` | `$51C4` | `$5408` | `$15` | `$74B4` | large terrain enemy |
| `$C46F` | `$1C46F` | `d7 51 53 6c` | `$51D7` | `$6C53` | `$1B` | `$596D` | red scripted flyer |
| `$C473` | `$1C473` | `db 51 54 10` | `$51DB` | `$1054` | `$04` | `$55E9` | terrain-bound enemy |
| `$C477` | `$1C477` | `eb 51 07 6c` | `$51EB` | `$6C07` | `$1B` | `$596D` | red scripted flyer |
| `$C47B` | `$1C47B` | `f4 51 75 6c` | `$51F4` | `$6C75` | `$1B` | `$596D` | red scripted flyer |
| `$C47F` | `$1C47F` | `fd 51 04 6c` | `$51FD` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$C483` | `$1C483` | `80 49 00 6c` | `$4980` | `$6C00` | `$1B` | `$596D` | red scripted flyer |
| `$C487` | `$1C487` | `80 49 00 6c` | `$4980` | `$6C00` | `$1B` | `$596D` | red scripted flyer |
| `$C48B` | `$1C48B` | `25 52 73 6c` | `$5225` | `$6C73` | `$1B` | `$596D` | red scripted flyer |
| `$C48F` | `$1C48F` | `2c 52 54 6c` | `$522C` | `$6C54` | `$1B` | `$596D` | red scripted flyer |
| `$C493` | `$1C493` | `3a 52 06 6c` | `$523A` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$C497` | `$1C497` | `44 52 74 6c` | `$5244` | `$6C74` | `$1B` | `$596D` | red scripted flyer |
| `$C49B` | `$1C49B` | `50 52 00 a8` | `$5250` | `$A800` | `$2A` | `$B7FB` | stage object $A200/$B805 |
| `$C49F` | `$1C49F` | `50 52 37 6c` | `$5250` | `$6C37` | `$1B` | `$596D` | red scripted flyer |
| `$C4A3` | `$1C4A3` | `5a 52 42 6c` | `$525A` | `$6C42` | `$1B` | `$596D` | red scripted flyer |
| `$C4A7` | `$1C4A7` | `61 52 04 6c` | `$5261` | `$6C04` | `$1B` | `$596D` | red scripted flyer |
| `$C4AB` | `$1C4AB` | `6f 52 45 6c` | `$526F` | `$6C45` | `$1B` | `$596D` | red scripted flyer |
| `$C4AF` | `$1C4AF` | `74 52 57 6c` | `$5274` | `$6C57` | `$1B` | `$596D` | red scripted flyer |
| `$C4B3` | `$1C4B3` | `7e 52 03 6c` | `$527E` | `$6C03` | `$1B` | `$596D` | red scripted flyer |
| `$C4B7` | `$1C4B7` | `8a 52 06 6c` | `$528A` | `$6C06` | `$1B` | `$596D` | red scripted flyer |
| `$C4BB` | `$1C4BB` | `94 52 53 6c` | `$5294` | `$6C53` | `$1B` | `$596D` | red scripted flyer |
| `$C4BF` | `$1C4BF` | `9d 52 54 6c` | `$529D` | `$6C54` | `$1B` | `$596D` | red scripted flyer |
| `$C4C3` | `$1C4C3` | `a7 52 65 6c` | `$52A7` | `$6C65` | `$1B` | `$596D` | red scripted flyer |
| `$C4C7` | `$1C4C7` | `b1 52 02 6c` | `$52B1` | `$6C02` | `$1B` | `$596D` | red scripted flyer |
| `$C4CB` | `$1C4CB` | `bd 52 56 6c` | `$52BD` | `$6C56` | `$1B` | `$596D` | red scripted flyer |
| `$C4CF` | `$1C4CF` | `c7 52 4c 15` | `$52C7` | `$154C` | `$05` | `$5A02` | ground walker |
| `$C4D3` | `$1C4D3` | `cb 52 66 6c` | `$52CB` | `$6C66` | `$1B` | `$596D` | red scripted flyer |
| `$C4D7` | `$1C4D7` | `d5 52 43 6c` | `$52D5` | `$6C43` | `$1B` | `$596D` | red scripted flyer |
| `$C4DB` | `$1C4DB` | `e0 52 00 9c` | `$52E0` | `$9C00` | `$27` | `$F366` | stage transition control |
| `$C4DF` | `$1C4DF` | `ec 52 55 6c` | `$52EC` | `$6C55` | `$1B` | `$596D` | red scripted flyer |
| `$C4E3` | `$1C4E3` | `f1 52 68 6c` | `$52F1` | `$6C68` | `$1B` | `$596D` | red scripted flyer |
| `$C4E7` | `$1C4E7` | `f6 52 24 6c` | `$52F6` | `$6C24` | `$1B` | `$596D` | red scripted flyer |
| `$C4EB` | `$1C4EB` | `00 53 42 6c` | `$5300` | `$6C42` | `$1B` | `$596D` | red scripted flyer |
| `$C4EF` | `$1C4EF` | `06 53 55 6c` | `$5306` | `$6C55` | `$1B` | `$596D` | red scripted flyer |
| `$C4F3` | `$1C4F3` | `0b 53 57 6c` | `$530B` | `$6C57` | `$1B` | `$596D` | red scripted flyer |
| `$C4F7` | `$1C4F7` | `18 53 55 6c` | `$5318` | `$6C55` | `$1B` | `$596D` | red scripted flyer |
| `$C4FB` | `$1C4FB` | `22 53 63 6c` | `$5322` | `$6C63` | `$1B` | `$596D` | red scripted flyer |
| `$C4FF` | `$1C4FF` | `2c 53 16 6c` | `$532C` | `$6C16` | `$1B` | `$596D` | red scripted flyer |
| `$C503` | `$1C503` | `36 53 64 6c` | `$5336` | `$6C64` | `$1B` | `$596D` | red scripted flyer |
| `$C507` | `$1C507` | `3b 53 43 6c` | `$533B` | `$6C43` | `$1B` | `$596D` | red scripted flyer |
| `$C50B` | `$1C50B` | `44 53 06 94` | `$5344` | `$9406` | `$25` | `$80E3` | player-targeting enemy |
| `$C50F` | `$1C50F` | `c4 53 00 68` | `$53C4` | `$6800` | `$1A` | `$5596` | boss arena collision-table setup |
| `$C513` | `$1C513` | `fe 53 00 a0` | `$53FE` | `$A000` | `$28` | `$F130` | stop all scroll velocities |
| `$C517` | `$1C517` | `00 54 0f 64` | `$5400` | `$640F` | `$19` | `$F01B` | next-stage init |

## Stage 8: `ES:$C51B..$C5DF`

| `$C51B` | `$1C51B` | `00 54 00 04` | `$5400` | `$0400` | `$01` | `$F461` | stage control |
| `$C51F` | `$1C51F` | `20 54 00 b0` | `$5420` | `$B000` | `$2C` | `$C0A9` | final-stage controller $C800/$C0CA |
| `$C523` | `$1C523` | `28 54 12 ac` | `$5428` | `$AC12` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C527` | `$1C527` | `37 54 01 ac` | `$5437` | `$AC01` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C52B` | `$1C52B` | `5a 54 13 ac` | `$545A` | `$AC13` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C52F` | `$1C52F` | `78 54 00 ac` | `$5478` | `$AC00` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C533` | `$1C533` | `82 54 10 ac` | `$5482` | `$AC10` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C537` | `$1C537` | `85 54 14 10` | `$5485` | `$1014` | `$04` | `$55E9` | terrain-bound enemy |
| `$C53B` | `$1C53B` | `96 54 05 ac` | `$5496` | `$AC05` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C53F` | `$1C53F` | `a0 54 36 10` | `$54A0` | `$1036` | `$04` | `$55E9` | terrain-bound enemy |
| `$C543` | `$1C543` | `dc 54 12 ac` | `$54DC` | `$AC12` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C547` | `$1C547` | `fa 54 01 ac` | `$54FA` | `$AC01` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C54B` | `$1C54B` | `2c 55 15 ac` | `$552C` | `$AC15` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C54F` | `$1C54F` | `68 55 02 ac` | `$5568` | `$AC02` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C553` | `$1C553` | `a4 55 33 10` | `$55A4` | `$1033` | `$04` | `$55E9` | terrain-bound enemy |
| `$C557` | `$1C557` | `e0 55 13 ac` | `$55E0` | `$AC13` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C55B` | `$1C55B` | `f4 55 01 ac` | `$55F4` | `$AC01` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C55F` | `$1C55F` | `80 56 04 ac` | `$5680` | `$AC04` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C563` | `$1C563` | `94 56 11 ac` | `$5694` | `$AC11` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C567` | `$1C567` | `bc 56 05 ac` | `$56BC` | `$AC05` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C56B` | `$1C56B` | `70 57 12 ac` | `$5770` | `$AC12` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C56F` | `$1C56F` | `98 57 00 ac` | `$5798` | `$AC00` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C573` | `$1C573` | `06 58 13 ac` | `$5806` | `$AC13` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C577` | `$1C577` | `10 58 05 ac` | `$5810` | `$AC05` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C57B` | `$1C57B` | `1a 58 13 ac` | `$581A` | `$AC13` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C57F` | `$1C57F` | `2e 58 05 ac` | `$582E` | `$AC05` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C583` | `$1C583` | `4c 58 07 10` | `$584C` | `$1007` | `$04` | `$55E9` | terrain-bound enemy |
| `$C587` | `$1C587` | `4c 58 16 ac` | `$584C` | `$AC16` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C58B` | `$1C58B` | `7e 58 02 ac` | `$587E` | `$AC02` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C58F` | `$1C58F` | `88 58 44 10` | `$5888` | `$1044` | `$04` | `$55E9` | terrain-bound enemy |
| `$C593` | `$1C593` | `92 58 11 ac` | `$5892` | `$AC11` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C597` | `$1C597` | `b0 58 03 ac` | `$58B0` | `$AC03` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C59B` | `$1C59B` | `f6 58 14 ac` | `$58F6` | `$AC14` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C59F` | `$1C59F` | `14 59 02 ac` | `$5914` | `$AC02` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C5A3` | `$1C5A3` | `28 59 11 ac` | `$5928` | `$AC11` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C5A7` | `$1C5A7` | `32 59 03 ac` | `$5932` | `$AC03` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C5AB` | `$1C5AB` | `46 59 14 ac` | `$5946` | `$AC14` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C5AF` | `$1C5AF` | `78 59 02 ac` | `$5978` | `$AC02` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C5B3` | `$1C5B3` | `8a 59 14 ac` | `$598A` | `$AC14` | `$2B` | `$9660` | enemy entry $2000/$9674 with $FA90/$FAA5 setup |
| `$C5B7` | `$1C5B7` | `f4 5a 03 84` | `$5AF4` | `$8403` | `$21` | `$E430` | stage resource owner |
| `$C5BB` | `$1C5BB` | `94 5b 00 b8` | `$5B94` | `$B800` | `$2E` | `$FB10` | six-object stage controller from ES:$945C |
| `$C5BF` | `$1C5BF` | `bc 5b 0a 80` | `$5BBC` | `$800A` | `$20` | `$FB9C` | stage resource/control event |
| `$C5C3` | `$1C5C3` | `bc 5b 0b 80` | `$5BBC` | `$800B` | `$20` | `$FB9C` | stage resource/control event |
| `$C5C7` | `$1C5C7` | `bc 5b 0c 80` | `$5BBC` | `$800C` | `$20` | `$FB9C` | stage resource/control event |
| `$C5CB` | `$1C5CB` | `bc 5b 0d 80` | `$5BBC` | `$800D` | `$20` | `$FB9C` | stage resource/control event |
| `$C5CF` | `$1C5CF` | `bc 5b 0e 80` | `$5BBC` | `$800E` | `$20` | `$FB9C` | stage resource/control event |
| `$C5D3` | `$1C5D3` | `bc 5b 0f 80` | `$5BBC` | `$800F` | `$20` | `$FB9C` | stage resource/control event |
| `$C5D7` | `$1C5D7` | `98 5c 00 bc` | `$5C98` | `$BC00` | `$2F` | `$EEAB` | final-stage object $0100/$EEB5 |
| `$C5DB` | `$1C5DB` | `d4 5c 00 c0` | `$5CD4` | `$C000` | `$30` | `$EE0B` | final-stage scroll/state reset object $0200/$EE3C |
| `$C5DF` | `$1C5DF` | `ff ff 00 00` | `$FFFF` | `$0000` | `$00` | `$F0F3` | stage speed/config |
