; Сгенерировано m72_sprite_assets.py; вручную не редактировать.
; Подлинные объекты M72: предварительные xBRZ6 + Lanczos, FT812 ARGB4444.
M72_SPR_BLOB_BASE      EQU $000000
M72_SPR_BLOB_SIZE      EQU 84572
M72_SPR_ASSET_COUNT    EQU 30
M72_SPRITE_REC_SIZE    EQU 20
M72SpriteTable:
                ; ассет 0: c0022_p0_32x16_f00 53x28
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $000000)
                DEFD $28000000
                DEFD $0730D41C
                DEFD $29000000
                DEFD $0800AA2D
                ; ассет 1: c0a23_p1_32x16_f00 52x30
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $000B98)
                DEFD $28000000
                DEFD $0730D01E
                DEFD $29000000
                DEFD $0800A830
                ; ассет 2: c0af4_p3_16x16_f00 7x7
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $0017C8)
                DEFD $28000000
                DEFD $07301C07
                DEFD $29000000
                DEFD $0800180C
                ; ассет 3: c0af3_p2_16x16_f00 7x9
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00182C)
                DEFD $28000000
                DEFD $07301C09
                DEFD $29000000
                DEFD $0800180F
                ; ассет 4: c0af6_p5_16x16_f00 7x7
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $0018AC)
                DEFD $28000000
                DEFD $07301C07
                DEFD $29000000
                DEFD $0800180C
                ; ассет 5: c0af3_p3_16x16_f00 7x9
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $001910)
                DEFD $28000000
                DEFD $07301C09
                DEFD $29000000
                DEFD $0800180F
                ; ассет 6: c0af7_p3_16x16_f00 9x11
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $001990)
                DEFD $28000000
                DEFD $0730240B
                DEFD $29000000
                DEFD $08001E12
                ; ассет 7: c0af7_p4_16x16_f00 9x11
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $001A58)
                DEFD $28000000
                DEFD $0730240B
                DEFD $29000000
                DEFD $08001E12
                ; ассет 8: c0af5_p5_16x16_f00 9x13
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $001B20)
                DEFD $28000000
                DEFD $0730240D
                DEFD $29000000
                DEFD $08001E15
                ; ассет 9: c0af4_p4_16x16_f00 7x7
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $001C0C)
                DEFD $28000000
                DEFD $07301C07
                DEFD $29000000
                DEFD $0800180C
                ; ассет 10: r9_pitch_0_exact 53x30
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $001C70)
                DEFD $28000000
                DEFD $0730D41E
                DEFD $29000000
                DEFD $0800AA30
                ; ассет 11: r9_pitch_1_exact 53x29
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $0028DC)
                DEFD $28000000
                DEFD $0730D41D
                DEFD $29000000
                DEFD $0800AA2F
                ; ассет 12: r9_pitch_2_exact 53x28
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $0034E0)
                DEFD $28000000
                DEFD $0730D41C
                DEFD $29000000
                DEFD $0800AA2D
                ; ассет 13: r9_pitch_3_exact 53x29
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $004078)
                DEFD $28000000
                DEFD $0730D41D
                DEFD $29000000
                DEFD $0800AA2F
                ; ассет 14: r9_pitch_4_exact 53x29
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $004C7C)
                DEFD $28000000
                DEFD $0730D41D
                DEFD $29000000
                DEFD $0800AA2F
                ; ассет 15: r9_launch_0a23_exact 52x30
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $005880)
                DEFD $28000000
                DEFD $0730D01E
                DEFD $29000000
                DEFD $0800A830
                ; ассет 16: r9_launch_0aa2_exact 53x60
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $0064B0)
                DEFD $28000000
                DEFD $0730D43C
                DEFD $29000000
                DEFD $0800AA60
                ; ассет 17: r9_launch_0aa4_exact 53x58
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $007D88)
                DEFD $28000000
                DEFD $0730D43A
                DEFD $29000000
                DEFD $0800AA5D
                ; ассет 18: r9_launch_0aa6_exact 53x52
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00958C)
                DEFD $28000000
                DEFD $0730D434
                DEFD $29000000
                DEFD $0800AA54
                ; ассет 19: stage1_patrol_c0132_p7 50x48
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00AB14)
                DEFD $28000000
                DEFD $0730C830
                DEFD $29000000
                DEFD $0800A04D
                ; ассет 20: stage1_red_c00f4_p5 40x50
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00BDD4)
                DEFD $28000000
                DEFD $0730A032
                DEFD $29000000
                DEFD $08008050
                ; ассет 21: stage1_red_flip_c0161_p5 40x29
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00CD74)
                DEFD $28000000
                DEFD $0730A01D
                DEFD $29000000
                DEFD $0800802F
                ; ассет 22: stage1_walker_c0100_p8 53x57
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00D684)
                DEFD $28000000
                DEFD $0730D439
                DEFD $29000000
                DEFD $0800AA5C
                ; ассет 23: c08f8_p0_16x16_f00 27x12
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00EE20)
                DEFD $28000000
                DEFD $07306C0C
                DEFD $29000000
                DEFD $08005814
                ; ассет 24: wave_0_p8_80x16 133x30
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $00F0A8)
                DEFD $28000000
                DEFD $0732141E
                DEFD $29000000
                DEFD $0801AA30
                ; ассет 25: wave_1_p8_80x16 133x30
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $010FD4)
                DEFD $28000000
                DEFD $0732141E
                DEFD $29000000
                DEFD $0801AA30
                ; ассет 26: wave_release_0_c0013_p8_16x16 27x30
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $012F00)
                DEFD $28000000
                DEFD $07306C1E
                DEFD $29000000
                DEFD $08005830
                ; ассет 27: wave_release_1_c0043_p8_32x16 41x24
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $013554)
                DEFD $28000000
                DEFD $0730A418
                DEFD $29000000
                DEFD $08008427
                ; ассет 28: wave_release_2_c0044_p8_32x16 51x20
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $013D04)
                DEFD $28000000
                DEFD $0730CC14
                DEFD $29000000
                DEFD $0800A420
                ; ассет 29: wave_release_3_c0045_p8_32x16 43x16
                DEFD $01000000 | (M72_SPR_BLOB_BASE + $0144FC)
                DEFD $28000000
                DEFD $0730AC10
                DEFD $29000000
                DEFD $08008A1A

; Ширина нужна только редкой точной обрезке launch-объекта у X<0.
M72SpriteLogicalWidthTable:
                DEFB 53, 52, 7, 7, 7, 7, 9, 9, 9, 7, 53, 53, 53, 53, 53, 52, 53, 53, 53, 50, 40, 40, 53, 27, 133, 133, 27, 41, 51, 43

; R-9: пять наклонов и четыре эффекта вылета взяты из готового Python-runtime.
; Эффект не является постоянным выхлопом: его выбирает только 226-кадровая таблица.
M72_R9_ASSET            EQU 12
M72_R9_PITCH_ASSET_COUNT EQU 5
M72R9PitchAssetTable:
                DEFB 10, 11, 12, 13, 14
M72R9PitchCropTopTable:
                DEFB 0, 1, 1, 1, 1
M72_R9_LAUNCH_ASSET_COUNT EQU 4
M72R9LaunchAssetTable:
                DEFB 15, 16, 17, 18
M72_R9_SHOT_ASSET       EQU 23
M72_R9_SHOT_DX_Q8       EQU 13653
M72_R9_SHOT_DY_Q8       EQU 3072
M72_R9_SHOT_VX_Q8       EQU 6827
M72_R9_WAVE_ASSET_A     EQU 24
M72_R9_WAVE_ASSET_B     EQU 25
M72_R9_WAVE_DX_Q8       EQU 6827
M72_R9_WAVE_DY_Q8       EQU 768
M72_R9_WAVE_VX_Q8       EQU 3413
M72_R9_WAVE_MIN_CHARGE  EQU 67
M72_R9_WAVE_DELAY       EQU 2
M72_R9_WAVE_RELEASE_0   EQU 26
M72_R9_WAVE_RELEASE_1   EQU 27
M72_R9_WAVE_RELEASE_2   EQU 28
M72_R9_WAVE_RELEASE_3   EQU 29
M72_R9_WAVE_RELEASE_DX_Q8 EQU 13653
M72_R9_WAVE_RELEASE_DY_Q8 EQU 768

; Противники Stage 1 взяты из MAME frame 1500 и декодированы из ROM.
M72_ENEMY_PATROL_ASSET EQU 19
M72_ENEMY_PATROL_W     EQU 50
M72_ENEMY_PATROL_H     EQU 48
M72_ENEMY_RED_ASSET EQU 20
M72_ENEMY_RED_W     EQU 40
M72_ENEMY_RED_H     EQU 50
M72_ENEMY_RED_FLIP_ASSET EQU 21
M72_ENEMY_RED_FLIP_W     EQU 40
M72_ENEMY_RED_FLIP_H     EQU 29
M72_ENEMY_WALKER_ASSET EQU 22
M72_ENEMY_WALKER_W     EQU 53
M72_ENEMY_WALKER_H     EQU 57

; Остальные захваченные объекты в точном порядке вывода MAME.
M72_SCENE_INSTANCE_REC_SIZE EQU 5
M72_SCENE_INSTANCE_COUNT EQU 25
M72SceneInstanceTable:
                DEFB 3  ; ОЗУ спрайтов $0D0
                DEFW $10DA
                DEFW $101A
                DEFB 3  ; ОЗУ спрайтов $0CC
                DEFW $115A
                DEFW $01F3
                DEFB 3  ; ОЗУ спрайтов $0C8
                DEFW $039A
                DEFW $0EDA
                DEFB 8  ; ОЗУ спрайтов $0C4
                DEFW $1573
                DEFW $0973
                DEFB 6  ; ОЗУ спрайтов $0C0
                DEFW $134D
                DEFW $05C0
                DEFB 9  ; ОЗУ спрайтов $0BC
                DEFW $00DA
                DEFW $03CD
                DEFB 3  ; ОЗУ спрайтов $0B8
                DEFW $1033
                DEFW $06CD
                DEFB 5  ; ОЗУ спрайтов $0B4
                DEFW $03DA
                DEFW $075A
                DEFB 3  ; ОЗУ спрайтов $0B0
                DEFW $055A
                DEFW $12CD
                DEFB 4  ; ОЗУ спрайтов $0AC
                DEFW $06CD
                DEFW $07DA
                DEFB 8  ; ОЗУ спрайтов $0A8
                DEFW $1873
                DEFW $12B3
                DEFB 3  ; ОЗУ спрайтов $0A4
                DEFW $09DA
                DEFW $0EDA
                DEFB 4  ; ОЗУ спрайтов $0A0
                DEFW $0B4D
                DEFW $050D
                DEFB 2  ; ОЗУ спрайтов $09C
                DEFW $185A
                DEFW $089A
                DEFB 7  ; ОЗУ спрайтов $098
                DEFW $1240
                DEFW $03CD
                DEFB 7  ; ОЗУ спрайтов $094
                DEFW $0FCD
                DEFW $04C0
                DEFB 6  ; ОЗУ спрайтов $090
                DEFW $17A6
                DEFW $0FB3
                DEFB 5  ; ОЗУ спрайтов $08C
                DEFW $1A5A
                DEFW $1300
                DEFB 3  ; ОЗУ спрайтов $088
                DEFW $145A
                DEFW $084D
                DEFB 5  ; ОЗУ спрайтов $084
                DEFW $15DA
                DEFW $089A
                DEFB 4  ; ОЗУ спрайтов $080
                DEFW $1C4D
                DEFW $01C0
                DEFB 3  ; ОЗУ спрайтов $07C
                DEFW $1B73
                DEFW $00B3
                DEFB 3  ; ОЗУ спрайтов $078
                DEFW $1CDA
                DEFW $089A
                DEFB 3  ; ОЗУ спрайтов $074
                DEFW $1BDA
                DEFW $01F3
                DEFB 2  ; ОЗУ спрайтов $070
                DEFW $1D8D
                DEFW $110D

; логический пиксель -> VERTEX2F для VERTEX_FORMAT 3 и физического x8/5.
M72LogicalToVertexTable:
                DEFW 0, 13, 26, 38, 51, 64, 77, 90
                DEFW 102, 115, 128, 141, 154, 166, 179, 192
                DEFW 205, 218, 230, 243, 256, 269, 282, 294
                DEFW 307, 320, 333, 346, 358, 371, 384, 397
                DEFW 410, 422, 435, 448, 461, 474, 486, 499
                DEFW 512, 525, 538, 550, 563, 576, 589, 602
                DEFW 614, 627, 640, 653, 666, 678, 691, 704
                DEFW 717, 730, 742, 755, 768, 781, 794, 806
                DEFW 819, 832, 845, 858, 870, 883, 896, 909
                DEFW 922, 934, 947, 960, 973, 986, 998, 1011
                DEFW 1024, 1037, 1050, 1062, 1075, 1088, 1101, 1114
                DEFW 1126, 1139, 1152, 1165, 1178, 1190, 1203, 1216
                DEFW 1229, 1242, 1254, 1267, 1280, 1293, 1306, 1318
                DEFW 1331, 1344, 1357, 1370, 1382, 1395, 1408, 1421
                DEFW 1434, 1446, 1459, 1472, 1485, 1498, 1510, 1523
                DEFW 1536, 1549, 1562, 1574, 1587, 1600, 1613, 1626
                DEFW 1638, 1651, 1664, 1677, 1690, 1702, 1715, 1728
                DEFW 1741, 1754, 1766, 1779, 1792, 1805, 1818, 1830
                DEFW 1843, 1856, 1869, 1882, 1894, 1907, 1920, 1933
                DEFW 1946, 1958, 1971, 1984, 1997, 2010, 2022, 2035
                DEFW 2048, 2061, 2074, 2086, 2099, 2112, 2125, 2138
                DEFW 2150, 2163, 2176, 2189, 2202, 2214, 2227, 2240
                DEFW 2253, 2266, 2278, 2291, 2304, 2317, 2330, 2342
                DEFW 2355, 2368, 2381, 2394, 2406, 2419, 2432, 2445
                DEFW 2458, 2470, 2483, 2496, 2509, 2522, 2534, 2547
                DEFW 2560, 2573, 2586, 2598, 2611, 2624, 2637, 2650
                DEFW 2662, 2675, 2688, 2701, 2714, 2726, 2739, 2752
                DEFW 2765, 2778, 2790, 2803, 2816, 2829, 2842, 2854
                DEFW 2867, 2880, 2893, 2906, 2918, 2931, 2944, 2957
                DEFW 2970, 2982, 2995, 3008, 3021, 3034, 3046, 3059
                DEFW 3072, 3085, 3098, 3110, 3123, 3136, 3149, 3162
                DEFW 3174, 3187, 3200, 3213, 3226, 3238, 3251, 3264
                DEFW 3277, 3290, 3302, 3315, 3328, 3341, 3354, 3366
                DEFW 3379, 3392, 3405, 3418, 3430, 3443, 3456, 3469
                DEFW 3482, 3494, 3507, 3520, 3533, 3546, 3558, 3571
                DEFW 3584, 3597, 3610, 3622, 3635, 3648, 3661, 3674
                DEFW 3686, 3699, 3712, 3725, 3738, 3750, 3763, 3776
                DEFW 3789, 3802, 3814, 3827, 3840, 3853, 3866, 3878
                DEFW 3891, 3904, 3917, 3930, 3942, 3955, 3968, 3981
                DEFW 3994, 4006, 4019, 4032, 4045, 4058, 4070, 4083
                DEFW 4096, 4109, 4122, 4134, 4147, 4160, 4173, 4186
                DEFW 4198, 4211, 4224, 4237, 4250, 4262, 4275, 4288
                DEFW 4301, 4314, 4326, 4339, 4352, 4365, 4378, 4390
                DEFW 4403, 4416, 4429, 4442, 4454, 4467, 4480, 4493
                DEFW 4506, 4518, 4531, 4544, 4557, 4570, 4582, 4595
                DEFW 4608, 4621, 4634, 4646, 4659, 4672, 4685, 4698
                DEFW 4710, 4723, 4736, 4749, 4762, 4774, 4787, 4800
                DEFW 4813, 4826, 4838, 4851, 4864, 4877, 4890, 4902
                DEFW 4915, 4928, 4941, 4954, 4966, 4979, 4992, 5005
                DEFW 5018, 5030, 5043, 5056, 5069, 5082, 5094, 5107
                DEFW 5120, 5133, 5146, 5158, 5171, 5184, 5197, 5210
                DEFW 5222, 5235, 5248, 5261, 5274, 5286, 5299, 5312
                DEFW 5325, 5338, 5350, 5363, 5376, 5389, 5402, 5414
                DEFW 5427, 5440, 5453, 5466, 5478, 5491, 5504, 5517
                DEFW 5530, 5542, 5555, 5568, 5581, 5594, 5606, 5619
                DEFW 5632, 5645, 5658, 5670, 5683, 5696, 5709, 5722
                DEFW 5734, 5747, 5760, 5773, 5786, 5798, 5811, 5824
                DEFW 5837, 5850, 5862, 5875, 5888, 5901, 5914, 5926
                DEFW 5939, 5952, 5965, 5978, 5990, 6003, 6016, 6029
                DEFW 6042, 6054, 6067, 6080, 6093, 6106, 6118, 6131
                DEFW 6144, 6157, 6170, 6182, 6195, 6208, 6221, 6234
                DEFW 6246, 6259, 6272, 6285, 6298, 6310, 6323, 6336
                DEFW 6349, 6362, 6374, 6387, 6400, 6413, 6426, 6438
                DEFW 6451, 6464, 6477, 6490, 6502, 6515, 6528, 6541
                DEFW 6554, 6566, 6579, 6592, 6605, 6618, 6630, 6643
                DEFW 6656, 6669, 6682, 6694, 6707, 6720, 6733, 6746
                DEFW 6758, 6771, 6784, 6797, 6810, 6822, 6835, 6848
                DEFW 6861, 6874, 6886, 6899, 6912, 6925, 6938, 6950
                DEFW 6963, 6976, 6989, 7002, 7014, 7027, 7040, 7053
                DEFW 7066, 7078, 7091, 7104, 7117, 7130, 7142, 7155
                DEFW 7168, 7181, 7194, 7206, 7219, 7232, 7245, 7258
                DEFW 7270, 7283, 7296, 7309, 7322, 7334, 7347, 7360
                DEFW 7373, 7386, 7398, 7411, 7424, 7437, 7450, 7462
                DEFW 7475, 7488, 7501, 7514, 7526, 7539, 7552, 7565
                DEFW 7578, 7590, 7603, 7616, 7629, 7642, 7654, 7667
                DEFW 7680, 7693, 7706, 7718, 7731, 7744, 7757, 7770
                DEFW 7782, 7795, 7808, 7821, 7834, 7846, 7859, 7872
                DEFW 7885, 7898, 7910, 7923, 7936, 7949, 7962, 7974
                DEFW 7987, 8000, 8013, 8026, 8038, 8051, 8064, 8077
                DEFW 8090, 8102, 8115, 8128, 8141, 8154, 8166, 8179
                DEFW 8192
