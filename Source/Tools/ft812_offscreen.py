"""Безоконный вывод через bt8xxemu из патченного Unreal, без ввода пользователя.

ABI 12 взят из поставляемого с Unreal заголовка ft8xx/bt8xxemu.h.
Это диагностический провайдер ПК, не модель рендера и не часть игрового SPG.
"""
import ctypes as c
import hashlib
from pathlib import Path
import threading

from PIL import Image


Graphics = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p, c.c_int,
                      c.c_void_p, c.c_uint32, c.c_uint32, c.c_int)
Log = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_int, c.c_char_p)


class Parameters(c.Structure):
    _fields_ = [('Main', c.c_void_p), ('Flags', c.c_int), ('Mode', c.c_int),
                ('MousePressure', c.c_uint32), ('ExternalFrequency', c.c_uint32),
                ('ReduceGraphicsThreads', c.c_uint32), ('MCUSleep', c.c_void_p),
                ('RomFilePath', c.c_wchar * 260), ('OtpFilePath', c.c_wchar * 260),
                ('CoprocessorRomFilePath', c.c_wchar * 260), ('Graphics', Graphics),
                ('Log', Log), ('Close', c.c_void_p), ('UserContext', c.c_void_p),
                ('Flash', c.c_void_p)]


class FT812Offscreen:
    def __init__(self, library=Path('E:/zx/unreal_x64/bt8xxemu.dll')):
        self.library = Path(library)
        self.library_sha256 = hashlib.sha256(self.library.read_bytes()).hexdigest()
        self.dll = c.CDLL(str(self.library))
        signatures = {
            'version': (c.c_char_p, []),
            'defaults': (None, [c.c_uint32, c.POINTER(Parameters), c.c_int]),
            'run': (None, [c.c_uint32, c.POINTER(c.c_void_p), c.POINTER(Parameters)]),
            'destroy': (None, [c.c_void_p]),
            'chipSelect': (None, [c.c_void_p, c.c_int]),
            'transfer': (c.c_uint8, [c.c_void_p, c.c_uint8]),
        }
        for name, (result, arguments) in signatures.items():
            fn = getattr(self.dll, 'BT8XXEMU_' + name)
            fn.restype, fn.argtypes = result, arguments
            setattr(self, '_' + name, fn)
        self.version = self._version().decode('utf-8', errors='replace')
        self.ready = threading.Event()
        self.messages = []
        self.image = None
        self.swapped = False
        self.graphics = Graphics(self._graphics)
        self.log = Log(lambda sender, context, kind, text: self.messages.append(
            (kind, text.decode('utf-8', errors='replace'))))
        parameters = Parameters()
        self._defaults(12, c.byref(parameters), 0x812)
        parameters.Graphics = self.graphics
        parameters.Log = self.log
        # Только копроцессор и многопоточный рендер, без окна/ввода/ухудшения качества.
        parameters.Flags = 0x04 | 0x20
        self.handle = c.c_void_p()
        self._run(12, c.byref(self.handle), c.byref(parameters))
        if not self.handle:
            raise RuntimeError(('bt8xxemu не запустился', self.messages))
        self.command(0x44)
        self.command(0x61, 0xc8)
        self.command(0x00)
        self.write(0x302070, b'\0')
        # VM_1024_768_59Hz из TSLib и VCYCLE текущей демо (866).
        for address, value in ((0x30202c, 1344), (0x302030, 320), (0x302034, 1024),
                               (0x302038, 24), (0x30203c, 160), (0x302040, 866),
                               (0x302044, 37), (0x302048, 768),
                               (0x30204c, 2), (0x302050, 8)):
            self.write(address, value.to_bytes(2, 'little'))

    def _graphics(self, sender, context, output, buffer, width, height, flags):
        if flags & 8:
            self.swapped = True
        if output and buffer and flags & 2 and self.swapped:
            raw = c.string_at(buffer, width * height * 4)
            self.image = Image.frombytes('RGBA', (width, height), raw, 'raw', 'BGRA').convert('RGB')
            self.swapped = False
            self.ready.set()
        return 1

    def command(self, value, parameter=0):
        self._chipSelect(self.handle, 1)
        for byte in (value, parameter, 0):
            self._transfer(self.handle, byte)
        self._chipSelect(self.handle, 0)

    def write(self, address, data):
        self._chipSelect(self.handle, 1)
        for byte in ((address >> 16) | 0x80, (address >> 8) & 255, address & 255):
            self._transfer(self.handle, byte)
        for byte in data:
            self._transfer(self.handle, byte)
        self._chipSelect(self.handle, 0)

    def render(self, display_list):
        self.ready.clear()
        self.swapped = False
        self.write(0x300000, display_list)
        self.write(0x302054, b'\x02')
        self.write(0x302070, b'\x01')
        if not self.ready.wait(5):
            raise RuntimeError(('Нет полного кадра после DLSWAP', self.messages))
        return self.image.copy()

    def close(self):
        if self.handle:
            self._destroy(self.handle)
            self.handle = c.c_void_p()
