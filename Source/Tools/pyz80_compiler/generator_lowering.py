"""Понижение проверенного тела генератора для next()/send(None).

Это не реализация вызова-фабрики, throw или yield from. Исходная сигнатура
остаётся generator-frame: обычный ABI не имеет права вызывать тело как функцию.
"""
from __future__ import annotations

from .lambda_lowering import _hash


def lower_generator_next_bodies(functions, units):
    lowered, pending = [], []
    for unit in units:
        signature = unit.get("meta", {}).get("signature", {})
        if unit["kind"] != 1 or signature.get("execution_kind") != "generator-frame":
            continue
        identity = functions[unit["owner"]]["callable_id"]
        frame = signature.get("frame", {})
        states = frame.get("states", [])
        blocks = unit["blocks"]
        # Нельзя терять обработчики исключений, finally или делегирование.
        if (signature.get("async") is not False or signature.get("source_yield_from_count") != 0 or
                frame.get("format") != "pyz80.generator-frame.v1" or
                frame.get("bounded_by_source_ast") is not True or
                unit["meta"].get("blockers") or
                any(b.get("exception_target") is not None for b in blocks) or
                any(s.get("suspension_kind") != "yield" or s.get("finalizer_stack") or
                    s.get("exception_target") is not None or s.get("operand_stack_slots") != 0 or
                    s.get("bounded_by_source_ast") is not True for s in states)):
            pending.append(identity)
            continue
        descriptors = {s["state"]: s for s in states}
        if len(descriptors) != len(states) or len(states) != signature.get("source_suspension_count"):
            raise ValueError("generator state identity/count mismatch")
        by_name = {b["name"]: b for b in blocks}
        if (unit["entry"] not in by_name or not by_name[unit["entry"]]["instructions"] or
                by_name[unit["entry"]]["instructions"][0]["op"] != "generator-frame-enter"):
            raise ValueError("generator guard must precede body execution")
        for state in states:
            resume = by_name.get(state["resume_target"], {}).get("instructions", [])
            if ([i["op"] for i in resume[:2]] != ["generator-restore-frame", "generator-resume-value"] or
                    any(b["terminator"]["op"] != "suspend-yield" for b in blocks
                        if state["resume_target"] in b["terminator"]["targets"])):
                raise ValueError("generator resume ordering mismatch")
        saves, restores, resumes, entered, yields = [], [], [], 0, []
        for block in blocks:
            for item in block["instructions"]:
                op, args = item["op"], item["arguments"]
                if op == "generator-frame-enter":
                    entered += 1
                    if args != [frame["local_slots"]] or block["name"] != unit["entry"]:
                        raise ValueError("generator entry/local slots mismatch")
                elif op in ("generator-save-frame", "generator-restore-frame"):
                    if len(args) != 2 or args[0] not in descriptors or args[1] != descriptors[args[0]]:
                        raise ValueError("generator frame descriptor mismatch")
                    (saves if op == "generator-save-frame" else restores).append(args[0])
                    if op == "generator-restore-frame" and descriptors[args[0]]["resume_target"] != block["name"]:
                        raise ValueError("generator restore block mismatch")
                elif op == "generator-resume-value":
                    if len(args) != 1 or args[0] not in descriptors or descriptors[args[0]]["resume_target"] != block["name"]:
                        raise ValueError("generator resume value mismatch")
                    resumes.append(args[0])
                elif op.startswith("generator-"):
                    raise ValueError("unsupported generator instruction in sealed next body")
            term = block["terminator"]
            if term["op"] == "suspend-yield":
                args = term["arguments"]
                if (len(args) != 2 or args[1] not in descriptors or
                        term["targets"] != [descriptors[args[1]]["resume_target"]] or
                        term["targets"][0] not in by_name or not block["instructions"] or
                        block["instructions"][-1]["op"] != "generator-save-frame" or
                        block["instructions"][-1]["arguments"][0] != args[1]):
                    raise ValueError("generator suspension edge mismatch")
                yields.append(args[1])
            elif term["op"] not in ("jump", "branch-truth", "generator-return"):
                pending.append(identity)
                break
        else:
            ordered = sorted(descriptors)
            if entered != 1 or any(sorted(seq) != ordered for seq in (saves, restores, resumes, yields)):
                raise ValueError("generator save/restore coverage mismatch")
            seal = _hash({"signature": signature, "blocks": blocks})
            for block in blocks:
                rewritten = []
                for item in block["instructions"]:
                    op = item["op"]
                    if op == "generator-frame-enter":
                        item.update(op="generator-next-enter", arguments=[],
                            attributes={"generator_next_body_sha256": seal})
                    elif op in ("generator-save-frame", "generator-restore-frame"):
                        if item.get("destination") is not None:
                            raise ValueError("unexpected generator save/restore value")
                        continue
                    elif op == "generator-resume-value":
                        item.update(op="constant", arguments=[None], value_kind="py-none",
                            attributes={"generator_next_body_sha256": seal})
                    rewritten.append(item)
                block["instructions"] = rewritten
                term = block["terminator"]
                if term["op"] == "suspend-yield":
                    term.update(op="vm-yield-next", arguments=term["arguments"][:1],
                        attributes={"generator_next_body_sha256": seal})
                elif term["op"] == "generator-return":
                    term["op"] = "return"
            lowered.append({"callable_id": identity, "source_body_sha256": seal,
                            "states": len(states), "protocol": "next/send-none"})
            unit["meta"]["generator_next_body_sha256"] = seal
    seals = {row["callable_id"]:row["source_body_sha256"] for row in lowered}
    for unit in units:
        for block in unit["blocks"]:
            for item in block["instructions"]:
                attrs = item.get("attributes", {})
                if item["op"] in ("make-source-function", "make-source-function-defaults") and attrs.get("source_callable_id") in seals:
                    attrs["generator_next_body_sha256"] = seals[attrs["source_callable_id"]]
    return {"bodies": lowered, "pending": pending,
            "factory_call_binding_available": True,
            "required_provider": "PyZ80Target_AttachGenerators",
            "throw_send_value_delegation_complete": False}
