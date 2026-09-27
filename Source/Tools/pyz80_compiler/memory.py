"""Validated CPU/physical-memory contracts for banked TS-Config targets.

The Z80 sees a 64 KiB virtual address space while TS-Config provides 256
independently mapped 16 KiB physical pages.  Consequently, equal CPU VMA
ranges are normal for banks which are alive at different times, but equal
physical pages are not.  This module makes every such exception explicit:
an overlap is accepted only when both regions are members of one named
lifecycle overlay for the corresponding address domain.

The model is deliberately independent from the R-Type translator and from
any assembler syntax.  Other projects can use the same JSON format and
validator before their backend or packer writes an output file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .diagnostics import CompileError, Diagnostic


CPU_ADDRESS_SPACE = 0x10000
TS_PAGE_SIZE = 0x4000
TS_PHYSICAL_PAGE_COUNT = 0x100
MEMORY_LAYOUT_FORMAT = "pyz80-memory-layout-v1"

_OVERLAY_DOMAINS = frozenset(("vma", "physical"))


def _error(code: str, message: str) -> CompileError:
    return CompileError(Diagnostic(code, message))


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error("PZ1202", f"{field} должен быть целым числом")
    return value


@dataclass(frozen=True, order=True)
class VmaRange:
    """One half-open range in the Z80 CPU address space."""

    start: int
    end: int

    @classmethod
    def from_json(cls, data: Mapping[str, Any], field: str) -> "VmaRange":
        try:
            start = _integer(data["start"], f"{field}.start")
            end = _integer(data["end"], f"{field}.end")
        except KeyError as error:
            raise _error("PZ1202", f"{field} требует start и end") from error
        return cls(start, end)

    def overlaps(self, other: "VmaRange") -> bool:
        return self.start < other.end and other.start < self.end

    def intersection(self, other: "VmaRange") -> "VmaRange | None":
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return VmaRange(start, end) if start < end else None


@dataclass(frozen=True, order=True)
class PhysicalPageRange:
    """One inclusive range of 16 KiB TS physical page numbers."""

    first: int
    last: int

    @classmethod
    def from_json(
            cls, data: Mapping[str, Any], field: str) -> "PhysicalPageRange":
        try:
            first = _integer(data["first"], f"{field}.first")
            last = _integer(data["last"], f"{field}.last")
        except KeyError as error:
            raise _error("PZ1202", f"{field} требует first и last") from error
        return cls(first, last)

    def __iter__(self) -> Iterator[int]:
        return iter(range(self.first, self.last + 1))


@dataclass(frozen=True)
class MemoryRegion:
    """A named allocation with a CPU view and/or physical page ownership."""

    name: str
    purpose: str
    vma: VmaRange | None
    physical_pages: tuple[PhysicalPageRange, ...]

    @classmethod
    def from_json(cls, data: Mapping[str, Any], index: int) -> "MemoryRegion":
        name = str(data.get("name", "")).strip()
        purpose = str(data.get("purpose", "")).strip()
        raw_vma = data.get("vma")
        if raw_vma is not None and not isinstance(raw_vma, Mapping):
            raise _error("PZ1202", f"regions[{index}].vma должен быть object")
        vma = (VmaRange.from_json(raw_vma, f"regions[{index}].vma")
               if raw_vma is not None else None)
        raw_pages = data.get("physical_pages", ())
        if (isinstance(raw_pages, (str, bytes, Mapping)) or
                not isinstance(raw_pages, Iterable)):
            raise _error(
                "PZ1202",
                f"regions[{index}].physical_pages должен быть массивом",
            )
        pages: list[PhysicalPageRange] = []
        for page_index, item in enumerate(raw_pages):
            if not isinstance(item, Mapping):
                raise _error(
                    "PZ1202",
                    f"regions[{index}].physical_pages[{page_index}] "
                    "должен быть object",
                )
            pages.append(PhysicalPageRange.from_json(
                item, f"regions[{index}].physical_pages[{page_index}]"))
        return cls(name, purpose, vma, tuple(pages))

    def pages(self) -> Iterator[int]:
        for page_range in self.physical_pages:
            yield from page_range


@dataclass(frozen=True)
class LifecycleOverlay:
    """An explicit mutual-exclusion promise for one address domain."""

    name: str
    domain: str
    lifecycle: str
    members: frozenset[str]

    @classmethod
    def from_json(
            cls, data: Mapping[str, Any], index: int) -> "LifecycleOverlay":
        name = str(data.get("name", "")).strip()
        domain = str(data.get("domain", "")).strip()
        lifecycle = str(data.get("lifecycle", "")).strip()
        raw_members = data.get("members", ())
        if (isinstance(raw_members, (str, bytes, Mapping)) or
                not isinstance(raw_members, Iterable)):
            raise _error(
                "PZ1202",
                f"lifecycle_overlays[{index}].members должен быть массивом",
            )
        members = frozenset(str(item).strip() for item in raw_members)
        return cls(name, domain, lifecycle, members)


@dataclass(frozen=True)
class MemoryLayoutReport:
    """Immutable ownership index produced by successful validation."""

    region_names: tuple[str, ...]
    page_owners: tuple[tuple[str, ...], ...]
    vma_overlays: tuple[str, ...]
    physical_overlays: tuple[str, ...]

    @property
    def used_physical_pages(self) -> frozenset[int]:
        return frozenset(
            page for page, owners in enumerate(self.page_owners) if owners)

    @property
    def free_physical_pages(self) -> frozenset[int]:
        return frozenset(range(len(self.page_owners))) - self.used_physical_pages

    def owners_of_page(self, page: int) -> tuple[str, ...]:
        if not 0 <= page < len(self.page_owners):
            raise IndexError(f"physical page #{page:X} is outside the layout")
        return self.page_owners[page]


@dataclass(frozen=True)
class PhysicalAllocation:
    """One concrete pack/runtime allocation checked against a region owner."""

    name: str
    owner: str
    pages: tuple[int, ...]


@dataclass(frozen=True)
class PhysicalAllocationReport:
    """Deterministic page index for concrete allocations."""

    allocation_names: tuple[str, ...]
    page_allocations: tuple[tuple[str, ...], ...]

    @property
    def allocated_pages(self) -> frozenset[int]:
        return frozenset(
            page for page, names in enumerate(self.page_allocations) if names)


@dataclass(frozen=True)
class MemoryLayout:
    """Complete banked-memory manifest before validation."""

    format: str
    cpu_address_space: int
    physical_page_size: int
    physical_page_count: int
    regions: tuple[MemoryRegion, ...]
    lifecycle_overlays: tuple[LifecycleOverlay, ...]

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "MemoryLayout":
        raw_regions = data.get("regions", ())
        raw_overlays = data.get("lifecycle_overlays", ())
        if (isinstance(raw_regions, (str, bytes, Mapping)) or
                not isinstance(raw_regions, Iterable)):
            raise _error("PZ1202", "regions должен быть массивом")
        if (isinstance(raw_overlays, (str, bytes, Mapping)) or
                not isinstance(raw_overlays, Iterable)):
            raise _error("PZ1202", "lifecycle_overlays должен быть массивом")
        regions: list[MemoryRegion] = []
        for index, item in enumerate(raw_regions):
            if not isinstance(item, Mapping):
                raise _error("PZ1202", f"regions[{index}] должен быть object")
            regions.append(MemoryRegion.from_json(item, index))
        overlays: list[LifecycleOverlay] = []
        for index, item in enumerate(raw_overlays):
            if not isinstance(item, Mapping):
                raise _error(
                    "PZ1202",
                    f"lifecycle_overlays[{index}] должен быть object",
                )
            overlays.append(LifecycleOverlay.from_json(item, index))
        return cls(
            format=str(data.get("format", "")),
            cpu_address_space=_integer(
                data.get("cpu_address_space", CPU_ADDRESS_SPACE),
                "cpu_address_space",
            ),
            physical_page_size=_integer(
                data.get("physical_page_size", TS_PAGE_SIZE),
                "physical_page_size",
            ),
            physical_page_count=_integer(
                data.get("physical_page_count", TS_PHYSICAL_PAGE_COUNT),
                "physical_page_count",
            ),
            regions=tuple(regions),
            lifecycle_overlays=tuple(overlays),
        )

    @classmethod
    def load(cls, path: Path) -> "MemoryLayout":
        """Load and validate a manifest without executing project code."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise _error("PZ1200", f"не удалось прочитать memory manifest: {error}") from error
        if not isinstance(payload, Mapping):
            raise _error("PZ1202", "memory manifest должен быть JSON object")
        layout = cls.from_json(payload)
        layout.validate()
        return layout

    def validate(self) -> MemoryLayoutReport:
        return validate_memory_layout(self)

    def region(self, name: str) -> MemoryRegion:
        for region in self.regions:
            if region.name == name:
                return region
        raise KeyError(name)


def _validate_header(layout: MemoryLayout) -> None:
    if layout.format != MEMORY_LAYOUT_FORMAT:
        raise _error(
            "PZ1201",
            f"неподдерживаемый формат memory layout {layout.format!r}",
        )
    if layout.cpu_address_space != CPU_ADDRESS_SPACE:
        raise _error(
            "PZ1202",
            f"TS Z80 cpu_address_space должен быть {CPU_ADDRESS_SPACE}",
        )
    if layout.physical_page_size != TS_PAGE_SIZE:
        raise _error(
            "PZ1202",
            f"TS physical_page_size должен быть {TS_PAGE_SIZE}",
        )
    if layout.physical_page_count != TS_PHYSICAL_PAGE_COUNT:
        raise _error(
            "PZ1202",
            f"TS physical_page_count должен быть {TS_PHYSICAL_PAGE_COUNT}",
        )


def _validate_regions(layout: MemoryLayout) -> dict[str, MemoryRegion]:
    if not layout.regions:
        raise _error("PZ1203", "memory layout не содержит regions")
    by_name: dict[str, MemoryRegion] = {}
    for region in layout.regions:
        if not region.name:
            raise _error("PZ1203", "region требует непустое имя")
        if region.name in by_name:
            raise _error("PZ1203", f"повторное имя region {region.name!r}")
        if region.vma is None and not region.physical_pages:
            raise _error(
                "PZ1203",
                f"region {region.name!r} не содержит VMA или physical pages",
            )
        if region.vma is not None and not (
                0 <= region.vma.start < region.vma.end <=
                layout.cpu_address_space):
            raise _error(
                "PZ1204",
                f"region {region.name!r}: неверный CPU VMA "
                f"{region.vma.start:#x}..{region.vma.end:#x}",
            )
        seen_pages: set[int] = set()
        for page_range in region.physical_pages:
            if not (0 <= page_range.first <= page_range.last <
                    layout.physical_page_count):
                raise _error(
                    "PZ1205",
                    f"region {region.name!r}: неверный диапазон страниц "
                    f"#{page_range.first:02X}..#{page_range.last:02X}",
                )
            for page in page_range:
                if page in seen_pages:
                    raise _error(
                        "PZ1205",
                        f"region {region.name!r}: страница #{page:02X} "
                        "перечислена повторно",
                    )
                seen_pages.add(page)
        by_name[region.name] = region
    return by_name


def _validate_overlays(
        layout: MemoryLayout,
        regions: Mapping[str, MemoryRegion],
        ) -> dict[str, dict[str, str]]:
    names: set[str] = set()
    membership: dict[str, dict[str, str]] = {
        "vma": {},
        "physical": {},
    }
    for overlay in layout.lifecycle_overlays:
        if not overlay.name:
            raise _error("PZ1206", "lifecycle overlay требует непустое имя")
        if overlay.name in names:
            raise _error(
                "PZ1206", f"повторное имя lifecycle overlay {overlay.name!r}")
        names.add(overlay.name)
        if overlay.domain not in _OVERLAY_DOMAINS:
            raise _error(
                "PZ1207",
                f"overlay {overlay.name!r}: domain должен быть vma или physical",
            )
        if not overlay.lifecycle:
            raise _error(
                "PZ1207",
                f"overlay {overlay.name!r} требует явное описание lifecycle",
            )
        if len(overlay.members) < 2 or "" in overlay.members:
            raise _error(
                "PZ1207",
                f"overlay {overlay.name!r} должен содержать минимум два region",
            )
        unknown = sorted(overlay.members - regions.keys())
        if unknown:
            raise _error(
                "PZ1208",
                f"overlay {overlay.name!r} ссылается на неизвестные regions: "
                + ", ".join(unknown),
            )
        for member in sorted(overlay.members):
            region = regions[member]
            if overlay.domain == "vma" and region.vma is None:
                raise _error(
                    "PZ1208",
                    f"overlay {overlay.name!r}: region {member!r} не имеет VMA",
                )
            if overlay.domain == "physical" and not region.physical_pages:
                raise _error(
                    "PZ1208",
                    f"overlay {overlay.name!r}: region {member!r} не имеет pages",
                )
            previous = membership[overlay.domain].get(member)
            if previous is not None:
                raise _error(
                    "PZ1209",
                    f"region {member!r} состоит сразу в overlays {previous!r} "
                    f"и {overlay.name!r} domain={overlay.domain}",
                )
            membership[overlay.domain][member] = overlay.name
    return membership


def _approved(
        domain: str,
        first: str,
        second: str,
        membership: Mapping[str, Mapping[str, str]],
        ) -> bool:
    group = membership[domain].get(first)
    return group is not None and group == membership[domain].get(second)


def _validate_vma_overlaps(
        regions: tuple[MemoryRegion, ...],
        membership: Mapping[str, Mapping[str, str]],
        ) -> None:
    with_vma = tuple(region for region in regions if region.vma is not None)
    for index, first in enumerate(with_vma):
        assert first.vma is not None
        for second in with_vma[index + 1:]:
            assert second.vma is not None
            intersection = first.vma.intersection(second.vma)
            if intersection is None:
                continue
            if _approved("vma", first.name, second.name, membership):
                continue
            raise _error(
                "PZ1210",
                "неразрешённое пересечение CPU VMA "
                f"${intersection.start:04X}..${intersection.end - 1:04X}: "
                f"{first.name!r} и {second.name!r}; требуется общий "
                "именованный vma lifecycle overlay",
            )


def _physical_owners(
        layout: MemoryLayout,
        membership: Mapping[str, Mapping[str, str]],
        ) -> tuple[tuple[str, ...], ...]:
    owners: list[list[str]] = [
        [] for _ in range(layout.physical_page_count)
    ]
    for region in layout.regions:
        for page in region.pages():
            for previous in owners[page]:
                if not _approved(
                        "physical", previous, region.name, membership):
                    raise _error(
                        "PZ1211",
                        f"неразрешённое пересечение TS physical page "
                        f"#{page:02X}: {previous!r} и {region.name!r}; "
                        "требуется общий именованный physical lifecycle overlay",
                    )
            owners[page].append(region.name)
    return tuple(tuple(items) for items in owners)


def validate_memory_layout(layout: MemoryLayout) -> MemoryLayoutReport:
    """Validate all ranges and return deterministic ownership information."""
    _validate_header(layout)
    regions = _validate_regions(layout)
    membership = _validate_overlays(layout, regions)
    _validate_vma_overlaps(layout.regions, membership)
    owners = _physical_owners(layout, membership)
    return MemoryLayoutReport(
        region_names=tuple(region.name for region in layout.regions),
        page_owners=owners,
        vma_overlays=tuple(sorted(set(membership["vma"].values()))),
        physical_overlays=tuple(sorted(
            set(membership["physical"].values()))),
    )


def validate_physical_allocations(
        layout: MemoryLayout,
        allocations: Iterable[PhysicalAllocation],
        ) -> PhysicalAllocationReport:
    """Check concrete SPG/runtime pages against their declared owners.

    Regions reserve address space; allocations are the actual files or buffers
    placed there by a project packer.  Keeping these two layers separate lets a
    target reserve growth space while still detecting a single generated blob
    which escaped its reservation or collided with another blob.
    """
    layout.validate()
    regions = {region.name: region for region in layout.regions}
    names: set[str] = set()
    page_allocations: list[list[str]] = [
        [] for _ in range(layout.physical_page_count)
    ]
    ordered_names: list[str] = []
    for allocation in allocations:
        if not allocation.name:
            raise _error("PZ1212", "physical allocation требует непустое имя")
        if allocation.name in names:
            raise _error(
                "PZ1212",
                f"повторное имя physical allocation {allocation.name!r}",
            )
        names.add(allocation.name)
        ordered_names.append(allocation.name)
        region = regions.get(allocation.owner)
        if region is None:
            raise _error(
                "PZ1213",
                f"allocation {allocation.name!r} ссылается на неизвестный "
                f"region {allocation.owner!r}",
            )
        allowed_pages = frozenset(region.pages())
        seen_here: set[int] = set()
        for page in allocation.pages:
            if isinstance(page, bool) or not isinstance(page, int):
                raise _error(
                    "PZ1213",
                    f"allocation {allocation.name!r}: page должен быть целым",
                )
            if not 0 <= page < layout.physical_page_count:
                raise _error(
                    "PZ1213",
                    f"allocation {allocation.name!r}: page #{page:X} вне TS RAM",
                )
            if page in seen_here:
                raise _error(
                    "PZ1214",
                    f"allocation {allocation.name!r}: page #{page:02X} "
                    "перечислена повторно",
                )
            seen_here.add(page)
            if page not in allowed_pages:
                raise _error(
                    "PZ1213",
                    f"allocation {allocation.name!r}: page #{page:02X} "
                    f"не принадлежит region {allocation.owner!r}",
                )
            if page_allocations[page]:
                raise _error(
                    "PZ1214",
                    f"physical page #{page:02X} одновременно занята "
                    f"{page_allocations[page][0]!r} и {allocation.name!r}",
                )
            page_allocations[page].append(allocation.name)
    return PhysicalAllocationReport(
        allocation_names=tuple(ordered_names),
        page_allocations=tuple(tuple(names) for names in page_allocations),
    )


def load_memory_layout(path: Path) -> tuple[MemoryLayout, MemoryLayoutReport]:
    """Convenience API returning both the parsed manifest and its index."""
    layout = MemoryLayout.load(path)
    return layout, layout.validate()
