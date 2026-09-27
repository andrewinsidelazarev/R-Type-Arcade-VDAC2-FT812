; Автоматически создано Source/Tools/m72_fixed_player_tables.py.
; Все значения буквально извлечены из World ROM; runtime их не строит.

RTypeForceHitboxTable:
                DEFW #0004, #0004, #0004, #0004 ; ES:$15C6
                DEFW #0004, #0004, #0004, #0004 ; ES:$15C6
                DEFW #0007, #0007, #0007, #0007 ; ES:$15CE
                DEFW #000C, #000C, #000C, #000C ; ES:$15D6

RTypeForceLevel1AttachedDescriptors:
                DEFW #14EA, #14F0, #14F6, #14FC, #1502, #1508

RTypeForceLevel1ReturnDescriptors:
                DEFW #1508, #1502, #14FC, #14F6, #14F0, #14EA

RTypeForceLevel2UpBehindDescriptors:
                DEFW #150E, #1514, #151A, #1520, #1526, #152C

RTypeForceLevel2DownBehindDescriptors:
                DEFW #152C, #1526, #1520, #151A, #1514, #150E

RTypeForceLevel2UpFrontDescriptors:
                DEFW #1532, #1538, #153E, #1544, #154A, #1550

RTypeForceLevel2DownFrontDescriptors:
                DEFW #1550, #154A, #1544, #153E, #1538, #1532

RTypeForceLevel3DetachedFrontDescriptors:
                DEFW #1586, #158C, #1592, #1598

RTypeForceLevel3DetachedBehindDescriptors:
                DEFW #156E, #1568, #1562, #155C

; direction 0…15, затем animation 0…3.
RTypeForceLevel3DirectionDescriptors:
                DEFW #156E, #1580, #157A, #1574 ; direction #00, group 0
                DEFW #1586, #158C, #1592, #1598 ; direction #01, group 2
                DEFW #1556, #1568, #1562, #155C ; direction #02, group 6
                DEFW #156E, #1580, #157A, #1574 ; direction #03, group 0
                DEFW #156E, #1574, #157A, #1580 ; direction #04, group 4
                DEFW #156E, #158C, #1592, #1598 ; direction #05, group 3
                DEFW #156E, #155C, #1562, #1568 ; direction #06, group 5
                DEFW #156E, #1580, #157A, #1574 ; direction #07, group 0
                DEFW #156E, #1580, #157A, #1574 ; direction #08, group 8
                DEFW #156E, #1598, #1592, #158C ; direction #09, group 1
                DEFW #156E, #1568, #1562, #155C ; direction #0A, group 7
                DEFW #156E, #1580, #157A, #1574 ; direction #0B, group 0
                DEFW #156E, #1580, #157A, #1574 ; direction #0C, group 0
                DEFW #156E, #1580, #157A, #1574 ; direction #0D, group 0
                DEFW #156E, #1580, #157A, #1574 ; direction #0E, group 0
                DEFW #156E, #1580, #157A, #1574 ; direction #0F, group 0

RTypeForceAttachedAnimationDelta:
                DEFB #01, #01, #FF, #01, #01, #01, #01, #01, #FF, #FF, #FF, #FF, #01, #01, #01, #01

; coarse strength 0…3, direction 0…15: signed X,Y.
RTypeBitsOffsetTable:
                DEFW #0000, #0000 ; coarse 0, direction #00
                DEFW #FFF0, #0000 ; coarse 0, direction #01
                DEFW #0010, #0000 ; coarse 0, direction #02
                DEFW #0000, #0000 ; coarse 0, direction #03
                DEFW #0000, #000E ; coarse 0, direction #04
                DEFW #FFF0, #000E ; coarse 0, direction #05
                DEFW #0010, #000E ; coarse 0, direction #06
                DEFW #0000, #0000 ; coarse 0, direction #07
                DEFW #0000, #FFF2 ; coarse 0, direction #08
                DEFW #FFF0, #FFF2 ; coarse 0, direction #09
                DEFW #0010, #FFF2 ; coarse 0, direction #0A
                DEFW #0000, #0000 ; coarse 0, direction #0B
                DEFW #0000, #0000 ; coarse 0, direction #0C
                DEFW #0000, #0000 ; coarse 0, direction #0D
                DEFW #0000, #0000 ; coarse 0, direction #0E
                DEFW #0000, #0000 ; coarse 0, direction #0F
                DEFW #0000, #0000 ; coarse 1, direction #00
                DEFW #FFE0, #0000 ; coarse 1, direction #01
                DEFW #0020, #0000 ; coarse 1, direction #02
                DEFW #0000, #0000 ; coarse 1, direction #03
                DEFW #0000, #001E ; coarse 1, direction #04
                DEFW #FFE0, #001E ; coarse 1, direction #05
                DEFW #0020, #001E ; coarse 1, direction #06
                DEFW #0000, #0000 ; coarse 1, direction #07
                DEFW #0000, #FFE2 ; coarse 1, direction #08
                DEFW #FFE0, #FFE2 ; coarse 1, direction #09
                DEFW #0020, #FFE2 ; coarse 1, direction #0A
                DEFW #0000, #0000 ; coarse 1, direction #0B
                DEFW #0000, #0000 ; coarse 1, direction #0C
                DEFW #0000, #0000 ; coarse 1, direction #0D
                DEFW #0000, #0000 ; coarse 1, direction #0E
                DEFW #0000, #0000 ; coarse 1, direction #0F
                DEFW #0000, #0000 ; coarse 2, direction #00
                DEFW #FFD0, #0000 ; coarse 2, direction #01
                DEFW #0030, #0000 ; coarse 2, direction #02
                DEFW #0000, #0000 ; coarse 2, direction #03
                DEFW #0000, #002E ; coarse 2, direction #04
                DEFW #FFD0, #002E ; coarse 2, direction #05
                DEFW #0030, #002E ; coarse 2, direction #06
                DEFW #0000, #0000 ; coarse 2, direction #07
                DEFW #0000, #FFD2 ; coarse 2, direction #08
                DEFW #FFD0, #FFD2 ; coarse 2, direction #09
                DEFW #0030, #FFD2 ; coarse 2, direction #0A
                DEFW #0000, #0000 ; coarse 2, direction #0B
                DEFW #0000, #0000 ; coarse 2, direction #0C
                DEFW #0000, #0000 ; coarse 2, direction #0D
                DEFW #0000, #0000 ; coarse 2, direction #0E
                DEFW #0000, #0000 ; coarse 2, direction #0F
                DEFW #0000, #0000 ; coarse 3, direction #00
                DEFW #FFC0, #0000 ; coarse 3, direction #01
                DEFW #0040, #0000 ; coarse 3, direction #02
                DEFW #0000, #0000 ; coarse 3, direction #03
                DEFW #0000, #003E ; coarse 3, direction #04
                DEFW #FFC0, #003E ; coarse 3, direction #05
                DEFW #0040, #003E ; coarse 3, direction #06
                DEFW #0000, #0000 ; coarse 3, direction #07
                DEFW #0000, #FFC2 ; coarse 3, direction #08
                DEFW #FFC0, #FFC2 ; coarse 3, direction #09
                DEFW #0040, #FFC2 ; coarse 3, direction #0A
                DEFW #0000, #0000 ; coarse 3, direction #0B
                DEFW #0000, #0000 ; coarse 3, direction #0C
                DEFW #0000, #0000 ; coarse 3, direction #0D
                DEFW #0000, #0000 ; coarse 3, direction #0E
                DEFW #0000, #0000 ; coarse 3, direction #0F

RTypeBit0SpeedTable:
                DEFW #0400, #0700, #0700, #0700, #0700, #0700, #0700, #0700
                DEFW #0800, #0800, #0800, #0800, #0800, #0800, #0900, #0900
                DEFW #0A00, #0A00, #0B00, #0B00, #0B00, #0C00, #0C00, #0D00
                DEFW #0C00, #0D00, #0D00, #0E00, #0E00, #0F00, #0F00, #0F00

RTypeBit1SpeedTable:
                DEFW #0400, #0700, #0700, #0700, #0700, #0700, #0700, #0700
                DEFW #0800, #0800, #0800, #0800, #0800, #0800, #0900, #0900
                DEFW #0A00, #0A00, #0B00, #0B00, #0B00, #0C00, #0C00, #0D00
                DEFW #0C00, #0D00, #0D00, #0E00, #0E00, #0F00, #0F00, #0F00
