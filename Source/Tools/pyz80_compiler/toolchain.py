"""Закреплённый вызов SDCC и преобразование результата в страницу TS-Conf."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import CompileError, Diagnostic
from .manifest import TargetSpec


@dataclass(frozen=True)
class ToolchainResult:
    binary: bytes
    assembly: str
    map_text: str
    symbols: dict[str, int]
    command: tuple[str, ...]
    version: str
    executable_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def locate_sdcc(target: TargetSpec) -> Path:
    candidates: list[Path] = []
    override = os.environ.get("PYZ80_SDCC")
    if override:
        candidates.append(Path(override))
    candidates.extend((
        Path("E:/zx/sdcc/bin/sdcc.exe"),
        Path("C:/Program Files/SDCC/bin/sdcc.exe"),
    ))
    found = next((path for path in candidates if path.is_file()), None)
    if found is None:
        raise CompileError(Diagnostic(
            "PZ5001", "SDCC не найден; задайте PYZ80_SDCC"))
    actual_hash = _sha256(found)
    if actual_hash != target.toolchain_sha256:
        raise CompileError(Diagnostic(
            "PZ5002",
            f"хеш SDCC {actual_hash} не совпал с {target.toolchain_sha256}",
        ))
    completed = subprocess.run(
        [str(found), "--version"], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace")
    version = completed.stdout.strip()
    if completed.returncode or target.toolchain_version not in version:
        raise CompileError(Diagnostic(
            "PZ5003", f"неожиданная версия SDCC: {version}"))
    return found


def _run(command: list[str], cwd: Path, *, tool_directory: Path | None = None) -> str:
    environment = os.environ.copy()
    if tool_directory is not None:
        environment["PATH"] = str(tool_directory) + os.pathsep + environment.get("PATH", "")
    completed = subprocess.run(
        command, cwd=cwd, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", env=environment)
    if completed.returncode:
        raise CompileError(Diagnostic(
            "PZ5004",
            "ошибка toolchain:\n" + completed.stdout.rstrip(),
        ))
    return completed.stdout


def _parse_map(text: str) -> dict[str, int]:
    symbols: dict[str, int] = {}
    # ASlink map печатает адрес либо первым, либо вторым hex-полем строки.
    patterns = (
        re.compile(r"^\s*([0-9A-Fa-f]{4,8})\s+(_[A-Za-z][A-Za-z0-9_]*)(?:\s+.*)?$"),
        re.compile(r"^\s*_[A-Za-z][A-Za-z0-9_]*\s+([0-9A-Fa-f]{4,8})(?:\s+.*)?$"),
    )
    for line in text.splitlines():
        first = patterns[0].match(line)
        if first:
            symbols[first.group(2)] = int(first.group(1), 16)
            continue
        second = patterns[1].match(line)
        if second:
            name = line.split()[0]
            symbols[name] = int(second.group(1), 16)
    return symbols


def compile_c(
        source: str, target: TargetSpec, directory: Path,
        support_files: tuple[tuple[str, str], ...] = (),
        ) -> ToolchainResult:
    if target.cpu.lower() != "z80" or target.backend != "sdcc-c":
        raise CompileError(Diagnostic(
            "PZ5005", f"backend {target.backend}/{target.cpu} не поддержан"))
    directory = directory.resolve()
    sdcc = locate_sdcc(target)
    makebin = sdcc.with_name("makebin.exe")
    if not makebin.is_file():
        raise CompileError(Diagnostic("PZ5006", "makebin.exe не найден рядом с SDCC"))
    directory.mkdir(parents=True, exist_ok=False)
    source_path = directory / "compiled.c"
    source_path.write_text(source, encoding="utf-8", newline="\n")
    support_c_names: list[str] = []
    for name, contents in support_files:
        support_path = directory / name
        if support_path.name != name or support_path.suffix not in (".c", ".h"):
            raise CompileError(Diagnostic(
                "PZ5009", f"неверное имя support C-файла {name!r}"))
        support_path.write_text(contents, encoding="utf-8", newline="\n")
        if support_path.suffix == ".c":
            support_c_names.append(name)
    output_ihx = directory / "compiled.ihx"
    compile_options = [
        "-mz80", "--std-c11",
        "--sdcccall", "1", "--fno-omit-frame-pointer", "--stack-auto",
        "--opt-code-speed", "--no-c-code-in-asm",
    ]
    compile_commands: list[list[str]] = []
    for name in (source_path.name, *support_c_names):
        command = [str(sdcc), *compile_options, "-c", name]
        _run(command, directory, tool_directory=sdcc.parent)
        compile_commands.append(command)
    object_names = [
        str(Path(name).with_suffix(".rel"))
        for name in (source_path.name, *support_c_names)
    ]
    link_command = [
        str(sdcc), "-mz80", "--no-std-crt0", "--sdcccall", "1",
        "--out-fmt-ihx",
        "--code-loc", f"0x{target.origin:04X}",
        "--data-loc", f"0x{target.origin + target.bank_size - 0x0800:04X}",
        "-o", output_ihx.name, *object_names,
    ]
    _run(link_command, directory, tool_directory=sdcc.parent)
    output_bin = directory / "compiled.bin"
    _run([
        str(makebin), "-s", str(target.origin + target.bank_size),
        "-o", str(target.origin),
        output_ihx.name, output_bin.name,
    ], directory, tool_directory=sdcc.parent)
    if not output_bin.is_file():
        raise CompileError(Diagnostic("PZ5007", "makebin не создал binary"))
    binary = output_bin.read_bytes()
    if len(binary) != target.bank_size:
        raise CompileError(Diagnostic(
            "PZ5008", f"binary имеет размер {len(binary)}, ожидалось {target.bank_size}"))
    assembly_path = directory / "compiled.asm"
    map_path = directory / "compiled.map"
    assembly_parts = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(directory.glob("*.asm"))
    ]
    assembly = "\n".join(assembly_parts)
    map_text = map_path.read_text(encoding="utf-8", errors="replace")
    return ToolchainResult(
        binary=binary,
        assembly=assembly,
        map_text=map_text,
        symbols=_parse_map(map_text),
        command=tuple(
            item
            for index, command in enumerate((*compile_commands, link_command))
            for item in (("&&",) if index else ()) + tuple(command[1:])
        ),
        version=target.toolchain_version,
        executable_sha256=_sha256(sdcc),
    )
