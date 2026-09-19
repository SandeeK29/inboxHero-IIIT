# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Verification Suite for Part 2: Zeroing It (Capability R1)
Tests that every message gets exactly one disposition and reason,
verifies rule routing count, validates decisions.json, and asserts undecided: 0.
"""

import json
import sys
from pathlib import Path
from collections import Counter

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DECISIONS_FILE, TRACE_FILE
from triage import zero_inbox
from schemas import DispositionType


def test_part2_zeroing():
    print("=" * 65)
    print("Part 2: Zeroing It (Capability R1) — Verification")
    print("=" * 65)

    # 1. Execute zero_inbox
    decisions, rule_count, model_count = zero_inbox()
    total_processed = len(decisions)

    print(f"\n[✓] Total messages processed: {total_processed}")
    assert total_processed == 100, f"Expected 100 messages, got {total_processed}"

    # 2. Verify Rule vs Model distribution
    print(f"[✓] Rule-handled messages (0 LLM tokens): {rule_count}")
    print(f"[✓] Model-handled messages: {model_count}")
    assert rule_count >= 30, f"Expected at least 30 rule-handled messages, got {rule_count}"

    # 3. Check Dispositions and Reasons
    valid_dispositions = {d.value for d in DispositionType}
    undecided_count = 0
    disp_counts = Counter()

    for d in decisions:
        if d.disposition.value not in valid_dispositions or not d.reason:
            undecided_count += 1
        disp_counts[d.disposition.value] += 1

    print("\n--- Disposition Breakdown ---")
    for disp, count in sorted(disp_counts.items()):
        print(f"  {disp:10}: {count} messages")

    # 4. Verify decisions.json
    assert DECISIONS_FILE.exists(), "Error: decisions.json was not created!"
    with open(DECISIONS_FILE, "r", encoding="utf-8") as f:
        saved_decisions = json.load(f)
    assert len(saved_decisions) == 100, f"decisions.json has {len(saved_decisions)} items, expected 100"
    print(f"\n[✓] decisions.json verified: {len(saved_decisions)} records written to disk.")

    # 5. Verify trace.jsonl for cap=R1
    assert TRACE_FILE.exists(), "Error: trace.jsonl was not created!"
    r1_events = []
    with open(TRACE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ev = json.loads(line)
                if ev.get("cap") == "R1":
                    r1_events.append(ev)
    assert len(r1_events) >= 100, f"Expected at least 100 cap=R1 trace events, got {len(r1_events)}"
    print(f"[✓] trace.jsonl verified: {len(r1_events)} events tagged cap=R1.")

    # 6. Critical Assignment Metric: undecided == 0
    print("\n" + "-" * 40)
    print(f"undecided: {undecided_count}")
    print("-" * 40)
    assert undecided_count == 0, f"Failed: {undecided_count} messages left undecided!"

    print("\n" + "=" * 65)
    print("ALL PART 2 (R1) REQUIREMENTS VERIFIED & SATISFIED! (100% Zeroed)")
    print("=" * 65)


if __name__ == "__main__":
    test_part2_zeroing()
