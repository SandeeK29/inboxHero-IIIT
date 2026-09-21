# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Verification Suite for Part 5: Standing Instructions (Capability R4)
Tests end-to-end persistent memory:
- Invocation 1: Stores preference from m015 to prefs.json and exits.
- Invocation 2 (Fresh process): Handles legal mail m018 and automatically adds co-founder to CC.
- Verifies prefs.json on disk and cap=R4 trace events.
"""

import json
import sys
import subprocess
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config import PREFS_FILE, TRACE_FILE, INBOX_FILE
from store import MailStore
from memory import PreferenceStore


def run_invocation_1():
    """Invocation 1: Reads m015, saves preference to prefs.json, exits process."""
    store = MailStore(INBOX_FILE)
    m015 = store.get_message("m015", log_read=False)
    assert m015 is not None, "m015 not found!"

    pref_store = PreferenceStore(PREFS_FILE)
    pref_key = pref_store.ingest_from_message(m015, cap="R4")
    assert pref_key is not None, "Failed to extract preference from m015!"
    print(f"[Invocation 1] Dynamically extracted & stored preference key '{pref_key}' to prefs.json.")
    print("[Invocation 1] Process now terminating completely.")


def run_invocation_2():
    """Invocation 2: Fresh process, loads prefs.json, handles m018, verifies CC."""
    store = MailStore(INBOX_FILE)
    m018 = store.get_message("m018", log_read=False)
    assert m018 is not None, "m018 not found!"

    pref_store = PreferenceStore(PREFS_FILE)
    assert len(pref_store.preferences) > 0, "Preferences missing in fresh process!"

    # Create draft for m018
    draft = {
        "recipient": m018.from_addr,
        "subject": f"Re: {m018.subject}",
        "body": "Marcus, reviewing the revised SAFE now and will sign via the portal. -- Sam",
        "cc": []
    }

    # Apply preferences
    updated_draft = pref_store.apply_preferences(m018, draft, cap="R4")
    print(f"[Invocation 2] Handling m018 (from {m018.from_addr})...")
    print(f"[Invocation 2] Resulting CC list: {updated_draft['cc']}")

    assert "priya@paperjet.io" in updated_draft["cc"], "Error: Co-founder was not added to CC!"
    print("[Invocation 2] Success: Co-founder automatically CC'd on Hartwell & Cho legal mail.")


def test_part5_persistent_preference():
    print("=" * 65)
    print("Part 5: Standing Instructions (Capability R4) — Verification")
    print("=" * 65)

    # 1. Ensure clean slate for testing
    if PREFS_FILE.exists():
        PREFS_FILE.unlink()

    # 2. Run Invocation 1 in a dedicated subprocess to prove process termination
    print("\n--- Running Invocation 1 in Subprocess ---")
    sub_env = {**dict(sys.modules.get("os").environ if "os" in sys.modules else {}), "PYTHONPATH": str(PROJECT_ROOT)}
    import os
    sub_env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    cmd1 = [sys.executable, "-c", "from tests.test_part5 import run_invocation_1; run_invocation_1()"]
    res1 = subprocess.run(cmd1, cwd=str(PROJECT_ROOT), env=sub_env, capture_output=True, text=True)
    print(res1.stdout.strip())
    assert res1.returncode == 0, f"Invocation 1 failed:\n{res1.stderr}"

    # 3. Check that prefs.json exists on disk between runs
    assert PREFS_FILE.exists(), "Grading failure: prefs.json does not exist on disk between runs!"
    with open(PREFS_FILE, "r", encoding="utf-8") as f:
        prefs_data = json.load(f)
    print(f"\n[✓] prefs.json verified on disk between runs ({len(prefs_data)} rule saved).")

    # 4. Run Invocation 2 in a fresh independent subprocess
    print("\n--- Running Invocation 2 in Fresh Subprocess (Post-Restart) ---")
    cmd2 = [sys.executable, "-c", "from tests.test_part5 import run_invocation_2; run_invocation_2()"]
    res2 = subprocess.run(cmd2, cwd=str(PROJECT_ROOT), env=sub_env, capture_output=True, text=True)
    print(res2.stdout.strip())
    assert res2.returncode == 0, f"Invocation 2 failed:\n{res2.stderr}"

    # 5. Check Trace Events in trace.jsonl
    print("\n--- Verifying trace.jsonl Evidence ---")
    r4_events = []
    with open(TRACE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                ev = json.loads(line)
                if ev.get("cap") == "R4":
                    r4_events.append(ev)

    event_types = [ev.get("event_type") for ev in r4_events]
    assert "preference_saved" in event_types, "trace.jsonl missing preference_saved event!"
    assert "preference_applied" in event_types, "trace.jsonl missing preference_applied event!"
    print(f"[✓] trace.jsonl verified: Recorded {len(r4_events)} events tagged cap=R4.")

    print("\n" + "=" * 65)
    print("ALL PART 5 (R4) REQUIREMENTS VERIFIED & SATISFIED! (100% Persistent)")
    print("=" * 65)


if __name__ == "__main__":
    test_part5_persistent_preference()
