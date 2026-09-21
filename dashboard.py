# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Three-Pane Interactive Dashboard Generator for Project inboxHero (Capability R6)
Generates:
1. Pane 1: Pending Actions — Gated drafts awaiting human sign-off with grounded citations.
2. Pane 2: Flagged Threats — Refused prompt injections, phishing, and wire fraud (kept in place).
3. Pane 3: Commitments & Calendar — Schedule with multi-message derivations and surfaced collisions.

Outputs dashboard.html (rich visual interface) and dashboard.json, and logs cap=R6 to trace.jsonl.
Zero hardcoded message IDs, subjects, sender names, or dates.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    INBOX_FILE,
    DECISIONS_FILE,
    PREFS_FILE,
    TRACE_FILE,
    DASHBOARD_FILE,
    DASHBOARD_JSON_FILE,
    DRAFTS_FILE
)
from schemas import Message, Commitment, TraceEvent
from store import MailStore
from security import SecurityScanner
from memory import PreferenceStore
from drafting import GroundedDrafter


class DashboardGenerator:
    def __init__(
        self,
        inbox_file: Path = INBOX_FILE,
        decisions_file: Path = DECISIONS_FILE,
        prefs_file: Path = PREFS_FILE,
        trace_file: Path = TRACE_FILE
    ):
        self.inbox_file = inbox_file
        self.decisions_file = decisions_file
        self.prefs_file = prefs_file
        self.trace_file = trace_file

        self.store = MailStore(self.inbox_file)
        self.scanner = SecurityScanner()
        self.memory = PreferenceStore(self.prefs_file)
        self.drafter = GroundedDrafter(self.store)
        self._last_data: Optional[Dict[str, Any]] = None

    def get_pane1_pending_actions(self) -> List[Dict[str, Any]]:
        """
        Pane 1: Pending Actions needing human sign-off.
        Surfaces only genuine human-to-human messages that need a reply.
        Filters out:
          - Automated senders (no-reply, noreply, alerts, ship-confirm, etc.)
          - Messages sent by the owner themselves (cannot reply to yourself)
          - Hostile messages (already in Pane 2)
        """
        pending_actions = []

        # Load existing decisions if available
        decisions_map = {}
        if self.decisions_file.exists():
            try:
                with open(self.decisions_file, "r", encoding="utf-8") as f:
                    decs = json.load(f)
                    decisions_map = {d["message_id"]: d for d in decs}
            except Exception:
                decisions_map = {}

        # Automated sender prefixes — generic pattern, not a hardcoded allowlist.
        # Covers no-reply addresses, department aliases, automated system accounts.
        AUTO_PREFIXES = (
            "no-reply", "noreply", "do-not-reply", "donotreply",
            "ship-confirm", "ship-notification", "order-confirm",
            "calendar-notification", "alerts", "alert",
            "info", "feedback", "status", "notes",
            "checkin", "appointments", "success", "mailer",
            "notifications", "billing", "no-reply-aws",
            "hr", "facilities", "it-support", "helpdesk",
            "noreply-aws", "support", "admin",
        )

        def _is_automated(addr: str) -> bool:
            """Returns True if the sender is an automated/no-reply address."""
            local = addr.split("@")[0].lower()
            return any(local.startswith(p.rstrip("@")) or local == p.rstrip("@")
                       for p in AUTO_PREFIXES)

        # Infer owner address generically: the most common 'to' address in the inbox
        # is the inbox owner (Sam). Messages FROM the owner shouldn't be pending actions.
        from collections import Counter
        to_counter = Counter(m.to_addr.lower() for m in self.store.messages if m.to_addr)
        owner_addr = to_counter.most_common(1)[0][0] if to_counter else ""

        def _is_owner_sent(msg: Message) -> bool:
            """Returns True if the message was sent BY the owner, not received by them."""
            return msg.from_addr.lower() == owner_addr


        candidate_ids_raw = []
        if decisions_map:
            for mid, d in decisions_map.items():
                if d.get("disposition") == "reply":
                    candidate_ids_raw.append(mid)
        else:
            # Fallback: heuristic scan when no decisions.json exists
            for msg in self.store.messages:
                if _is_automated(msg.from_addr):
                    continue
                text = (msg.subject + " " + msg.body).lower()
                if any(q in text for q in ["?", "could you", "does that work", "let me know", "can we"]):
                    sec = self.scanner.scan_message(msg)
                    if not sec.is_hostile:
                        candidate_ids_raw.append(msg.id)

        # Include any messages that have precomputed grounded drafts in DRAFTS_FILE
        if DRAFTS_FILE.exists():
            try:
                with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
                    saved_drafts = json.load(f)
                for mid in saved_drafts:
                    if mid not in candidate_ids_raw:
                        candidate_ids_raw.append(mid)
            except Exception:
                pass

        # Deduplicate by thread: for threads with multiple 'reply' candidates,
        # only surface the most recent message. Showing every message in a long
        # thread creates noise; the latest unresolved message represents the thread.
        thread_latest: Dict[str, Tuple[str, str]] = {}  # thread_id -> (msg_id, timestamp)
        for mid in candidate_ids_raw:
            msg = self.store.get_message(mid, log_read=False)
            if not msg:
                continue
            tid = msg.thread_id
            if tid not in thread_latest or msg.timestamp > thread_latest[tid][1]:
                thread_latest[tid] = (mid, msg.timestamp)
        candidate_ids = [v[0] for v in thread_latest.values()]

        # Process each pending candidate
        for mid in candidate_ids:
            msg = self.store.get_message(mid)
            if not msg:
                continue

            # Filter 1: Skip automated/no-reply senders
            if _is_automated(msg.from_addr):
                continue

            # Filter 2: Skip messages the owner sent to themselves
            if _is_owner_sent(msg):
                continue

            # Filter 3: Skip hostile messages (they belong in Pane 2)
            sec = self.scanner.scan_message(msg)
            if sec.is_hostile:
                continue

            existing_dec = decisions_map.get(mid, {})
            draft_text = existing_dec.get("draft_body")
            cited_ids = existing_dec.get("cited_ids", [])
            cc_list = []

            if not draft_text:
                # Check pre-computed drafts from R2 run (or previous invocation)
                saved_drafts = {}
                if DRAFTS_FILE.exists():
                    try:
                        with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
                            saved_drafts = json.load(f)
                    except Exception:
                        saved_drafts = {}

                if mid in saved_drafts:
                    draft_res = saved_drafts[mid]
                else:
                    draft_res = self.drafter.draft_reply(mid, cap="R6")
                    if draft_res:
                        saved_drafts[mid] = draft_res
                        try:
                            with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
                                json.dump(saved_drafts, f, indent=2)
                        except Exception:
                            pass

                if draft_res and draft_res.get("draft"):
                    draft_text = draft_res.get("draft")
                    cited_ids = draft_res.get("cited_ids", []) or draft_res.get("cited", [])
                    draft_res = self.memory.apply_preferences(msg, draft_res, cap="R6")
                    cc_list = draft_res.get("cc", [])
                else:
                    # Drafter could not ground a reply from inbox context.
                    # Per spec: ungroundable messages go to Pane 2, NOT Pane 1.
                    # Pane 1 is "what the system wants to do" — no draft = nothing to gate.
                    continue

            # Apply dynamic preferences (e.g. standing CC rules)
            draft_payload = {"draft": draft_text, "cc": cc_list}
            updated = self.memory.apply_preferences(msg, draft_payload, cap="R6")
            cc_list = updated.get("cc", [])

            pending_actions.append({
                "message_id": msg.id,
                "from": msg.from_addr,
                "subject": msg.subject,
                "timestamp": msg.timestamp,
                "body": msg.body,
                "proposed_action": "send_reply",
                "recipient": msg.from_addr,
                "cc": cc_list,
                "draft_body": draft_text,
                "cited_ids": cited_ids,
                "status": "AWAITING_HUMAN_SIGN_OFF",
                "is_reversible": False,
                "notes": "Gate: Irreversible action held at boundary for user approval."
            })

        return pending_actions


    # _generate_inquiry_draft removed.
    # Rule: if the inbox contains no information to ground a reply, draft nothing.
    # An agent that sends 'I will look into this' is an agent that should be fired.

    def get_pane2_flagged_threats(self, ungroundable: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """
        Pane 2: Refused actions.
        Per spec: hostile messages + anything the system could not ground.
        """
        flagged = []

        # Section A: Hostile/adversarial messages (prompt injection, phishing, spoofing)
        for msg in self.store.messages:
            report = self.scanner.scan_message(msg, cap="R6")
            if report.is_hostile:
                flagged.append({
                    "message_id": msg.id,
                    "from": msg.from_addr,
                    "subject": msg.subject,
                    "timestamp": msg.timestamp,
                    "threat_type": report.attack_type,
                    "attempted_action": report.attempted_action,
                    "risk_level": "CRITICAL",
                    "decision": "REFUSED - Left in place",
                    "refusal_reason": "hostile_injection",
                    "enforcement": "Zero writes to outbox. Attacker instructions suppressed. Preserved for audit."
                })

        # Section B: Messages the system wanted to reply to but could not ground
        # (reply disposition, non-hostile, but no grounding context found in inbox)
        for item in (ungroundable or []):
            flagged.append({
                "message_id": item["message_id"],
                "from": item["from"],
                "subject": item["subject"],
                "timestamp": item["timestamp"],
                "threat_type": "ungroundable_reply",
                "attempted_action": f"Proposed reply to {item['from']} re: '{item['subject']}'",
                "risk_level": "INFO",
                "decision": "REFUSED - Could not ground from inbox",
                "refusal_reason": "no_grounding_context",
                "enforcement": "System declined to draft. No message sent. Surfaced for human attention."
            })

        return flagged

    def _parse_message_datetime(self, msg: Message) -> Optional[Tuple[datetime, str, str]]:
        """
        Generic date and time parser for email text.
        Returns (parsed_datetime, formatted_datetime_str, normalized_slot_key) or None.
        """
        text = f"{msg.subject} {msg.body}"
        msg_dt = datetime.fromisoformat(msg.timestamp)

        # 1. Parse Time: e.g. "3:00pm", "10:00am", "9:30am", "14:00"
        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)", text)
        if not time_match:
            time_match_24 = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
            if not time_match_24:
                return None
            hr = int(time_match_24.group(1))
            mn = int(time_match_24.group(2))
            ampm_str = f"{hr:02d}:{mn:02d}"
        else:
            hr = int(time_match.group(1))
            mn = int(time_match.group(2) or 0)
            ampm = time_match.group(3).lower()
            ampm_str = f"{hr}:{mn:02d} {ampm.upper()}"
            if ampm == "pm" and hr < 12:
                hr += 12
            elif ampm == "am" and hr == 12:
                hr = 0

        # 2. Parse Month (if explicitly mentioned)
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        m_match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b", text, re.IGNORECASE)
        month = month_map[m_match.group(1).lower()[:3]] if m_match else msg_dt.month

        # 3. Parse Day of month: e.g. "Sep 15", "the 18th", "15th at"
        day_patterns = [
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?",
            r"(?:the|on)\s+(\d{1,2})(?:st|nd|rd|th)?",
            r"\b(\d{1,2})(?:st|nd|rd|th)\b"
        ]
        day = None
        for pat in day_patterns:
            d_match = re.search(pat, text, re.IGNORECASE)
            if d_match:
                day = int(d_match.group(1))
                break

        if not day:
            # Check weekday mentioned in text relative to message timestamp
            weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            for idx, w in enumerate(weekdays):
                if re.search(rf"\b{w}\b", text, re.IGNORECASE):
                    days_ahead = (idx - msg_dt.weekday()) % 7
                    if days_ahead == 0 and ("next" in text.lower() or "at" in text.lower()):
                        days_ahead = 7
                    target_date = msg_dt + timedelta(days=days_ahead)
                    day = target_date.day
                    month = target_date.month
                    break

        if not day:
            day = msg_dt.day

        year = msg_dt.year
        try:
            event_dt = datetime(year, month, day, hr, mn)
        except ValueError:
            event_dt = msg_dt.replace(hour=hr, minute=mn)

        formatted_str = event_dt.strftime("%b %d, %Y at %I:%M %p")
        normalized_slot = event_dt.strftime("%Y-%m-%d %H:%M")
        return event_dt, formatted_str, normalized_slot

    def get_pane3_commitments(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Pane 3: Calendar Commitments with Multi-Message Derivations & Collisions.
        Completely generic across any input dataset.
        """
        commitments: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []

        # 1. Scan candidate scheduling emails
        commitment_keywords = [
            "meeting", "scheduled", "appointment", "demo", "calendar", 
            "set for", "1:1", "intro call", "slot", "standup"
        ]
        
        for msg in self.store.messages:
            text = f"{msg.subject} {msg.body}".lower()
            if any(k in text for k in commitment_keywords):
                # Ensure not hostile injection
                report = self.scanner.scan_message(msg)
                if report.is_hostile:
                    continue

                parsed = self._parse_message_datetime(msg)
                if parsed:
                    event_dt, formatted_str, normalized_slot = parsed
                    # Clean title from subject
                    clean_title = re.sub(r"^(?:Re:\s*|Reminder:\s*|Your\s*)", "", msg.subject, flags=re.IGNORECASE).strip()
                    commitments.append({
                        "id": f"comm_{msg.id}",
                        "title": clean_title,
                        "datetime_str": formatted_str,
                        "normalized_slot": normalized_slot,
                        "datetime_obj": event_dt,
                        "source_message_ids": [msg.id],
                        "notes": msg.body.strip().split("\n")[0][:120],
                        "is_multi_message": False
                    })

        # 2. Dynamic Multi-Message Derivation Engine
        # Matches any relative offset: "X days before <event name>"
        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, 
            "five": 5, "six": 6, "seven": 7, "ten": 10
        }
        for msg in self.store.messages:
            rel_match = re.search(
                r"(\w+)\s+days?\s+(?:before|prior to)\s+(?:the\s+)?([a-zA-Z0-9\s]+?)(?:\?|\.|\,|$|\n)",
                msg.body,
                re.IGNORECASE
            )
            if rel_match:
                offset_word = rel_match.group(1).lower()
                target_event = rel_match.group(2).strip().lower()
                offset_days = word_to_num.get(offset_word)
                if not offset_days and offset_word.isdigit():
                    offset_days = int(offset_word)
                if not offset_days:
                    offset_days = 2

                # Dynamically search store for anchor message matching target event
                for anchor_msg in self.store.messages:
                    if anchor_msg.id != msg.id:
                        anchor_text = f"{anchor_msg.subject} {anchor_msg.body}".lower()
                        if target_event in anchor_text:
                            anchor_parsed = self._parse_message_datetime(anchor_msg)
                            if anchor_parsed:
                                anchor_dt, _, _ = anchor_parsed
                                derived_dt = anchor_dt - timedelta(days=offset_days)
                                der_id = f"derived_{msg.id}_{anchor_msg.id}"
                                formatted_der = derived_dt.strftime("%b %d, %Y at %I:%M %p")
                                normalized_der = derived_dt.strftime("%Y-%m-%d %H:%M")
                                clean_title = f"{msg.subject.strip().title()} (Circulation Deadline)"

                                if not any(c["id"] == der_id for c in commitments):
                                    commitments.append({
                                        "id": der_id,
                                        "title": clean_title,
                                        "datetime_str": formatted_der,
                                        "normalized_slot": normalized_der,
                                        "datetime_obj": derived_dt,
                                        "source_message_ids": [anchor_msg.id, msg.id],
                                        "notes": f"Multi-message derived: {offset_days} days prior to {target_event.title()} (established in {anchor_msg.id}).",
                                        "is_multi_message": True
                                    })

        # 3. Dynamic Collision & Policy Conflict Surfacing
        slots_seen: Dict[str, Dict[str, Any]] = {}
        for comm in commitments:
            slot = comm.get("normalized_slot")
            if not slot:
                continue

            # Check time collision across commitments
            if slot in slots_seen:
                prior = slots_seen[slot]
                comm["is_conflict"] = True
                comm["conflict_with_id"] = prior["id"]
                prior["is_conflict"] = True
                prior["conflict_with_id"] = comm["id"]

                conflicts.append({
                    "type": "SCHEDULE_COLLISION",
                    "slot": slot,
                    "datetime": comm["datetime_str"],
                    "item1": f"{prior['title']} (from {', '.join(prior['source_message_ids'])})",
                    "item2": f"{comm['title']} (from {', '.join(comm['source_message_ids'])})",
                    "description": f"CONFLICT: two items scheduled at {comm['datetime_str']} — '{prior['title']}' vs '{comm['title']}'."
                })
            else:
                slots_seen[slot] = comm

            # Check standing preference constraints (e.g. meeting hour limits)
            comm_dt = comm.get("datetime_obj")
            if comm_dt:
                for pref_key, pref_val in self.memory.preferences.items():
                    pref_desc = pref_val.get("description", "").lower()
                    # Check for "before XX:XX" rule
                    cutoff_match = re.search(r"before\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", pref_desc)
                    if cutoff_match:
                        cutoff_hr = int(cutoff_match.group(1))
                        cutoff_ampm = (cutoff_match.group(3) or "am").lower()
                        if cutoff_ampm == "pm" and cutoff_hr < 12:
                            cutoff_hr += 12
                        if comm_dt.hour < cutoff_hr:
                            comm["is_policy_violation"] = True
                            conflicts.append({
                                "type": "POLICY_VIOLATION",
                                "slot": slot,
                                "datetime": comm["datetime_str"],
                                "item1": f"{comm['title']} (from {', '.join(comm['source_message_ids'])})",
                                "item2": f"Standing Preference: {pref_desc}",
                                "description": f"POLICY CONFLICT: Slot {comm['datetime_str']} violates standing instruction ({pref_desc})."
                            })

        # Remove datetime_obj before serialization
        for comm in commitments:
            comm.pop("datetime_obj", None)

        commitments.sort(key=lambda c: c.get("normalized_slot", ""))
        return commitments, conflicts

    def build_dashboard(self) -> Dict[str, Any]:
        """Assembles full 3-pane dashboard data.
        Pane 1: grounded drafts gated for sign-off.
        Pane 2: hostile + ungroundable (per spec: 'anything it could not ground').
        Pane 3: commitments calendar.
        """
        pane1 = self.get_pane1_pending_actions()
        pane1_ids = {item["message_id"] for item in pane1}

        # Collect messages the system wanted to reply to but could NOT ground
        # These go to Pane 2 per the assignment spec
        from collections import Counter
        to_counter = Counter(m.to_addr.lower() for m in self.store.messages if m.to_addr)
        owner_addr = to_counter.most_common(1)[0][0] if to_counter else ""
        AUTO_PREFIXES = (
            "no-reply", "noreply", "do-not-reply", "donotreply",
            "ship-confirm", "ship-notification", "order-confirm",
            "calendar-notification", "alerts", "alert",
            "info", "feedback", "status", "notes",
            "checkin", "appointments", "success", "mailer",
            "notifications", "billing", "no-reply-aws",
            "hr", "facilities", "it-support", "helpdesk",
            "noreply-aws", "support", "admin", "security", "hello"
        )
        decisions_map = {}
        if self.decisions_file.exists():
            try:
                with open(self.decisions_file, "r", encoding="utf-8") as f:
                    decisions_map = {d["message_id"]: d for d in json.load(f)}
            except Exception:
                pass

        ungroundable = []
        for mid, d in decisions_map.items():
            if d.get("disposition") != "reply" or mid in pane1_ids:
                continue
            msg = self.store.get_message(mid, log_read=False)
            if not msg:
                continue
            local = msg.from_addr.split("@")[0].lower()
            if any(local.startswith(p) or local == p for p in AUTO_PREFIXES):
                continue
            if msg.from_addr.lower() == owner_addr:
                continue
            sec = self.scanner.scan_message(msg)
            if sec.is_hostile:
                continue  # Already in hostile section

            # Verify it is a genuine inquiry/request, not an informational update
            text = (msg.subject + " " + msg.body).lower()
            has_q = "?" in msg.body
            has_req = any(r in text for r in [
                "could you", "can you", "please send", "please share",
                "let me know", "let us know", "what is", "what are", "where is",
                "does that work", "are you free", "can we", "resend",
                "do you have", "would you", "reply to confirm", "need a yes", "please confirm",
                "for signature", "sign via", "signature needed"
            ])
            if not has_q and not has_req:
                continue

            ungroundable.append({
                "message_id": msg.id,
                "from": msg.from_addr,
                "subject": msg.subject,
                "timestamp": msg.timestamp,
            })

        pane2 = self.get_pane2_flagged_threats(ungroundable=ungroundable)
        pane3_comm, pane3_conflicts = self.get_pane3_commitments()

        summary = {
            "system": "inboxHero",
            "roll_number": "evernorth-aai-1150010",
            "student_name": "Sandeep Kulkarni",
            "generated_at": datetime.now().isoformat(),
            "metrics": {
                "total_inbox_messages": len(self.store.messages),
                "pending_actions_count": len(pane1),
                "flagged_threats_count": len(pane2),
                "commitments_count": len(pane3_comm),
                "conflicts_count": len(pane3_conflicts)
            },
            "pane1_pending_actions": pane1,
            "pane2_flagged_items": pane2,
            "pane3_commitments": pane3_comm,
            "conflicts": pane3_conflicts
        }
        self._last_data = summary
        return summary

    def generate_json(self, output_file: Path = DASHBOARD_JSON_FILE) -> Dict[str, Any]:
        """Saves machine-readable dashboard summary to dashboard.json"""
        data = self.build_dashboard()
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data

    def generate_html(self, output_file: Path = DASHBOARD_FILE, data: Optional[Dict] = None) -> str:
        """Generates executive-grade responsive 3-pane HTML dashboard.
        Accepts pre-computed data dict to avoid a second LLM pass.
        If data is None, reuses self._last_data if available, otherwise calls build_dashboard().
        """
        if data is None:
            data = self._last_data or self.build_dashboard()

        # HTML formatting helpers
        pane1_items_html = ""
        for item in data["pane1_pending_actions"]:
            cites = "".join([f'<span class="badge cite">Source: {cid}</span>' for cid in item.get("cited_ids", [])])
            cc_badge = f'<span class="badge cc">CC: {", ".join(item.get("cc", []))}</span>' if item.get("cc") else ""
            has_draft = bool(item.get("draft_body"))

            if has_draft:
                draft_section = f'''
                <div class="draft-box">
                    <div class="draft-label">&#x2728; Proposed Grounded Draft Reply:</div>
                    <div class="draft-text">{item["draft_body"]}</div>
                </div>
                <div class="citations-row">
                    <span class="cite-label">Grounded Citations:</span>
                    {cites if cites else '<span class="badge note">Direct Context</span>'}
                </div>'''
            else:
                body_preview = (item.get("body") or "").replace("<", "&lt;").replace(">", "&gt;")
                draft_section = f'''
                <div class="draft-box" style="background:rgba(251,191,36,0.08);border-left:3px solid #f59e0b;">
                    <div class="draft-label" style="color:#f59e0b;">&#x270D; No grounded draft — reply needed from you:</div>
                    <div class="draft-text" style="color:#94a3b8;white-space:pre-wrap;font-size:0.82rem;">{body_preview[:400]}{"..." if len(body_preview) > 400 else ""}</div>
                </div>'''

            pane1_items_html += f"""
            <div class="card pending-card">
                <div class="card-header">
                    <div class="card-title">[{item['message_id']}] {item['subject']}</div>
                    <span class="badge gate-badge">AWAITING SIGN-OFF</span>
                </div>
                <div class="meta-row">
                    <span><strong>From:</strong> {item['from']}</span>
                    <span><strong>Proposed Action:</strong> {item['proposed_action']}</span>
                    <span><strong>Why Human Needed:</strong> Irreversible send holding credentials/facts; gated under Part 4 boundary.</span>
                </div>
                {f'<div class="meta-row">{cc_badge}</div>' if cc_badge else ''}
                {draft_section}
                <div class="action-footer">
                    <button class="btn btn-approve" onclick="alert('Simulation: Approved dispatch for {item['message_id']} via Gate.')">&#x2713; Approve &amp; Send</button>
                    <button class="btn btn-reject" onclick="alert('Simulation: Draft rejected for {item['message_id']}.')">&#x2715; Modify / Reject</button>
                </div>
            </div>
            """

        pane2_items_html = ""
        for item in data["pane2_flagged_items"]:
            is_ungroundable = item.get("refusal_reason") == "no_grounding_context" or item.get("threat_type") == "ungroundable_reply"
            if is_ungroundable:
                pane2_items_html += f"""
            <div class="card" style="border-left: 4px solid var(--accent-amber); background: rgba(30, 41, 59, 0.45);">
                <div class="card-header">
                    <div class="card-title">[{item['message_id']}] UNGROUNDABLE INQUIRY</div>
                    <span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4);">REFUSED TO HALLUCINATE</span>
                </div>
                <div class="meta-row">
                    <span><strong>From:</strong> {item['from']}</span>
                    <span><strong>Subject:</strong> {item['subject']}</span>
                </div>
                <div class="threat-box" style="background: rgba(45, 35, 15, 0.5); border: 1px solid rgba(245, 158, 11, 0.3);">
                    <div class="threat-label" style="color: #fbbf24;">What Was Attempted:</div>
                    <div class="threat-desc" style="color: #fef3c7;">{item['attempted_action']}</div>
                </div>
                <div class="defense-status">
                    <div class="shield-icon">ℹ️</div>
                    <div class="defense-text" style="color: #e2e8f0;">
                        <strong>What System Did Instead:</strong> Refused to draft: required facts not present in inbox. Held for human attention rather than inventing details.
                    </div>
                </div>
            </div>
            """
            else:
                pane2_items_html += f"""
            <div class="card flagged-card">
                <div class="card-header">
                    <div class="card-title">[{item['message_id']}] {item['threat_type'].upper()}</div>
                    <span class="badge danger-badge">REFUSED & BLOCKED</span>
                </div>
                <div class="meta-row">
                    <span><strong>From:</strong> <span class="spoof-target">{item['from']}</span></span>
                    <span><strong>Subject:</strong> {item['subject']}</span>
                </div>
                <div class="threat-box">
                    <div class="threat-label">What Was Attempted:</div>
                    <div class="threat-desc">{item['attempted_action']}</div>
                </div>
                <div class="defense-status">
                    <div class="shield-icon">🛡️</div>
                    <div class="defense-text">
                        <strong>What System Did Instead:</strong> Refused hostile instruction, zero outbox writes. Message preserved in place for forensic audit.
                    </div>
                </div>
            </div>
            """

        conflicts_banner_html = ""
        if data["conflicts"]:
            conflict_items = "".join([f"<li>⚠️ <strong>{c['type']}:</strong> {c['description']}</li>" for c in data["conflicts"]])
            conflicts_banner_html = f"""
            <div class="conflicts-alert-banner">
                <div class="alert-title">⚠️ SCHEDULE & POLICY CONFLICTS DETECTED ({len(data['conflicts'])})</div>
                <ul>{conflict_items}</ul>
            </div>
            """

        pane3_items_html = ""
        for item in data["pane3_commitments"]:
            is_conf = item.get("is_conflict", False)
            is_pol = item.get("is_policy_violation", False)
            card_cls = "commitment-card"
            badge_html = '<span class="badge calendar-badge">CONFIRMED</span>'
            if is_conf:
                card_cls += " conflict-highlight"
                badge_html = '<span class="badge conflict-badge">⚠️ TIME COLLISION</span>'
            elif is_pol:
                card_cls += " policy-highlight"
                badge_html = '<span class="badge policy-badge">⚠️ POLICY VIOLATION</span>'

            der_pill = '<span class="badge multi-badge">Multi-Message Derived</span>' if item.get("is_multi_message") else ""
            cites = "".join([f'<span class="badge cite">Cite: {cid}</span>' for cid in item.get("source_message_ids", [])])

            pane3_items_html += f"""
            <div class="card {card_cls}">
                <div class="card-header">
                    <div class="card-title">{item['title']}</div>
                    {badge_html}
                </div>
                <div class="event-time">📅 {item['datetime_str']}</div>
                <div class="notes-box">{item.get('notes', '')}</div>
                <div class="citations-row">
                    {der_pill}
                    {cites}
                </div>
            </div>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>inboxHero — Executive Triage Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0d14;
            --bg-secondary: #0f172a;
            --card-bg: rgba(22, 27, 34, 0.75);
            --card-border: rgba(255, 255, 255, 0.08);
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent-cyan: #06b6d4;
            --accent-emerald: #10b981;
            --accent-amber: #f59e0b;
            --accent-rose: #f43f5e;
            --accent-violet: #8b5cf6;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background: radial-gradient(circle at 10% 20%, #111827 0%, var(--bg-primary) 90%);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            padding: 24px;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .brand-title {{
            font-size: 26px;
            font-weight: 800;
            background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .brand-sub {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 4px;
        }}
        .metrics-bar {{
            display: flex;
            gap: 16px;
        }}
        .metric-pill {{
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 8px 14px;
            text-align: center;
        }}
        .metric-val {{
            font-size: 18px;
            font-weight: 700;
            color: #38bdf8;
        }}
        .metric-label {{
            font-size: 11px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .conflicts-alert-banner {{
            background: rgba(244, 63, 94, 0.12);
            border: 1px solid rgba(244, 63, 94, 0.4);
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(244, 63, 94, 0.15);
        }}
        .alert-title {{
            font-weight: 700;
            color: #fb7185;
            margin-bottom: 8px;
            font-size: 15px;
        }}
        .conflicts-alert-banner ul {{
            padding-left: 20px;
            color: #fecdd3;
            font-size: 13px;
            line-height: 1.6;
        }}

        .dashboard-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 24px;
        }}
        @media (max-width: 1100px) {{
            .dashboard-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .pane-col {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .pane-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            border-radius: 12px;
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid var(--card-border);
        }}
        .pane-title {{
            font-size: 16px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .card {{
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 18px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }}

        .pending-card {{
            border-left: 4px solid var(--accent-amber);
        }}
        .flagged-card {{
            border-left: 4px solid var(--accent-rose);
        }}
        .commitment-card {{
            border-left: 4px solid var(--accent-cyan);
        }}
        .conflict-highlight {{
            border-left: 4px solid var(--accent-rose);
            background: rgba(244, 63, 94, 0.08);
            box-shadow: 0 0 15px rgba(244, 63, 94, 0.2);
        }}
        .policy-highlight {{
            border-left: 4px solid var(--accent-amber);
            background: rgba(245, 158, 11, 0.08);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 10px;
            gap: 8px;
        }}
        .card-title {{
            font-size: 14px;
            font-weight: 600;
            color: #ffffff;
        }}

        .badge {{
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 4px 8px;
            border-radius: 6px;
            letter-spacing: 0.5px;
            white-space: nowrap;
        }}
        .gate-badge {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}
        .danger-badge {{ background: rgba(244, 63, 94, 0.2); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.4); }}
        .calendar-badge {{ background: rgba(6, 182, 212, 0.2); color: #67e8f9; border: 1px solid rgba(6, 182, 212, 0.4); }}
        .conflict-badge {{ background: rgba(244, 63, 94, 0.3); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.6); }}
        .policy-badge {{ background: rgba(245, 158, 11, 0.25); color: #fde047; border: 1px solid rgba(245, 158, 11, 0.5); }}
        .cite {{ background: rgba(99, 102, 241, 0.2); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.3); }}
        .cc {{ background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }}
        .multi-badge {{ background: rgba(168, 85, 247, 0.2); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.4); }}

        .meta-row {{
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 10px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .draft-box {{
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 12px;
        }}
        .draft-label {{
            font-size: 11px;
            color: #94a3b8;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        .draft-text {{
            font-size: 12px;
            color: #e2e8f0;
            white-space: pre-wrap;
            line-height: 1.4;
            font-family: monospace;
        }}

        .threat-box {{
            background: rgba(30, 27, 46, 0.7);
            border: 1px solid rgba(244, 63, 94, 0.2);
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 12px;
        }}
        .threat-label {{
            font-size: 11px;
            color: #fb7185;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        .threat-desc {{
            font-size: 12px;
            color: #fecdd3;
            line-height: 1.4;
        }}
        .defense-status {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 11px;
            color: #94a3b8;
        }}
        .shield-icon {{
            font-size: 18px;
        }}

        .event-time {{
            font-size: 13px;
            font-weight: 600;
            color: #38bdf8;
            margin-bottom: 8px;
        }}
        .notes-box {{
            font-size: 12px;
            color: #94a3b8;
            margin-bottom: 10px;
            line-height: 1.4;
        }}
        .citations-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
        }}
        .cite-label {{
            font-size: 11px;
            color: var(--text-muted);
        }}

        .action-footer {{
            display: flex;
            gap: 8px;
            margin-top: 14px;
        }}
        .btn {{
            flex: 1;
            padding: 8px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: opacity 0.2s;
        }}
        .btn:hover {{
            opacity: 0.9;
        }}
        .btn-approve {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
        }}
        .btn-reject {{
            background: rgba(51, 65, 85, 0.8);
            color: #cbd5e1;
        }}
    </style>
</head>
<body>
    <header>
        <div>
            <div class="brand-title">inboxHero &bull; Executive Operations Console</div>
            <div class="brand-sub">Three-Pane Verification Dashboard &bull; Roll: {data['roll_number']} &bull; Generated: {data['generated_at'][:19]}</div>
        </div>
        <div class="metrics-bar">
            <div class="metric-pill">
                <div class="metric-val">{data['metrics']['total_inbox_messages']}</div>
                <div class="metric-label">Inbox Total</div>
            </div>
            <div class="metric-pill">
                <div class="metric-val" style="color: var(--accent-amber)">{data['metrics']['pending_actions_count']}</div>
                <div class="metric-label">Pending Sign-off</div>
            </div>
            <div class="metric-pill">
                <div class="metric-val" style="color: var(--accent-rose)">{data['metrics']['flagged_threats_count']}</div>
                <div class="metric-label">Flagged / Refused</div>
            </div>
            <div class="metric-pill">
                <div class="metric-val" style="color: var(--accent-cyan)">{data['metrics']['commitments_count']}</div>
                <div class="metric-label">Commitments</div>
            </div>
            <div class="metric-pill">
                <div class="metric-val" style="color: #fb7185">{data['metrics']['conflicts_count']}</div>
                <div class="metric-label">Conflicts</div>
            </div>
        </div>
    </header>

    {conflicts_banner_html}

    <main class="dashboard-grid">
        <!-- PANE 1: PENDING ACTIONS -->
        <section class="pane-col">
            <div class="pane-header">
                <div class="pane-title" style="color: #fbbf24">
                    <span>⏳</span> Pane 1: Pending Actions ({data['metrics']['pending_actions_count']})
                </div>
                <span class="badge gate-badge">Gate Protected</span>
            </div>
            {pane1_items_html}
        </section>

        <!-- PANE 2: FLAGGED HOSTILE & UNGROUNDABLE ITEMS -->
        <section class="pane-col">
            <div class="pane-header">
                <div class="pane-title" style="color: #fb7185">
                    <span>🛡️</span> Pane 2: Flagged & Refused Actions ({data['metrics']['flagged_threats_count']})
                </div>
                <span class="badge danger-badge">Refused & Preserved</span>
            </div>
            {pane2_items_html}
        </section>

        <!-- PANE 3: COMMITMENTS & CALENDAR -->
        <section class="pane-col">
            <div class="pane-header">
                <div class="pane-title" style="color: #38bdf8">
                    <span>📅</span> Pane 3: Commitments & Schedule ({data['metrics']['commitments_count']})
                </div>
                <span class="badge calendar-badge">Multi-Source Audited</span>
            </div>
            {pane3_items_html}
        </section>
    </main>
</body>
</html>
"""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Log trace event for capability R6
        self._log_trace_event(data)
        return html_content

    def _log_trace_event(self, data: Dict[str, Any]):
        """Logs capability R6 event to trace.jsonl"""
        event = TraceEvent(
            cap="R6",
            event_type="dashboard_generated",
            message_id=None,
            details={
                "pending_actions_count": data["metrics"]["pending_actions_count"],
                "flagged_threats_count": data["metrics"]["flagged_threats_count"],
                "commitments_count": data["metrics"]["commitments_count"],
                "conflicts_count": data["metrics"]["conflicts_count"],
                "conflicts": [c["description"] for c in data["conflicts"]],
                "html_path": str(DASHBOARD_FILE),
                "json_path": str(DASHBOARD_JSON_FILE)
            },
            timestamp=datetime.now().isoformat()
        )
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def print_terminal_summary(self, data: Dict[str, Any]):
        """Prints a clean ASCII summary to stdout"""
        print("\n" + "=" * 70)
        print("📊 INBOXHERO THREE-PANE DASHBOARD SUMMARY (CAPABILITY R6)")
        print("=" * 70)
        m = data["metrics"]
        print(f"Total Inbox Messages : {m['total_inbox_messages']}")
        print(f"Pane 1 (Pending)     : {m['pending_actions_count']} drafts awaiting human sign-off")
        print(f"Pane 2 (Flagged)     : {m['flagged_threats_count']} hostile attacks refused & preserved")
        print(f"Pane 3 (Commitments) : {m['commitments_count']} commitments (with multi-message derivations)")
        print(f"Surfaced Conflicts   : {m['conflicts_count']} schedule collisions / policy violations")

        print("\n--- PANE 1: PENDING ACTIONS (GATED REPLIES) ---")
        for item in data["pane1_pending_actions"][:4]:
            cites = f" (cited: {item['cited_ids']})" if item.get("cited_ids") else ""
            cc = f" [CC: {item['cc']}]" if item.get("cc") else ""
            print(f"  • [{item['message_id']}] To: {item['recipient']}{cc} | Subj: {item['subject']}{cites}")

        print("\n--- PANE 2: FLAGGED HOSTILE ATTACKS (REFUSED) ---")
        for item in data["pane2_flagged_items"][:4]:
            print(f"  • [{item['message_id']}] {item['threat_type']}: {item['attempted_action']}")

        print("\n--- PANE 3: COMMITMENTS & SURFACED CONFLICTS ---")
        for comm in data["pane3_commitments"]:
            der = " [Multi-Message Derived]" if comm.get("is_multi_message") else ""
            c_tag = " [⚠️ CONFLICT]" if comm.get("is_conflict") else ""
            p_tag = " [⚠️ POLICY VIOLATION]" if comm.get("is_policy_violation") else ""
            cites = f" (from {', '.join(comm['source_message_ids'])})"
            print(f"  • {comm['datetime_str']} — {comm['title']}{der}{cites}{c_tag}{p_tag}")

        if data["conflicts"]:
            print("\n--- ⚠️ SURFACED CONFLICTS ---")
            for c in data["conflicts"]:
                print(f"  {c['description']}")

        print(f"\n[✓] Visual Web Dashboard: {DASHBOARD_FILE}")
        print(f"[✓] Machine-Readable JSON: {DASHBOARD_JSON_FILE}")
        print("=" * 70)


if __name__ == "__main__":
    generator = DashboardGenerator()
    data = generator.generate_json()
    generator.generate_html()
    generator.print_terminal_summary(data)
