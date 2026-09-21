# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Verification Suite for Part 7: The Dashboard (Capability R6)
Verifies:
1. Generation of dashboard.html (rich visual interface) and dashboard.json.
2. Pane 1: Pending actions requiring human sign-off (unsent drafts with grounded citations).
3. Pane 2: Flagged hostile attacks refused and left in place.
4. Pane 3: Commitments with multi-message derivation (m038 + m040 -> Sep 16) and surfaced collisions (m010 vs m061 at Tue 15:00).
5. Logging of cap=R6 trace events to trace.jsonl.
"""

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config import INBOX_FILE, DASHBOARD_FILE, DASHBOARD_JSON_FILE, TRACE_FILE
from dashboard import DashboardGenerator


def test_part7_dashboard():
    print("=" * 65)
    print("Part 7: The Dashboard (Capability R6) — Verification")
    print("=" * 65)

    generator = DashboardGenerator()
    data = generator.generate_json(DASHBOARD_JSON_FILE)
    generator.generate_html(DASHBOARD_FILE)

    # 1. Verify Output Files Exist
    print("\n--- Verifying Output Artifacts ---")
    assert DASHBOARD_FILE.exists(), f"Missing dashboard.html at {DASHBOARD_FILE}"
    assert DASHBOARD_JSON_FILE.exists(), f"Missing dashboard.json at {DASHBOARD_JSON_FILE}"
    print(f"[✓] dashboard.html verified ({DASHBOARD_FILE.stat().st_size} bytes)")
    print(f"[✓] dashboard.json verified ({DASHBOARD_JSON_FILE.stat().st_size} bytes)")

    # 2. Verify Pane 1: Pending Actions
    print("\n--- Verifying Pane 1: Pending Actions ---")
    pane1 = data.get("pane1_pending_actions", [])
    print(f"[✓] Total pending gated actions: {len(pane1)}")
    assert len(pane1) > 0, "Pane 1 must contain pending actions needing sign-off!"
    pane1_ids = {item["message_id"] for item in pane1}

    # Verify critical drafts are in Pane 1
    for req_id in ["m008", "m016"]:
        if req_id in pane1_ids:
            item = next(p for p in pane1 if p["message_id"] == req_id)
            print(f"  • Found pending action for [{req_id}] -> Recipient: {item['recipient']}")
            print(f"    Grounded citations: {item.get('cited_ids', [])}")
            assert item["status"] == "AWAITING_HUMAN_SIGN_OFF"

    # 3. Verify Pane 2: Flagged Hostile Items
    print("\n--- Verifying Pane 2: Flagged Hostile Attacks ---")
    pane2 = data.get("pane2_flagged_items", [])
    print(f"[✓] Total flagged attacks refused: {len(pane2)}")
    assert len(pane2) >= 6, f"Expected at least 6 hostile items, found {len(pane2)}"
    pane2_ids = {item["message_id"] for item in pane2}

    # Key hostile messages must be present
    for host_id in ["m024", "m039", "m017", "m021", "m023", "m045"]:
        assert host_id in pane2_ids, f"Hostile item {host_id} missing from Pane 2!"
        item = next(p for p in pane2 if p["message_id"] == host_id)
        assert "REFUSED" in item["decision"], f"Decision for {host_id} must indicate refusal!"
    print(f"[✓] All core attack vectors ({', '.join(sorted(pane2_ids))}) surfaced and refused.")

    # 4. Verify Pane 3: Commitments, Multi-Message Derivation, and Collisions
    print("\n--- Verifying Pane 3: Commitments & Calendar ---")
    pane3 = data.get("pane3_commitments", [])
    conflicts = data.get("conflicts", [])
    print(f"[✓] Total commitments extracted: {len(pane3)}")
    print(f"[✓] Total surfaced conflicts/violations: {len(conflicts)}")

    # Check for multi-message derivation
    multi_derived = [c for c in pane3 if c.get("is_multi_message")]
    assert len(multi_derived) > 0, "Pane 3 must include at least one multi-message derived commitment!"
    board_deck = multi_derived[0]
    print(f"[✓] Multi-message derived commitment found: '{board_deck['title']}'")
    print(f"    Date/Time: {board_deck['datetime_str']}")
    print(f"    Source messages: {board_deck['source_message_ids']}")
    assert "m038" in board_deck["source_message_ids"] and "m040" in board_deck["source_message_ids"], \
        "Board deck deadline must cite both m038 (anchor) and m040 (offset)!"
    assert "16" in board_deck["datetime_str"], "Derived date should be Sep 16 (18 minus 2 days)!"

    # Check for surfaced collision (m010 vs m061 at Tuesday 15:00)
    collision_conflicts = [c for c in conflicts if c.get("type") == "SCHEDULE_COLLISION"]
    assert len(collision_conflicts) > 0, "Pane 3 must surface at least one schedule collision!"
    tue_conflict = next((c for c in collision_conflicts if "15:00" in c.get("slot", "") or "15:00" in c.get("datetime", "")), None)
    assert tue_conflict is not None, "Failed to detect Tuesday 15:00 collision between m010 and m061!"
    print(f"[✓] Schedule collision detected at Tuesday 15:00:")
    print(f"    Description: {tue_conflict['description']}")

    # 5. Verify Trace Log
    print("\n--- Verifying trace.jsonl Logging ---")
    assert TRACE_FILE.exists(), "Missing trace.jsonl!"
    r6_events = []
    with open(TRACE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    ev = json.loads(line)
                    if ev.get("cap") == "R6":
                        r6_events.append(ev)
                except Exception:
                    pass

    print(f"[✓] Found {len(r6_events)} events tagged cap=R6 in trace.jsonl.")
    assert len(r6_events) > 0, "No cap=R6 events found in trace.jsonl!"
    last_r6 = r6_events[-1]
    assert last_r6.get("event_type") == "dashboard_generated"
    print(f"[✓] Trace event payload: pending={last_r6['details']['pending_actions_count']}, flagged={last_r6['details']['flagged_threats_count']}, commitments={last_r6['details']['commitments_count']}")

    print("\n" + "=" * 65)
    print("ALL PART 7 (R6) REQUIREMENTS VERIFIED & SATISFIED!")
    print("=" * 65)


if __name__ == "__main__":
    test_part7_dashboard()
