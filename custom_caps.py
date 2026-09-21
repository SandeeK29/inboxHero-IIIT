# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Custom Capabilities for Project inboxHero (Part 8)
Three additional capabilities beyond the required R1-R6:

  X1 (Tier B) - Follow-up Tracker:
      Multi-step reasoning: finds messages sent by Sam that never received
      a reply after 3+ days, and drafts a polite contextual chase email.
      Runs standalone: python demo.py --cap X1

  X2 (Tier B) - Thread Summarizer:
      Multi-step reasoning across a thread: walks the full conversation,
      uses the LLM to summarise the thread and extract the single open
      question or next required action.
      Runs standalone: python demo.py --cap X2

  X3 (Tier C) - Smart Daily Digest with Memory:
      Genuinely agentic: plans what happened, what needs the user, and
      what can wait. Uses a persistent digest log so already-surfaced
      items are NOT re-reported on the next run. Holds any proposed
      action that crosses the gate boundary for human approval before
      acting.
      Runs standalone: python demo.py --cap X3
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import INBOX_FILE, TRACE_FILE, DECISIONS_FILE
from schemas import Message, TraceEvent
from store import MailStore
from llm_client import LLMClient
from rules import evaluate_rules
from security import SecurityScanner


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _log_trace(cap: str, event_type: str, msg_id: Optional[str], details: Dict[str, Any]):
    """Appends a single trace event to trace.jsonl."""
    event = TraceEvent(cap=cap, event_type=event_type, message_id=msg_id, details=details)
    with open(TRACE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_dict()) + "\n")


def _parse_ts(ts: str) -> Optional[datetime]:
    """Best-effort ISO-8601 timestamp parser."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[:19], fmt[:len(ts[:19])])
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# X1: Follow-up Tracker (Tier B)
# ---------------------------------------------------------------------------

class FollowUpTracker:
    """
    Capability X1 - Tier B (multi-step, reasoning across several messages)

    Identifies threads where Sam sent the last message but received no reply
    within a configurable threshold (default 3 days). For each such thread,
    drafts a concise, contextual chase email grounded in the thread history.

    Observable output: JSON list of {message_id, days_waiting, subject, draft}
    printed to stdout and logged to trace.jsonl with cap=X1.
    """

    CAP = "X1"

    def __init__(self, store=None, llm=None, threshold_days=3, sam_domain="paperjet.io"):
        self.store = store or MailStore()
        self.llm = llm or LLMClient()
        self.threshold_days = threshold_days
        self.sam_domain = sam_domain

    def _sam_sent(self, msg):
        return msg.from_addr.lower() == "sam@paperjet.io"

    def find_unanswered(self, reference_dt=None):
        if reference_dt is None:
            # Anchor to simulated inbox date (max message timestamp) or current UTC
            parsed_dates = [_parse_ts(m.timestamp) for m in self.store.messages]
            valid_dates = [d for d in parsed_dates if d is not None]
            reference_dt = max(valid_dates, default=datetime.utcnow())

        unanswered = []

        for thread_id, msgs in self.store.by_thread.items():
            ordered = sorted(msgs, key=lambda m: m.timestamp)
            if not ordered:
                continue

            last_msg = ordered[-1]
            if not self._sam_sent(last_msg):
                continue

            correspondent = None
            for m in ordered:
                if not self._sam_sent(m):
                    correspondent = m.from_addr
                    break
            if not correspondent and last_msg.to_addr:
                correspondent = last_msg.to_addr

            # Skip messages Sam sent to himself (e.g. self-notes)
            if not correspondent or correspondent.lower() == "sam@paperjet.io":
                continue

            last_ts = _parse_ts(last_msg.timestamp)
            if not last_ts:
                continue

            days_waiting = (reference_dt - last_ts).days
            if days_waiting < self.threshold_days:
                continue

            prior_context = "\n\n".join([
                f"[{m.id}] From: {m.from_addr}\nSubject: {m.subject}\nBody:\n{m.body}"
                for m in ordered
            ])

            unanswered.append({
                "last_sent_id": last_msg.id,
                "thread_id": thread_id,
                "subject": last_msg.subject,
                "correspondent": correspondent,
                "days_waiting": days_waiting,
                "prior_context": prior_context,
                "source_ids": [m.id for m in ordered]
            })

        return unanswered

    def _draft_chase(self, item):
        prompt = (
            "You are an executive email assistant. Sam sent a message that received no reply.\n"
            "Draft a SHORT, professional, polite follow-up ('chase') email.\n"
            "Use ONLY the facts in the thread. Do NOT invent new information.\n"
            "Do NOT write a subject line - write only the body.\n\n"
            f"Thread history:\n{item['prior_context']}\n\n"
            "Output ONLY the email body text. Keep it under 5 sentences.\n"
            "Do not use placeholder brackets like [Name] - use the actual name from the thread."
        )
        try:
            resp = self.llm.call_raw(prompt).strip()
            resp = re.sub(r"^```[a-z]*\n?", "", resp, flags=re.MULTILINE).strip("`").strip()
            if len(resp) > 30:
                return resp
        except Exception as e:
            print(f"[X1] LLM unavailable for chase draft ({e}), using fallback.")

        return (
            f"Hi,\n\nJust following up on '{item['subject']}' - "
            f"we sent our last message {item['days_waiting']} day(s) ago and haven't heard back. "
            "Please let us know if you need anything from our side or if the timeline has changed.\n\n"
            "Best,\nSam"
        )

    def run(self):
        print(f"\n{'='*60}")
        print("Capability X1: Follow-up Tracker")
        print(f"{'='*60}")
        print(f"Threshold: {self.threshold_days}+ days without reply\n")

        unanswered = self.find_unanswered()

        if not unanswered:
            print("[X1] No unanswered threads found beyond the threshold.")
            _log_trace(self.CAP, "followup_scan", None, {"unanswered_count": 0})
            return []

        results = []
        for item in unanswered:
            draft = self._draft_chase(item)
            result = {
                "message_id": item["last_sent_id"],
                "thread_id": item["thread_id"],
                "subject": item["subject"],
                "correspondent": item["correspondent"],
                "days_waiting": item["days_waiting"],
                "source_ids": item["source_ids"],
                "draft": draft
            }
            results.append(result)

            _log_trace(self.CAP, "followup_chase_drafted", item["last_sent_id"], {
                "correspondent": item["correspondent"],
                "days_waiting": item["days_waiting"],
                "subject": item["subject"]
            })

        print(json.dumps(results, indent=2))
        print(f"\n[X1] Found {len(results)} unanswered thread(s). Chase drafts generated.")
        _log_trace(self.CAP, "followup_scan_complete", None, {
            "unanswered_count": len(results),
            "message_ids": [r["message_id"] for r in results]
        })
        return results


# ---------------------------------------------------------------------------
# X2: Thread Summarizer (Tier B)
# ---------------------------------------------------------------------------

class ThreadSummarizer:
    """
    Capability X2 - Tier B (multi-step reasoning across several messages)

    For every thread with 3+ messages, walks the full conversation and uses
    the LLM to produce:
      - A one-sentence summary of what the thread is about
      - The single open question or next action that is still unresolved

    Observable output: JSON list of {thread_id, message_count, summary,
    open_question, message_ids} printed to stdout and logged with cap=X2.
    """

    CAP = "X2"
    MIN_MESSAGES = 3

    def __init__(self, store=None, llm=None):
        self.store = store or MailStore()
        self.llm = llm or LLMClient()

    def _summarise_thread(self, msgs):
        history = "\n\n".join([
            f"[{m.id}] From: {m.from_addr}\nSubject: {m.subject}\nBody:\n{m.body}"
            for m in msgs
        ])

        prompt = (
            "You are an executive email assistant analysing an email thread.\n"
            "Read the thread below and respond with a JSON object containing:\n"
            "  'summary': one sentence describing what this thread is about.\n"
            "  'open_question': the single most important unresolved question or"
            " next action still pending. If fully resolved, write 'None'.\n\n"
            f"Thread:\n{history}\n\n"
            "Return ONLY the JSON object with keys 'summary' and 'open_question'."
        )

        try:
            resp = self.llm.call_raw(prompt)
            json_match = re.search(r"\{.*\}", resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                summary = data.get("summary", "").strip()
                open_q = data.get("open_question", "None").strip()
                if summary:
                    return summary, open_q
        except Exception as e:
            print(f"[X2] LLM summarisation error ({e}), using fallback.")

        last = msgs[-1]
        return (
            f"Thread about '{last.subject}' with {len(msgs)} messages.",
            "Unable to determine - manual review recommended."
        )

    def run(self):
        print(f"\n{'='*60}")
        print("Capability X2: Thread Summarizer")
        print(f"{'='*60}")
        print(f"Summarising threads with {self.MIN_MESSAGES}+ messages\n")

        results = []
        qualifying = [
            (tid, sorted(msgs, key=lambda m: m.timestamp))
            for tid, msgs in self.store.by_thread.items()
            if len(msgs) >= self.MIN_MESSAGES
        ]

        if not qualifying:
            print("[X2] No qualifying threads found.")
            return []

        for thread_id, msgs in qualifying:
            summary, open_q = self._summarise_thread(msgs)
            msg_ids = [m.id for m in msgs]

            result = {
                "thread_id": thread_id,
                "subject": msgs[-1].subject,
                "message_count": len(msgs),
                "message_ids": msg_ids,
                "summary": summary,
                "open_question": open_q
            }
            results.append(result)

            _log_trace(self.CAP, "thread_summarised", msgs[-1].id, {
                "thread_id": thread_id,
                "message_count": len(msgs),
                "summary": summary,
                "open_question": open_q
            })

        print(json.dumps(results, indent=2))
        print(f"\n[X2] Summarised {len(results)} thread(s).")
        _log_trace(self.CAP, "summarization_complete", None, {
            "threads_summarised": len(results)
        })
        return results


# ---------------------------------------------------------------------------
# X3: Smart Daily Digest with Memory (Tier C)
# ---------------------------------------------------------------------------

DIGEST_LOG_FILE = PROJECT_ROOT / "digest_log.json"


class SmartDailyDigest:
    """
    Capability X3 - Tier C (agentic: planning + persistent memory + human-in-the-loop)

    Produces a prioritised daily briefing with three sections:
      * NEEDS YOU NOW   - messages requiring human decision/reply, with proposed action
      * HAPPENED TODAY  - notable events/updates already handled or informational
      * CAN WAIT        - deferred items, low-priority, or fully automated

    Genuinely agentic properties:
      1. PLANNING: Uses LLM to reason over all inbox messages and assign each to
         the correct bucket.
      2. MEMORY: Persists a digest_log.json that tracks which message IDs have
         already been surfaced. On the next run, those messages are skipped -
         only NEW items appear. This prevents re-alerting on stale threads.
      3. HUMAN-IN-THE-LOOP: Any item in 'NEEDS YOU NOW' that requires an
         irreversible action (e.g. sending a reply) is flagged as
         AWAITING_APPROVAL - the system does NOT act until the human approves
         via the gate (consistent with Part 4).
      4. RECOVERY: If the LLM fails for any individual message, a deterministic
         linguistic heuristic classifies it instead of crashing.
    """

    CAP = "X3"
    DIGEST_OUTPUT_FILE = PROJECT_ROOT / "digest_output.json"

    def __init__(self, store=None, llm=None, scanner=None, digest_log_path=DIGEST_LOG_FILE):
        self.store = store or MailStore()
        self.llm = llm or LLMClient()
        self.scanner = scanner or SecurityScanner()
        self.digest_log_path = digest_log_path
        self._seen_ids = self._load_seen_ids()

    def _load_seen_ids(self):
        if self.digest_log_path.exists():
            try:
                with open(self.digest_log_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data.get("seen_ids", []))
            except Exception:
                pass
        return set()

    def _save_seen_ids(self, new_ids):
        all_ids = list(self._seen_ids | set(new_ids))
        with open(self.digest_log_path, "w", encoding="utf-8") as f:
            json.dump({
                "seen_ids": all_ids,
                "last_run": datetime.utcnow().isoformat()
            }, f, indent=2)
        self._seen_ids = set(all_ids)

    def _fallback_heuristic(self, msg):
        text = f"{msg.subject} {msg.body}".lower()
        if any(k in text for k in ["?", "could you", "can you", "does that work", "let me know", "please confirm"]):
            bucket, action, needs_gate = "needs_you", "Draft and send reply (requires gate approval)", True
        elif any(k in text for k in ["invoice", "receipt", "payment", "shipped", "delivered", "payout"]):
            bucket, action, needs_gate = "happened", None, False
        else:
            bucket, action, needs_gate = "can_wait", None, False
        return {
            "message_id": msg.id,
            "subject": msg.subject,
            "from": msg.from_addr,
            "bucket": bucket,
            "headline": f"{msg.subject} - from {msg.from_addr}",
            "proposed_action": action,
            "needs_gate": needs_gate
        }

    def _classify_message(self, msg):
        # 1. Rule check for zero-token classification
        rule_dec = evaluate_rules(msg)
        if rule_dec is not None:
            text = f"{msg.subject} {msg.body}".lower()
            if any(k in text for k in ["receipt", "invoice", "payment", "shipped", "delivered", "payout", "order"]):
                bucket = "happened"
            else:
                bucket = "can_wait"
            return {
                "message_id": msg.id,
                "subject": msg.subject,
                "from": msg.from_addr,
                "bucket": bucket,
                "headline": f"{msg.subject} - {msg.from_addr}",
                "proposed_action": None,
                "needs_gate": False
            }

        # 2. Fallback single message classification
        return self._fallback_heuristic(msg)

    def _classify_batch_llm(self, msgs: List[Message]) -> List[Dict[str, Any]]:
        """Classifies a batch of up to 10 human emails via LLM with structured JSON."""
        if not msgs:
            return []

        prompt = (
            "You are an executive email triage assistant producing a daily digest.\n"
            "Classify each email into EXACTLY ONE bucket:\n"
            "  'needs_you'  - requires human decision, reply, or sign-off today\n"
            "  'happened'   - notable event or update; informational, no action needed\n"
            "  'can_wait'   - low priority, automated notification, or already handled\n\n"
            "Emails to classify:\n"
            + "\n---\n".join([f"ID: {m.id}\nFrom: {m.from_addr}\nSubject: {m.subject}\nBody: {m.body[:300]}" for m in msgs])
            + "\n\nRespond with a JSON array of objects, one per email:\n"
            "[\n"
            "  {\n"
            '    "message_id": "...",\n'
            '    "bucket": "needs_you" | "happened" | "can_wait",\n'
            '    "headline": "one crisp sentence describing this item for the digest",\n'
            '    "proposed_action": "short string describing what to do, or null",\n'
            '    "needs_gate": true | false\n'
            "  }\n"
            "]\n"
            "Return ONLY valid JSON."
        )

        try:
            resp = self.llm.call_raw(prompt)
            json_match = re.search(r"\[.*\]", resp, re.DOTALL)
            if json_match:
                parsed_list = json.loads(json_match.group(0))
                id_to_parsed = {item.get("message_id"): item for item in parsed_list if isinstance(item, dict)}
                results = []
                for m in msgs:
                    p = id_to_parsed.get(m.id)
                    if p:
                        bucket = p.get("bucket", "can_wait")
                        if bucket not in ("needs_you", "happened", "can_wait"):
                            bucket = "can_wait"
                        results.append({
                            "message_id": m.id,
                            "subject": m.subject,
                            "from": m.from_addr,
                            "bucket": bucket,
                            "headline": p.get("headline", m.subject).strip(),
                            "proposed_action": p.get("proposed_action"),
                            "needs_gate": bool(p.get("needs_gate", False))
                        })
                    else:
                        results.append(self._fallback_heuristic(m))
                return results
        except Exception:
            pass

        return [self._fallback_heuristic(m) for m in msgs]

    def run(self):
        print(f"\n{'='*60}")
        print("Capability X3: Smart Daily Digest")
        print(f"{'='*60}")

        already_seen = len(self._seen_ids)
        print(f"Memory: {already_seen} message(s) already surfaced in prior runs - skipping.\n")

        new_msgs = []
        for msg in self.store.messages:
            if msg.id in self._seen_ids:
                continue
            sec = self.scanner.scan_message(msg)
            if sec.is_hostile:
                continue
            new_msgs.append(msg)

        if not new_msgs:
            print("[X3] No new messages to digest - inbox is clear.")
            _log_trace(self.CAP, "digest_generated", None, {
                "new_messages": 0,
                "already_seen": already_seen
            })
            return {"needs_you": [], "happened": [], "can_wait": []}

        print(f"Classifying {len(new_msgs)} new message(s)...\n")

        needs_you, happened, can_wait = [], [], []
        surfaced_ids = []

        # Split into rule-handled and model-handled
        rule_msgs = []
        model_msgs = []
        for msg in new_msgs:
            if evaluate_rules(msg) is not None:
                rule_msgs.append(msg)
            else:
                model_msgs.append(msg)

        classified_items = []
        # 1. Process rule-handled immediately
        for msg in rule_msgs:
            classified_items.append(self._classify_message(msg))

        # 2. Process model-handled in batches of 10
        batch_size = 10
        for i in range(0, len(model_msgs), batch_size):
            batch = model_msgs[i : i + batch_size]
            batch_results = self._classify_batch_llm(batch)
            classified_items.extend(batch_results)

        for item in classified_items:
            surfaced_ids.append(item["message_id"])

            if item["needs_gate"]:
                item["gate_status"] = "AWAITING_APPROVAL"
            else:
                item["gate_status"] = "NO_ACTION_REQUIRED"

            _log_trace(self.CAP, "digest_item_classified", item["message_id"], {
                "bucket": item["bucket"],
                "headline": item["headline"],
                "gate_status": item["gate_status"]
            })

            if item["bucket"] == "needs_you":
                needs_you.append(item)
            elif item["bucket"] == "happened":
                happened.append(item)
            else:
                can_wait.append(item)

        self._save_seen_ids(surfaced_ids)

        digest = {
            "generated_at": datetime.utcnow().isoformat(),
            "new_messages_processed": len(new_msgs),
            "previously_seen": already_seen,
            "needs_you": needs_you,
            "happened": happened,
            "can_wait": can_wait
        }

        self._print_digest(digest)

        with open(self.DIGEST_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(digest, f, indent=2)
        print(f"\n[X3] Digest saved to {self.DIGEST_OUTPUT_FILE.name}")

        _log_trace(self.CAP, "digest_generated", None, {
            "new_messages": len(new_msgs),
            "needs_you": len(needs_you),
            "happened": len(happened),
            "can_wait": len(can_wait),
            "previously_seen": already_seen,
            "surfaced_ids": surfaced_ids
        })

        return digest

    def _print_digest(self, digest):
        print(f"\n DAILY DIGEST  -  {digest['generated_at'][:10]}")
        print(f"   {digest['new_messages_processed']} new | {digest['previously_seen']} already seen\n")

        print("-" * 60)
        print(f"[NEEDS YOU NOW]  ({len(digest['needs_you'])} item(s))")
        print("-" * 60)
        if not digest["needs_you"]:
            print("   (none)\n")
        for item in digest["needs_you"]:
            gate = f"  [{item['gate_status']}]" if item.get("gate_status") else ""
            print(f"  * [{item['message_id']}] {item['headline']}{gate}")
            if item.get("proposed_action"):
                print(f"    -> Action: {item['proposed_action']}")
        print()

        print("-" * 60)
        print(f"[HAPPENED TODAY]  ({len(digest['happened'])} item(s))")
        print("-" * 60)
        if not digest["happened"]:
            print("   (none)\n")
        for item in digest["happened"]:
            print(f"  * [{item['message_id']}] {item['headline']}")
        print()

        print("-" * 60)
        print(f"[CAN WAIT]  ({len(digest['can_wait'])} item(s))")
        print("-" * 60)
        if not digest["can_wait"]:
            print("   (none)\n")
        for item in digest["can_wait"]:
            print(f"  * [{item['message_id']}] {item['headline']}")
        print()
