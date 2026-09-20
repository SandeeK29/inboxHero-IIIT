# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Verification Suite for Part 4: The Things You Cannot Undo (Capability R3)
Tests dry-run suppression (guaranteeing outbox writes: 0),
tests interactive approval and rejection, and verifies cap=R3 trace logging.
"""

import json
import sys
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OUTBOX_DIR, TRACE_FILE
from gate import SafetyGate


def test_part4_gate():
    print("=" * 65)
    print("Part 4: The Things You Cannot Undo (Capability R3) — Verification")
    print("=" * 65)

    test_outbox = OUTBOX_DIR / "test_run"
    test_outbox.mkdir(parents=True, exist_ok=True)

    # 1. Test Dry-Run Mode (Primary Rubric Check)
    print("\n--- Test 1: Dry-Run Mode Gating ---")
    gate_dry = SafetyGate(outbox_dir=test_outbox, dry_run=True)
    sent_dry = gate_dry.execute_send(
        message_id="m008",
        recipient="devika@paperjet.io",
        subject="Re: Staging queue creds",
        body="Here is the AMQP URL: amqp://pj_stage:Rk7-quiet-otter-51@broker-stg.paperjet.io:5672/pjs",
        cap="R3"
    )

    assert not sent_dry, "Error: execute_send should return False in dry-run mode!"
    outbox_files = list(test_outbox.glob("*.txt"))
    assert len(outbox_files) == 0, f"Error: Dry-run wrote files to outbox! Found: {outbox_files}"

    print(f"[✓] outbox/ writes: {gate_dry.outbox_writes_count}")
    print(f"[✓] Actions suppressed: {gate_dry.suppressed_count}")
    assert gate_dry.outbox_writes_count == 0, "Grading failure: outbox writes must be 0 in dry-run mode!"

    # 2. Test Human Rejection
    print("\n--- Test 2: Human Rejection (User says 'n') ---")
    gate_reject = SafetyGate(outbox_dir=test_outbox, dry_run=False, mock_human_input="n")
    sent_reject = gate_reject.execute_send(
        message_id="m008",
        recipient="devika@paperjet.io",
        subject="Re: Staging queue creds",
        body="Draft that user rejects",
        cap="R3"
    )
    assert not sent_reject, "Error: execute_send should return False when rejected!"
    assert not (test_outbox / "m008.txt").exists(), "Error: File should not exist after rejection!"
    print("[✓] Human rejection properly aborted outbox write.")

    # 3. Test Human Approval
    print("\n--- Test 3: Human Approval (User says 'y') ---")
    gate_approve = SafetyGate(outbox_dir=test_outbox, dry_run=False, mock_human_input="y")
    sent_approve = gate_approve.execute_send(
        message_id="m008",
        recipient="devika@paperjet.io",
        subject="Re: Staging queue creds",
        body="Draft that user approves: amqp://pj_stage...",
        cap="R3"
    )
    assert sent_approve, "Error: execute_send should return True when approved!"
    expected_file = test_outbox / "m008.txt"
    assert expected_file.exists(), "Error: outbox/m008.txt was not created on approval!"
    with open(expected_file, "r", encoding="utf-8") as f:
        file_content = f.read()
    assert "To: devika@paperjet.io" in file_content
    print(f"[✓] Verified outbox file created successfully on human approval.")

    # 4. Verify Trace Events for cap=R3
    print("\n--- Test 4: trace.jsonl Audit Trail Verification ---")
    assert TRACE_FILE.exists(), "Error: trace.jsonl does not exist!"

    r3_events = []
    with open(TRACE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ev = json.loads(line)
                if ev.get("cap") == "R3":
                    r3_events.append(ev)

    print(f"[✓] 'gate' events recorded in trace.jsonl: {len(r3_events)}")
    statuses = {ev["details"]["status"] for ev in r3_events}
    assert "dry_run" in statuses, "trace.jsonl missing dry_run gate event!"
    assert "rejected" in statuses, "trace.jsonl missing rejected gate event!"
    assert "approved" in statuses, "trace.jsonl missing approved gate event!"
    print(f"[✓] Verified all gate states (dry_run, rejected, approved) logged to trace.jsonl.")

    # Cleanup test folder
    shutil.rmtree(test_outbox, ignore_errors=True)

    print("\n" + "=" * 65)
    print("ALL PART 4 (R3) REQUIREMENTS VERIFIED & SATISFIED! (100% Gated)")
    print("=" * 65)


if __name__ == "__main__":
    test_part4_gate()
