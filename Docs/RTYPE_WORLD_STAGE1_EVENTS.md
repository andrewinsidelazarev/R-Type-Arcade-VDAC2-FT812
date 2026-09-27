# R-Type World — Stage 1 event stream

Сгенерировано `Source/Tools/m72_stage_event_map.py` напрямую из World ROM.
Запись имеет вид `threshold word, command word`. Процедура `$1BA7`
сравнивает threshold с `RAM:$2F4B`, затем вычисляет offset обработчика
как `((CH >> 1) & $7E)` в таблице `ES:$B92D`.

MAME frames в таблице отсутствуют намеренно: trigger — progression ROM,
а не номер кадра.

| ES | File | HEX | Threshold | Command | Opcode | Handler | Смысл |
|---:|---:|---|---:|---:|---:|---:|---|
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
