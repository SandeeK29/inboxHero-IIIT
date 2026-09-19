# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Triage Engine for Project inboxHero (Part 2 / Capability R1)
Coordinates Rule-based (0 tokens) and Model-based (Ollama / Gemini) triage to zero the inbox.
Outputs decisions.json and appends cap=R1 trace events to trace.jsonl.
"""

import json
from typing import List, Tuple
from pathlib import Path

from config import INBOX_FILE, DECISIONS_FILE, TRACE_FILE
from schemas import Message, Decision, TraceEvent
from rules import evaluate_rules
from llm_client import LLMClient


def append_trace_event(event: TraceEvent):
    """Appends a structured trace event to trace.jsonl"""
    with open(TRACE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_dict()) + "\n")


def zero_inbox(inbox_path: Path = INBOX_FILE) -> Tuple[List[Decision], int, int]:
    """
    Executes Part 2 (R1): Assigns every message a disposition + reason.
    - Rule-handled messages are routed deterministically (0 LLM calls).
    - Remaining messages are classified by the configured LLM (Ollama).
    Returns: (decisions_list, rule_handled_count, model_handled_count)
    """
    with open(inbox_path, "r", encoding="utf-8") as f:
        raw_msgs = json.load(f)

    messages = [Message.from_dict(m) for m in raw_msgs]
    decisions: List[Decision] = []
    needs_model: List[Message] = []
    rule_count = 0

    # Step A: First pass through generic rules
    for msg in messages:
        rule_decision = evaluate_rules(msg)
        if rule_decision is not None:
            decisions.append(rule_decision)
            rule_count += 1
            append_trace_event(TraceEvent(
                cap="R1",
                event_type="decision",
                message_id=msg.id,
                details={"disposition": rule_decision.disposition.value, "reason": rule_decision.reason, "path": "rule"}
            ))
        else:
            needs_model.append(msg)

    # Step B: Second pass through LLM (Ollama) in batches of 10
    model_count = len(needs_model)
    if needs_model:
        llm = LLMClient()
        batch_size = 10
        total_batches = (len(needs_model) + batch_size - 1) // batch_size
        print(f"\n[Ollama] Sending {len(needs_model)} messages to '{llm.provider}' in {total_batches} batches...")
        for i in range(0, len(needs_model), batch_size):
            chunk = needs_model[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            chunk_ids = [m.id for m in chunk]
            print(f"  -> Processing Batch {batch_num}/{total_batches} ({chunk_ids[0]}..{chunk_ids[-1]})...")
            model_decisions = llm.batch_classify_messages(chunk)
            for d in model_decisions:
                decisions.append(d)
                append_trace_event(TraceEvent(
                    cap="R1",
                    event_type="decision",
                    message_id=d.message_id,
                    details={"disposition": d.disposition.value, "reason": d.reason, "path": "model"}
                ))

    # Re-order decisions to match original inbox order
    decisions_by_id = {d.message_id: d for d in decisions}
    ordered_decisions = [decisions_by_id[m.id] for m in messages if m.id in decisions_by_id]

    # Write decisions.json
    with open(DECISIONS_FILE, "w", encoding="utf-8") as f:
        json.dump([d.to_dict() for d in ordered_decisions], f, indent=2)

    return ordered_decisions, rule_count, model_count
