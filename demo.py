# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Unified Demo Entry Point for Project inboxHero
Runs any single capability via: python demo.py --cap <ID>

Required capabilities (Parts 2-7):
  R1  Triage         — python demo.py --cap R1
  R2  Grounded Draft — python demo.py --cap R2
  R3  Gate           — python demo.py --cap R3
  R4  Preferences    — python demo.py --cap R4
  R5  Security Scan  — python demo.py --cap R5
  R6  Dashboard      — python demo.py --cap R6

Custom capabilities (Part 8):
  X1  Follow-up Tracker    (Tier B) — python demo.py --cap X1
  X2  Thread Summarizer    (Tier B) — python demo.py --cap X2
  X3  Smart Daily Digest   (Tier C) — python demo.py --cap X3
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_r1():
    """R1: Triage — classifies all inbox messages."""
    from triage import zero_inbox
    decisions, rule_count, model_count = zero_inbox()
    print(f"\n[R1] Triage complete.")
    print(f"     Total messages   : {len(decisions)}")
    print(f"     Rule-handled     : {rule_count} (0 LLM tokens)")
    print(f"     Model-handled    : {model_count}")
    reply_count = sum(1 for d in decisions if d.disposition.value == "reply")
    print(f"     Reply dispositions: {reply_count}")
    print(f"     Output: decisions.json")


def run_r2():
    """R2: Grounded Draft — drafts grounded replies for reply-dispositioned messages."""
    from config import DECISIONS_FILE
    from drafting import GroundedDrafter

    drafter = GroundedDrafter()
    if not DECISIONS_FILE.exists():
        from triage import zero_inbox
        print("[R2] Running R1 triage first to produce decisions.json...")
        zero_inbox()

    results = drafter.run_all(DECISIONS_FILE)
    for mid, res in results.items():
        print(f"  [{mid}] Draft for {res['recipient']}:")
        print(f"    {res['draft'][:120]}...")


def run_r3():
    """R3: Gate — dry-run of the human-in-the-loop approval gate."""
    import json
    from config import DECISIONS_FILE
    from store import MailStore
    from gate import SafetyGate
    from drafting import GroundedDrafter

    gate = SafetyGate(dry_run=True)
    store = MailStore()
    drafter = GroundedDrafter(store)

    decisions = []
    if DECISIONS_FILE.exists():
        with open(DECISIONS_FILE, "r", encoding="utf-8") as f:
            decisions = json.load(f)

    reply_ids = [d["message_id"] for d in decisions if d.get("disposition") == "reply"][:3]
    gated = 0
    for mid in reply_ids:
        msg = store.get_message(mid)
        if not msg:
            continue
        draft_res = drafter.draft_reply(mid)
        draft_text = draft_res.get("draft", "[No draft]") if draft_res else "[No draft]"
        gate.execute_send(mid, msg.from_addr, msg.subject, draft_text, cap="R3")
        gated += 1

    print(f"\n[R3] Gate dry-run complete. {gated} proposed send(s) intercepted. 0 outbox writes.")
    print(f"     Suppressed: {gate.suppressed_count}  |  Actual writes: {gate.outbox_writes_count}")


def run_r4():
    """R4: Preferences — ingests standing instructions and applies them."""
    import json
    from config import DECISIONS_FILE
    from store import MailStore
    from memory import PreferenceStore

    mem = PreferenceStore()
    store = MailStore()
    extracted = 0
    for msg in store.messages:
        key = mem.ingest_from_message(msg)
        if key:
            print(f"  Preference extracted from [{msg.id}]: {key}")
            extracted += 1
    print(f"\n[R4] {extracted} preference(s) extracted and persisted.")
    print(f"     Active preferences: {list(mem.preferences.keys())}")


def run_r5():
    """R5: Security Scan — scans inbox for hostile injections."""
    from store import MailStore
    from security import SecurityScanner

    store = MailStore()
    scanner = SecurityScanner()
    flagged = []
    for msg in store.messages:
        report = scanner.scan_message(msg, cap="R5")
        if report.is_hostile:
            flagged.append(msg)
            print(f"  FLAGGED [{msg.id}]: {report.attack_type} — {report.attempted_action}")

    print(f"\n[R5] Scanned {len(store.messages)} messages. {len(flagged)} hostile attack(s) detected and refused.")


def run_r6():
    """R6: Dashboard — generates 3-pane dashboard.html and dashboard.json."""
    from config import DASHBOARD_FILE, DASHBOARD_JSON_FILE
    from dashboard import DashboardGenerator

    gen = DashboardGenerator()
    data = gen.generate_json(DASHBOARD_JSON_FILE)
    gen.generate_html(DASHBOARD_FILE, data=data)   # pass data — no second LLM pass
    pane1 = data.get("pane1_pending_actions", [])
    pane2 = data.get("pane2_flagged_items", [])
    hostile = [i for i in pane2 if i.get("refusal_reason") == "hostile_injection"]
    ungroundable = [i for i in pane2 if i.get("refusal_reason") == "no_grounding_context"]
    print(f"\n[R6] Dashboard generated:")
    print(f"     Gated actions (Pane 1) : {len(pane1)} grounded draft(s) awaiting sign-off")
    print(f"     Hostile refused (Pane 2): {len(hostile)} attack(s) refused")
    print(f"     Ungroundable (Pane 2)   : {len(ungroundable)} reply(s) the system could not draft")
    print(f"     Commitments (Pane 3)    : {len(data.get('pane3_commitments', []))}")
    print(f"     Output: {DASHBOARD_FILE.name}, {DASHBOARD_JSON_FILE.name}")


def run_x1():
    """X1: Follow-up Tracker (Tier B)."""
    from custom_caps import FollowUpTracker
    tracker = FollowUpTracker()
    tracker.run()


def run_x2():
    """X2: Thread Summarizer (Tier B)."""
    from custom_caps import ThreadSummarizer
    summarizer = ThreadSummarizer()
    summarizer.run()


def run_x3():
    """X3: Smart Daily Digest with Memory (Tier C)."""
    from custom_caps import SmartDailyDigest
    digest = SmartDailyDigest()
    digest.run()


CAPS = {
    "R1": run_r1,
    "R2": run_r2,
    "R3": run_r3,
    "R4": run_r4,
    "R5": run_r5,
    "R6": run_r6,
    "X1": run_x1,
    "X2": run_x2,
    "X3": run_x3,
}


def main():
    parser = argparse.ArgumentParser(
        description="inboxHero demo — run a single capability",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Capabilities:
  R1  Triage (rule-then-model dispatcher)
  R2  Grounded Draft (cite-or-silence reply drafter)
  R3  Gate (human-in-the-loop approval boundary)
  R4  Preferences (standing instructions with memory)
  R5  Security Scan (hostile injection detector)
  R6  Dashboard (3-pane HTML + JSON summary)
  X1  Follow-up Tracker [Tier B]
  X2  Thread Summarizer [Tier B]
  X3  Smart Daily Digest with Memory [Tier C]
        """
    )
    parser.add_argument(
        "--cap", required=True,
        choices=list(CAPS.keys()),
        help="Capability ID to run"
    )
    args = parser.parse_args()

    cap_fn = CAPS[args.cap]
    print(f"\nRunning capability: {args.cap}")
    print("=" * 60)
    cap_fn()


if __name__ == "__main__":
    main()
