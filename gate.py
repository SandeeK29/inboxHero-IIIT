# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Safety Gate for Irreversible Actions for Project inboxHero (Part 4 / Capability R3)
Classifies actions as reversible vs irreversible, gates irreversible sends/deletes
behind human approval or --dry-run mode, controls outbox/ file writing, and logs to trace.jsonl.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any

from config import OUTBOX_DIR, TRACE_FILE
from schemas import GateDecision, TraceEvent


# Strict Classification (Required by Part 4)
IRREVERSIBLE_ACTIONS = {"send", "delete"}
REVERSIBLE_ACTIONS = {"draft", "label", "archive", "defer"}


class SafetyGate:
    def __init__(self, outbox_dir: Path = OUTBOX_DIR, dry_run: bool = False, mock_human_input: Optional[str] = None):
        self.outbox_dir = Path(outbox_dir)
        self.dry_run = dry_run
        self.mock_human_input = mock_human_input  # Used for testing human response without blocking CLI
        self.outbox_writes_count = 0
        self.suppressed_count = 0
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def is_action_irreversible(self, action: str) -> bool:
        """Checks if an action is classified as irreversible."""
        return action.lower() in IRREVERSIBLE_ACTIONS

    def log_gate_event(self, decision: GateDecision, cap: str = "R3"):
        """Appends a structured gate event to trace.jsonl."""
        event = TraceEvent(
            cap=cap,
            event_type="gate",
            message_id=decision.message_id,
            details={
                "action": decision.action,
                "is_reversible": decision.is_reversible,
                "recipient": decision.recipient,
                "status": decision.status,
                "human_comment": decision.human_comment,
                "content_preview": decision.proposed_content[:100] + "..." if len(decision.proposed_content) > 100 else decision.proposed_content
            }
        )
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def execute_send(
        self,
        message_id: str,
        recipient: str,
        subject: str,
        body: str,
        cap: str = "R3"
    ) -> bool:
        """
        Gates sending an email.
        If dry_run: displays proposed action, suppresses write, guarantees 0 outbox writes.
        If live: prompts user [y/N]. Only writes to outbox/ on explicit approval.
        """
        # Mode 1: Dry-Run Mode
        if self.dry_run:
            print(f"\n[GATE --dry-run] Proposed irreversible action: SEND to {recipient}")
            print(f"  Subject: {subject}")
            print(f"  Preview: {body[:120]}...")
            print("  --> Dry-run active: outbox write SUPPRESSED.")
            self.suppressed_count += 1

            decision = GateDecision(
                message_id=message_id,
                action="send",
                is_reversible=False,
                proposed_content=f"Subject: {subject}\n\n{body}",
                recipient=recipient,
                status="dry_run",
                human_comment=None
            )
            self.log_gate_event(decision, cap=cap)
            return False

        # Mode 2: Interactive Human Approval Mode
        print("\n" + "=" * 50)
        print(f"⚠️  IRREVERSIBLE ACTION GATE: Outbound Email Send")
        print(f"To     : {recipient}")
        print(f"Subject: {subject}")
        print("-" * 50)
        print(f"{body}")
        print("=" * 50)

        if self.mock_human_input is not None:
            user_choice = self.mock_human_input.strip().lower()
            print(f"Human input (automated): {user_choice}")
        else:
            try:
                user_choice = input(f"Approve sending this email to {recipient}? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                user_choice = "n"

        if user_choice == "y":
            # Write to outbox/ (1 file per message)
            out_file = self.outbox_dir / f"{message_id}.txt"
            content = f"To: {recipient}\nSubject: {subject}\n\n{body}\n"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(content)

            self.outbox_writes_count += 1
            print(f"[✓] APPROVED: Written to outbox/{message_id}.txt")

            decision = GateDecision(
                message_id=message_id,
                action="send",
                is_reversible=False,
                proposed_content=content,
                recipient=recipient,
                status="approved",
                human_comment="y"
            )
            self.log_gate_event(decision, cap=cap)
            return True
        else:
            print(f"[✗] REJECTED: Send aborted by human. No file written.")
            decision = GateDecision(
                message_id=message_id,
                action="send",
                is_reversible=False,
                proposed_content=f"Subject: {subject}\n\n{body}",
                recipient=recipient,
                status="rejected",
                human_comment=user_choice or "n"
            )
            self.log_gate_event(decision, cap=cap)
            return False
