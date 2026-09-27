#!/usr/bin/env python3
"""Host-only contract test for the isolated resident FT812 fragment bridge.

No SPG is assembled or executed here.  The model checks the two invariants that
are easy to lose in an emulator-only test: the sdcccall(0) return-gate stack
layout and an atomic READY -> CONSUMING -> FREE queue transfer whose FIFO chunks
preserve the exact byte order across the end of a physical TS page.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASM = ROOT / "Source" / "ASM" / "pyz80_ft812_fragment_bridge.asm"
MAIN_ASM = ROOT / "Source" / "ASM" / "main.asm"
SPGBLD = ROOT / "spgbld_rtype.ini"
HEADER = ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.h"
C_SOURCE = ROOT / "Source" / "C" / "ft812" / "pyz80_ft812.c"

QUEUE_HEADER = struct.Struct("<HBBHHHHBBBB")
QUEUE_BYTES = 0x4000
HEADER_BYTES = QUEUE_HEADER.size
PAYLOAD_OFFSET = HEADER_BYTES
MAGIC = 0x4651
FORMAT = 3
PAGE_A = 0xED
PAGE_B = 0xEE
STAGING_PAGE = 0x06
C_PAGE = 0xF0
FREE = 0
BUILDING = 1
READY = 2
CONSUMING = 3
FULL = 0
FRAGMENT = 1
FIFO_USABLE = 0x0FFC
PAYLOAD_MAX = QUEUE_BYTES - HEADER_BYTES
DL_WORD_LIMIT = 2048


def _number(text: str) -> int:
    text = text.strip().rstrip("uUlL")
    if text.startswith("#"):
        return int(text[1:], 16)
    return int(text, 0)


def _asm_equates(source: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, raw in re.findall(
            r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\s+EQU\s+([^;\r\n]+)", source):
        raw = raw.strip()
        if re.fullmatch(r"(?:#(?:[0-9A-Fa-f]+)|0x[0-9A-Fa-f]+|[0-9]+)", raw):
            result[name] = _number(raw)
    return result


def _c_macro(source: str, name: str) -> int:
    match = re.search(
        rf"(?m)^#define\s+{re.escape(name)}\s+([^\s/]+)", source)
    if not match:
        raise AssertionError(f"missing C macro {name}")
    return _number(match.group(1))


def _c_enum(source: str, name: str) -> int:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([^,\s]+)", source)
    if not match:
        raise AssertionError(f"missing C enum value {name}")
    return _number(match.group(1))


def _header_bytes(page: int, sequence: int, payload: bytes, *,
                  state: int = READY, kind: int = FRAGMENT,
                  overflow: int = 0, reserved: int = 0,
                  dl_words: int | None = None) -> bytes:
    if len(payload) & 3:
        raise ValueError("fragment payload must be dword aligned")
    if dl_words is None:
        dl_words = min(len(payload) // 4, DL_WORD_LIMIT)
    return QUEUE_HEADER.pack(
        MAGIC, FORMAT, page, sequence, len(payload) // 4, len(payload),
        dl_words, state, overflow, kind, reserved)


@dataclass
class FragmentPage:
    page: int
    memory: bytearray
    state_trace: list[int]

    @classmethod
    def ready(cls, page: int, sequence: int, payload: bytes, **changes: int
              ) -> "FragmentPage":
        memory = bytearray(QUEUE_BYTES)
        memory[:HEADER_BYTES] = _header_bytes(
            page, sequence, payload,
            state=changes.get("state", READY),
            kind=changes.get("kind", FRAGMENT),
            overflow=changes.get("overflow", 0),
            reserved=changes.get("reserved", 0),
            dl_words=changes.get("dl_words"),
        )
        memory[PAYLOAD_OFFSET:PAYLOAD_OFFSET + len(payload)] = payload
        return cls(page, memory, [memory[12]])

    @property
    def state(self) -> int:
        return self.memory[12]

    @state.setter
    def state(self, value: int) -> None:
        self.memory[12] = value
        self.state_trace.append(value)


class FragmentBridgeModel:
    """Behavioral model of the resident bridge, not an FT812 renderer."""

    def __init__(self, *, page2: int = 0x29, page3: int = 0x37,
                 sp: int = 0x4EC0, ix: int = 0xA55A) -> None:
        self.pages = {2: page2, 3: page3}
        self.sp = sp
        self.ix = ix
        self.busy = False
        self.stream = bytearray()
        self.chunks: list[tuple[str, int, int, bytes]] = []

    def call_c0(self, page: int, target: int, args: bytes,
                producer: object) -> tuple[int, int]:
        """Model tail-JP gate; returns (status, scalar DEHL surrogate)."""
        if page not in (PAGE_A, PAGE_B):
            return 3, 0
        if not 0x8000 <= target < 0xC000:
            return 4, 0
        if self.busy:
            return 2, 0
        self.busy = True
        old_pages = dict(self.pages)
        old_ix = self.ix
        entry_sp = self.sp
        original_return = 0x5A5A
        gate = 0x6B6B
        stack = bytearray(2 + len(args))
        struct.pack_into("<H", stack, 0, original_return)
        stack[2:] = args

        # The bridge overwrites, rather than pushes, the target's return word.
        struct.pack_into("<H", stack, 0, gate)
        self.pages[2] = C_PAGE
        self.pages[3] = page
        seen: dict[str, object] = {
            "return": struct.unpack_from("<H", stack, 0)[0],
            "args": bytes(stack[2:]),
            "pages": dict(self.pages),
            "sp": self.sp,
        }
        result = int(producer(seen))  # type: ignore[operator]

        # Target RET consumes the gate.  The resident gate restores everything
        # and its own RET consumes the original wrapper return.
        self.sp += 2
        self.pages = old_pages
        self.ix = old_ix
        struct.pack_into("<H", stack, 0, original_return)
        self.sp = entry_sp + 2
        self.busy = False
        if stack[2:] != args:
            raise AssertionError("return gate modified caller-owned arguments")
        return 0, result

    def consume(self, queue: FragmentPage, staging: bytes,
                fifo_spaces: list[int], *,
                fail_after_queue_chunks: int | None = None) -> int:
        if queue.page not in (PAGE_A, PAGE_B):
            return 3
        if self.busy:
            return 2
        self.busy = True
        old_pages = dict(self.pages)
        old_sp = self.sp
        old_ix = self.ix
        status = 0
        claimed = False
        try:
            self.pages[3] = queue.page
            if queue.state != READY:
                return 1
            values = QUEUE_HEADER.unpack_from(queue.memory)
            (magic, fmt, header_page, sequence, count, payload_bytes,
             dl_words, state, overflow, kind, reserved) = values
            valid = (
                magic == MAGIC and fmt == FORMAT and header_page == queue.page
                and state == READY and overflow == 0 and kind == FRAGMENT
                and reserved == 0 and count <= PAYLOAD_MAX // 4
                and payload_bytes == count * 4
                and payload_bytes <= PAYLOAD_MAX
                and dl_words <= DL_WORD_LIMIT
            )
            if not valid:
                return 5

            queue.state = CONSUMING
            claimed = True
            payload = bytes(
                queue.memory[PAYLOAD_OFFSET:PAYLOAD_OFFSET + payload_bytes])
            self.pages[3] = old_pages[3]
            self.pages[2] = STAGING_PAGE

            # Existing staging is earlier in the already-open command stream.
            if staging:
                if len(staging) & 3 or len(staging) > FIFO_USABLE:
                    return 6
                self.stream.extend(staging)
                self.chunks.append(("staging", STAGING_PAGE, 0x3200, staging))

            sent = 0
            queue_chunks = 0
            polls = 0
            spaces = iter(fifo_spaces)
            while sent < len(payload):
                if (fail_after_queue_chunks is not None
                        and queue_chunks >= fail_after_queue_chunks):
                    return 7
                free = next(spaces, FIFO_USABLE) & ~3
                polls += 1
                if polls > 100_000:
                    return 7
                if free == 0:
                    continue
                length = min(len(payload) - sent, free, FIFO_USABLE)
                length &= ~3
                if length == 0:
                    continue
                data = payload[sent:sent + length]
                physical_offset = PAYLOAD_OFFSET + sent
                if physical_offset + length > QUEUE_BYTES:
                    raise AssertionError("DMA crossed the queue physical page")
                self.stream.extend(data)
                self.chunks.append(
                    ("queue", queue.page, physical_offset, data))
                sent += length
                queue_chunks += 1

            self.pages[3] = queue.page
            if queue.state != CONSUMING:
                return 8
            queue.state = FREE
            claimed = False
            return status
        finally:
            # A claimed transfer that returned early stays poisoned CONSUMING;
            # invalid/unready pages were never claimed and keep their state.
            if claimed and queue.state != CONSUMING:
                raise AssertionError("post-claim failure released queue")
            self.pages = old_pages
            self.sp = old_sp
            self.ix = old_ix
            self.busy = False


def check_static_contract() -> None:
    asm = ASM.read_text(encoding="utf-8")
    header = HEADER.read_text(encoding="utf-8")
    c_source = C_SOURCE.read_text(encoding="utf-8")
    main_asm = MAIN_ASM.read_text(encoding="utf-8")
    spgbld = SPGBLD.read_text(encoding="utf-8")
    equ = _asm_equates(asm)
    generated_equ = _asm_equates(
        (ROOT / "Source" / "ASM" /
         "generated_python_compiled_symbols.inc").read_text(encoding="utf-8"))
    expected = {
        "RTYPE_PYFT_C_PAGE": generated_equ["RTYPE_PY_CODE_BANK0_PAGE"],
        "RTYPE_PYFT_QUEUE_PAGE_A": _c_macro(
            header, "PYZ80_FT_QUEUE_PAGE_A"),
        "RTYPE_PYFT_QUEUE_PAGE_B": _c_macro(
            header, "PYZ80_FT_QUEUE_PAGE_B"),
        "RTYPE_PYFTQ_FORMAT": _c_macro(header, "PYZ80_FT_QUEUE_FORMAT"),
        "RTYPE_PYFTQ_HEADER_BYTES": HEADER_BYTES,
        "RTYPE_PYFTQ_MAGIC": _c_macro(c_source, "PYZ80_FT_QUEUE_MAGIC"),
        "RTYPE_PYFTQ_KIND_FULL": _c_enum(
            header, "PYZ80_FT_QUEUE_FULL"),
        "RTYPE_PYFTQ_KIND_FRAGMENT": _c_enum(
            header, "PYZ80_FT_QUEUE_FRAGMENT"),
        "RTYPE_PYFTQ_FREE": _c_enum(header, "PYZ80_FT_QUEUE_FREE"),
        "RTYPE_PYFTQ_BUILDING": _c_enum(
            header, "PYZ80_FT_QUEUE_BUILDING"),
        "RTYPE_PYFTQ_READY": _c_enum(header, "PYZ80_FT_QUEUE_READY"),
        "RTYPE_PYFTQ_CONSUMING": _c_enum(
            header, "PYZ80_FT_QUEUE_CONSUMING"),
    }
    for name, value in expected.items():
        if equ.get(name) != value:
            raise AssertionError(
                f"ASM/C fragment ABI mismatch: {name}={equ.get(name)!r}, "
                f"expected {value}")
    main_equ = _asm_equates(main_asm)
    if equ["RTYPE_PYFT_STAGING_PAGE"] != main_equ["CorePage"] + 1:
        raise AssertionError("bridge staging page is not resident CorePage+1")

    offsets = {
        "MAGIC": 0, "FORMAT": 2, "PAGE": 3, "SEQUENCE": 4,
        "COUNT": 6, "PAYLOAD": 8, "DL_WORDS": 10, "STATE": 12,
        "OVERFLOW": 13, "KIND": 14, "RESERVED": 15,
    }
    for suffix, value in offsets.items():
        name = f"RTYPE_PYFTQ_OFF_{suffix}"
        if equ.get(name) != value:
            raise AssertionError(f"bad {name}: {equ.get(name)!r} != {value}")

    struct_match = re.search(
        r"typedef struct PyZ80FtQueueHeader\s*\{(.*?)\}\s*PyZ80FtQueueHeader",
        header, re.S)
    if not struct_match:
        raise AssertionError("missing PyZ80FtQueueHeader")
    fields = re.findall(
        r"uint(?:8|16)_t\s+([A-Za-z_][A-Za-z0-9_]*)\s*;",
        struct_match.group(1))
    if fields != [
            "magic", "format", "page", "frame_sequence", "count",
            "payload_bytes", "dl_words", "state", "overflow", "kind",
            "reserved"]:
        raise AssertionError(f"queue header field order changed: {fields}")

    code = "\n".join(line.split(";", 1)[0] for line in asm.splitlines())
    for required in (
            "RTypePyFTFragment_CallC0:",
            "RTypePyFTFragment_ReturnGate:",
            "RTypePyFTFragment_ConsumeReady:",
            "CALL FT.Coprocessor.FlushChunk",
            "CALL RTypeFT_CmdWritePageDMA"):
        if required not in code:
            raise AssertionError(f"bridge lost required operation: {required}")
    for forbidden in (
            "FT_CMD_Start", "FT_DL_Start", "FT_Display", "FT_CMD_Swap",
            "FT_CMD_DLSTART", "FT_CMD_SWAP"):
        if re.search(rf"\b{re.escape(forbidden)}\b", code):
            raise AssertionError(f"fragment bridge inserted lifecycle op {forbidden}")

    # The bridge is resident but deliberately not live: main.asm may contain
    # exactly one isolated page-0 placement/include/SAVEBIN section, and the
    # packer may contain exactly one matching block.  Neither fact is a render
    # hook.  Executable CALL/JP references from start/render/game remain banned.
    main_code_lines = [
        " ".join(line.split(";", 1)[0].split()).lower()
        for line in main_asm.splitlines()
        if line.split(";", 1)[0].strip()
    ]
    placement = [
        "slot 0",
        "page tslibpage",
        "org #0500",
        "rtypepyftfragmentresident_start:",
        'include "pyz80_ft812_fragment_bridge.asm"',
        "rtypepyftfragmentresident_end:",
        "assert rtypepyftfragmentresident_start = #0500",
        "assert rtypepyftfragmentresident_end <= #1000",
        ('savebin "build/pyz80_ft812_fragment_bridge.bin", '
         'rtypepyftfragmentresident_start, '
         'rtypepyftfragmentresident_end - '
         'rtypepyftfragmentresident_start'),
    ]
    placement_hits = sum(
        main_code_lines[index:index + len(placement)] == placement
        for index in range(len(main_code_lines) - len(placement) + 1)
    )
    if placement_hits != 1:
        raise AssertionError(
            "bridge must have exactly one isolated #0500..#0FFF page-0 "
            "include/SAVEBIN section in main.asm")
    if main_asm.lower().count(ASM.name.lower()) != 1:
        raise AssertionError("bridge include must occur exactly once in main.asm")
    if main_asm.lower().count(
            "build/pyz80_ft812_fragment_bridge.bin") != 1:
        raise AssertionError("bridge SAVEBIN must occur exactly once in main.asm")

    packer_code = "\n".join(
        line.split(";", 1)[0] for line in spgbld.splitlines())
    block_pattern = re.compile(
        r"(?im)^\s*Block\s*=\s*#0500\s*,\s*#00\s*,\s*"
        r"Build[\\/]pyz80_ft812_fragment_bridge\.bin\s*$")
    if len(block_pattern.findall(packer_code)) != 1:
        raise AssertionError(
            "packer must contain exactly one bridge Block at #0500/page #00")
    if spgbld.lower().count(
            "build/pyz80_ft812_fragment_bridge.bin") != 1:
        raise AssertionError("bridge block must occur exactly once in packer")

    control_flow = re.compile(
        r"(?im)^\s*(?:CALL|JP)\s+"
        r"(?:(?:NZ|Z|NC|C|PO|PE|P|M)\s*,\s*)?"
        r"RTypePyFTFragment_(?:CallC0|ConsumeReady)\b")
    hook_owners = (
        MAIN_ASM,
        ROOT / "Source" / "ASM" / "render.asm",
        ROOT / "Source" / "ASM" / "generated_python_gameplay.asm",
        ROOT / "Source" / "ASM" / "arcade_game.asm",
    )
    for owner in hook_owners:
        owner_code = "\n".join(
            line.split(";", 1)[0]
            for line in owner.read_text(encoding="utf-8").splitlines())
        if control_flow.search(owner_code):
            raise AssertionError(
                f"isolated bridge entrypoint was hooked from {owner.name}")
        if owner != MAIN_ASM and ASM.name.lower() in owner_code.lower():
            raise AssertionError(
                f"isolated bridge was included by {owner.name}")

    acquire = c_source[
        c_source.index("uint8_t PyZ80FT_QueueAcquireFragment"):]
    acquire = acquire[:acquire.index("uint8_t PyZ80FT_QueuePushCommand")]
    commit = c_source[
        c_source.index("uint8_t PyZ80FT_QueueCommitFragment"):]
    if "PYZ80_FT_CMD_DLSTART" in acquire:
        raise AssertionError("fragment acquire inserted CMD_DLSTART")
    if "PYZ80_FT_CMD_SWAP" in commit or "PYZ80_FT_DL_DISPLAY" in commit:
        raise AssertionError("fragment commit inserted DISPLAY/SWAP")
    if commit.index("payload_bytes") > commit.index("PYZ80_FT_QUEUE_READY"):
        raise AssertionError("READY is not the final fragment publication store")


def check_return_gate() -> None:
    model = FragmentBridgeModel(page2=STAGING_PAGE, page3=0x44)
    args = struct.pack("<HHH", 0xC000, 0x1234, 0xBEEF)

    def producer(seen: dict[str, object]) -> int:
        assert seen["return"] == 0x6B6B
        assert seen["args"] == args
        assert seen["pages"] == {2: C_PAGE, 3: PAGE_A}
        assert seen["sp"] == 0x4EC0
        return 0x89ABCDEF

    status, result = model.call_c0(PAGE_A, 0x8A00, args, producer)
    assert (status, result) == (0, 0x89ABCDEF)
    assert model.pages == {2: STAGING_PAGE, 3: 0x44}
    assert model.sp == 0x4EC2 and model.ix == 0xA55A

    model.busy = True
    nested_called = False

    def nested(_: dict[str, object]) -> int:
        nonlocal nested_called
        nested_called = True
        return 0

    status, _ = model.call_c0(PAGE_A, 0x8000, b"", nested)
    assert status == 2 and not nested_called
    model.busy = False


def check_atomic_chunking_and_order() -> tuple[int, int]:
    staging = struct.pack("<III", 0x11111111, 0x22222222, 0x33333333)
    payload = b"".join(struct.pack("<I", 0x40000000 | index)
                       for index in range(1537))
    queue = FragmentPage.ready(PAGE_A, 0x1234, payload, dl_words=1537)
    model = FragmentBridgeModel(page2=0x19, page3=0x27)
    original = (dict(model.pages), model.sp, model.ix)
    status = model.consume(
        queue, staging, [0, 12, FIFO_USABLE, 8, 2048, 4, FIFO_USABLE])
    assert status == 0
    assert queue.state_trace == [READY, CONSUMING, FREE]
    assert model.stream == staging + payload
    assert (model.pages, model.sp, model.ix) == original
    assert model.chunks[0] == ("staging", STAGING_PAGE, 0x3200, staging)
    queue_chunks = [item for item in model.chunks if item[0] == "queue"]
    assert b"".join(item[3] for item in queue_chunks) == payload
    assert all(len(item[3]) % 4 == 0
               and 0 < len(item[3]) <= FIFO_USABLE
               for item in queue_chunks)
    expected_offset = PAYLOAD_OFFSET
    for _, page, offset, data in queue_chunks:
        assert page == PAGE_A and offset == expected_offset
        expected_offset += len(data)
    assert expected_offset == PAYLOAD_OFFSET + len(payload)
    return len(payload), len(queue_chunks)


def check_page_end_and_fail_closed() -> int:
    payload = b"".join(struct.pack("<I", index ^ 0xA5A55A5A)
                       for index in range(PAYLOAD_MAX // 4))
    queue = FragmentPage.ready(PAGE_B, 0xFFFF, payload, dl_words=DL_WORD_LIMIT)
    model = FragmentBridgeModel(page2=0x70, page3=0x71)
    before = (dict(model.pages), model.sp, model.ix)
    status = model.consume(queue, b"", [FIFO_USABLE] * 8)
    assert status == 0 and queue.state_trace == [READY, CONSUMING, FREE]
    assert model.stream == payload
    assert (model.pages, model.sp, model.ix) == before
    queue_chunks = [item for item in model.chunks if item[0] == "queue"]
    assert queue_chunks[-1][2] + len(queue_chunks[-1][3]) == QUEUE_BYTES

    invalid = FragmentPage.ready(PAGE_A, 7, b"\x01\x02\x03\x04", kind=FULL)
    invalid_model = FragmentBridgeModel(page2=0x33, page3=0x34)
    invalid_before = dict(invalid_model.pages)
    assert invalid_model.consume(invalid, b"", [FIFO_USABLE]) == 5
    assert invalid.state_trace == [READY] and invalid.state == READY
    assert invalid_model.pages == invalid_before and not invalid_model.stream

    partial = FragmentPage.ready(PAGE_A, 8, payload[:8192], dl_words=2048)
    partial_model = FragmentBridgeModel(page2=0x45, page3=0x46)
    partial_before = (dict(partial_model.pages), partial_model.sp,
                      partial_model.ix)
    assert partial_model.consume(
        partial, b"", [1024, 1024], fail_after_queue_chunks=1) == 7
    assert partial.state_trace == [READY, CONSUMING]
    assert partial.state == CONSUMING
    assert len(partial_model.stream) == 1024
    assert (partial_model.pages, partial_model.sp,
            partial_model.ix) == partial_before
    return len(queue_chunks)


def main() -> int:
    check_static_contract()
    check_return_gate()
    payload_bytes, chunks = check_atomic_chunking_and_order()
    max_chunks = check_page_end_and_fail_closed()
    print(
        "FT812 fragment bridge: ABI format 3; sdcccall(0) gate keeps arg0 at "
        "SP+2; READY->CONSUMING->FREE atomic; staging+payload order exact; "
        f"{payload_bytes} bytes/{chunks} variable FIFO chunks; max page in "
        f"{max_chunks} chunks; MMU/SP/IX restored; post-claim fault poisoned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
