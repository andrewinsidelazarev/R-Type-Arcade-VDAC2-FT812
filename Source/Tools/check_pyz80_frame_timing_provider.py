#!/usr/bin/env python3
"""Generate or validate the source-derived FT812 frame-timing contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from pyz80_compiler.frame_timing_provider import (
    DEFAULT_INCLUDE,
    DEFAULT_MANIFEST,
    DEFAULT_STATUS,
    FrameTimingProviderError,
    analyze_frame_timing_provider,
    render_frame_timing_include,
    render_frame_timing_manifest,
    validate_frame_timing_provider_report,
)


ROOT = Path(__file__).resolve().parents[2]


def probe(project_root: Path | str = ROOT) -> dict[str, Any]:
    """Analyze current sources without requiring generated files to exist yet."""
    root = Path(project_root).resolve()
    report = analyze_frame_timing_provider(root)
    validate_frame_timing_provider_report(
        root, report, validate_artifacts=False)
    return report


def validate_report(project_root: Path | str,
                    report: Mapping[str, Any], *,
                    validate_artifacts: bool = True) -> None:
    validate_frame_timing_provider_report(
        Path(project_root).resolve(), report,
        validate_artifacts=validate_artifacts)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-pyz80")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def write_generated_contract(project_root: Path | str,
                             report: Mapping[str, Any], *,
                             status_path: Path | str | None = None,
                             manifest_path: Path | str | None = None,
                             include_path: Path | str | None = None) -> None:
    """Write generated consumers first and the validating status last."""
    root = Path(project_root).resolve()
    include = Path(include_path) if include_path is not None else root / DEFAULT_INCLUDE
    manifest = (Path(manifest_path) if manifest_path is not None
                else root / DEFAULT_MANIFEST)
    status = Path(status_path) if status_path is not None else root / DEFAULT_STATUS
    expected_include = (root / Path(
        str(report["generated_artifacts"]["include"]["path"]))).resolve()
    expected_manifest = (root / Path(
        str(report["generated_artifacts"]["manifest"]["path"]))).resolve()
    if (include.resolve() != expected_include or
            manifest.resolve() != expected_manifest):
        raise FrameTimingProviderError(
            "PZFTP424",
            "generated include/manifest paths are fixed by the timing ABI")
    _atomic_write_bytes(
        include, render_frame_timing_include(report).encode("utf-8"))
    _atomic_write_bytes(
        manifest, render_frame_timing_manifest(report).encode("utf-8"))
    validate_report(root, report, validate_artifacts=True)
    status_bytes = (json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8")
    _atomic_write_bytes(status, status_bytes)


def _load_status(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrameTimingProviderError(
            "PZFTP421", f"timing status unavailable {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FrameTimingProviderError(
            "PZFTP422", "timing status root is not an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--include", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    status_path = args.status or root / DEFAULT_STATUS
    manifest_path = args.manifest or root / DEFAULT_MANIFEST
    include_path = args.include or root / DEFAULT_INCLUDE
    try:
        if args.validate_only:
            report = _load_status(status_path)
            validate_report(root, report, validate_artifacts=True)
        else:
            report = probe(root)
            expected_artifacts = report["generated_artifacts"]
            if (Path(expected_artifacts["manifest"]["path"]) !=
                    Path(DEFAULT_MANIFEST) or
                    Path(expected_artifacts["include"]["path"]) !=
                    Path(DEFAULT_INCLUDE)):
                raise FrameTimingProviderError(
                    "PZFTP423", "report generated-artifact paths changed")
            if (args.manifest is not None and
                    manifest_path.resolve() != (root / DEFAULT_MANIFEST).resolve()) or (
                    args.include is not None and
                    include_path.resolve() != (root / DEFAULT_INCLUDE).resolve()):
                raise FrameTimingProviderError(
                    "PZFTP424",
                    "contract artifact paths are ABI-fixed; only --status may vary")
            write_generated_contract(
                root, report, status_path=status_path,
                manifest_path=manifest_path, include_path=include_path)
    except (FrameTimingProviderError, OSError, ValueError) as error:
        print(f"frame timing provider FAILED: {error}")
        return 1
    cadence = report["contract"]["actual_cadence"]
    selected = report["contract"]["selected_profile"]
    print(
        "frame timing provider: "
        f"VCYCLE={selected['registers']['FT_REG_VCYCLE']}, "
        f"refresh={cadence['refresh_hz']['decimal']} Hz, "
        f"error={cadence['relative_error_ppm']} ppm; "
        f"live={report['live']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
