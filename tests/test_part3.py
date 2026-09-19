# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Verification Suite for Part 3: Answering Properly (Capability R2)
Verifies that drafts are grounded in earlier thread messages, citations match real messages,
audit 'read' events exist in trace.jsonl, and missing info drafts nothing.
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TRACE_FILE
from store import MailStore
from drafting import GroundedDrafter


def test_part3_grounding():
    print("=" * 65)
    print("Part 3: Answering Properly (Capability R2) — Verification")
    print("=" * 65)

    store = MailStore()
    drafter = GroundedDrafter(store)

    # 1. Test Grounded Reply for m008
    print("\n--- Test 1: Grounded Reply for m008 ---")
    result = drafter.draft_reply("m008", cap="R2")
    assert result is not None, "Error: Grounded drafter returned None for m008!"

    print(f"[✓] Recipient : {result['recipient']}")
    print(f"[✓] Cited IDs : {result['cited']}")
    print("\nDraft Output:\n" + "-" * 40)
    print(result["draft"])
    print("-" * 40)

    # 2. Check that citation points to m003 and URL matches
    assert "m003" in result["cited"], f"Expected citation of m003, got: {result['cited']}"
    expected_url = "amqp://pj_stage:Rk7-quiet-otter-51@broker-stg.paperjet.io:5672/pjs"
    assert expected_url in result["draft"], "Error: Real AMQP URL from m003 was not found in the draft!"

    # Verify m003 actually exists and has that URL
    m003 = store.get_message("m003", log_read=False)
    assert m003 is not None, "Error: m003 not found in mail store!"
    assert expected_url in m003.body, "Error: m003 body does not contain the expected URL!"
    print(f"[✓] Verification: m003 legitimately contains the AMQP URL.")

    # 3. Check Audit Trail in trace.jsonl
    print("\n--- Test 2: trace.jsonl Audit Trail Verification ---")
    assert TRACE_FILE.exists(), "Error: trace.jsonl does not exist!"

    read_events = []
    draft_events = []
    with open(TRACE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ev = json.loads(line)
                if ev.get("cap") == "R2":
                    if ev.get("event_type") == "read":
                        read_events.append(ev)
                    elif ev.get("event_type") == "draft":
                        draft_events.append(ev)

    print(f"[✓] 'read' events recorded in trace.jsonl: {len(read_events)}")
    print(f"[✓] 'draft' events recorded in trace.jsonl: {len(draft_events)}")

    # Ensure m003 was read
    read_ids = {ev.get("message_id") for ev in read_events}
    assert "m003" in read_ids, "Grading failure: m003 was cited in draft but never recorded as read in trace.jsonl!"
    print(f"[✓] Audit verified: m003 was legitimately read before being cited.")

    # 4. Test Missing Information Rule (Draft Nothing)
    print("\n--- Test 3: Missing Information Rule ---")
    # Message m012 is ambiguous ("did you sort out that thing?"), context is missing from thread
    missing_result = drafter.draft_reply("m012", cap="R2")
    assert missing_result is None, "Error: System should have drafted nothing when information is missing!"
    print("[✓] Correctly drafted nothing for message with missing inbox context.")

    print("\n" + "=" * 65)
    print("ALL PART 3 (R2) REQUIREMENTS VERIFIED & SATISFIED! (100% Grounded)")
    print("=" * 65)


if __name__ == "__main__":
    test_part3_grounding()
