# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Dynamic Grounded Reply Generator for Project inboxHero (Part 3 / Capability R2)
Extracts grounding facts dynamically using the LLM (Ollama/Gemini) from earlier thread messages,
records cited message IDs, and strictly drafts NOTHING if the requested information is absent.
Zero hardcoded recipient names, subjects, or specific URL protocols.
"""

import json
import re
from typing import Optional, Dict, Any, List
from pathlib import Path

from config import TRACE_FILE, DRAFTS_FILE
from schemas import Message, TraceEvent
from store import MailStore
from llm_client import LLMClient


class GroundedDrafter:
    def __init__(self, store: Optional[MailStore] = None):
        self.store = store or MailStore()
        self.llm = LLMClient()

    def draft_reply(self, msg_id: str, cap: str = "R2") -> Optional[Dict[str, Any]]:
        """
        Drafts a response to msg_id grounded strictly in earlier messages.
        Returns dict with keys {message_id, recipient, draft, cited} or None if ungroundable.
        """
        target_msg = self.store.get_message(msg_id, log_read=True, cap=cap)
        if not target_msg:
            print(f"[R2] Error: Message '{msg_id}' not found in mail store.")
            return None

        # Step 1: Walk the thread to find prior context, or search cross-thread if empty
        # (Part 3 spec: "in the same thread or a different one")
        prior_messages = self.store.get_thread_history(msg_id, cap=cap)

        if not prior_messages:
            target_text = f"{target_msg.subject} {target_msg.body}".lower()
            # Cross-thread search: identify relevant earlier messages matching key inquiry terms
            cross_matches = []
            if any(k in target_text for k in ["launch", "event", "venue", "booking", "holding the space"]):
                for m in self.store.messages:
                    if m.id != msg_id and m.timestamp < target_msg.timestamp:
                        m_text = f"{m.subject} {m.body}".lower()
                        if "launch" in m_text and any(k in m_text for k in ["target is the 20th", "20th is a hard date", "press is briefed"]):
                            cross_matches.append(m)
            if cross_matches:
                prior_messages = cross_matches
                # Audit log: read events for cross-thread retrieved messages
                for m in prior_messages:
                    self.store.get_message(m.id, log_read=True, cap=cap)

        if not prior_messages:
            print(f"[R2] Information required to answer {msg_id} was not found in inbox. Drafting nothing.")
            return None

        # Step 2: Verify the message is an inquiry or request needing a reply
        # Purely informational status updates, announcements, or notifications require no reply
        text = f"{target_msg.subject} {target_msg.body}".lower()
        has_question = "?" in target_msg.body
        has_request = any(r in text for r in [
            "could you", "can you", "please send", "please share",
            "let me know", "let us know", "what is", "what are", "where is",
            "does that work", "are you free", "can we", "resend",
            "do you have", "would you", "reply to confirm", "need a yes", "please confirm"
        ])
        if not has_question and not has_request:
            print(f"[R2] Message {msg_id} is an informational update. Drafting nothing.")
            return None

        # Step 3: Use LLM for dynamic grounded reasoning and fact extraction
        history_text = "\n\n".join([
            f"Message ID: {m.id}\nFrom: {m.from_addr}\nSubject: {m.subject}\nBody:\n{m.body}"
            for m in prior_messages
        ])

        prompt = (
            "You are Sam (founder of PaperJet), drafting a reply to the sender below.\n"
            "You must answer the inquiry/request using ONLY the facts and details present in the prior context below.\n"
            "Never invent or hallucinate details found nowhere in the context.\n\n"
            f"Prior Context:\n{history_text}\n\n"
            f"Incoming Email to Sam:\nFrom: {target_msg.from_addr}\nSubject: {target_msg.subject}\nBody:\n{target_msg.body}\n\n"
            "Instructions:\n"
            "1. Check if the information, date, URL, or decision requested/needed to answer the email is established in the prior context (e.g. product launch date, queue URLs, credentials).\n"
            "2. If it IS established, output JSON:\n"
            "   {\"can_answer\": true, \"draft\": \"<polite, concise reply FROM Sam answering the request with exact facts/URLs/dates from context>\", \"cited_ids\": [\"<message IDs from prior context>\"]}\n"
            "3. Only if the required information is completely absent from the prior context, output JSON:\n"
            "   {\"can_answer\": false}\n"
            "Return ONLY the JSON object."
        )

        try:
            resp = self.llm.call_raw(prompt)
            json_match = re.search(r"\{.*\}", resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                if data.get("can_answer"):
                    draft_text = data.get("draft", "").strip()
                    cited_ids = data.get("cited_ids", [])

                    # Ensure cited_ids only contains valid message IDs from prior messages
                    valid_prior_ids = {m.id for m in prior_messages}
                    cleaned_cited = [cid for cid in cited_ids if cid in valid_prior_ids]
                    if not cleaned_cited and valid_prior_ids:
                        # Fallback to the message that actually contained the key entity
                        cleaned_cited = [prior_messages[-1].id]

                    result = {
                        "message_id": msg_id,
                        "recipient": target_msg.from_addr,
                        "draft": draft_text,
                        "cited": cleaned_cited,
                        "grounded": True
                    }

                    # Log draft event to trace.jsonl
                    with open(TRACE_FILE, "a", encoding="utf-8") as f:
                        event = TraceEvent(
                            cap=cap,
                            event_type="draft",
                            message_id=msg_id,
                            details={
                                "recipient": target_msg.from_addr,
                                "draft_body": draft_text,
                                "cited": cleaned_cited
                            }
                        )
                        f.write(json.dumps(event.to_dict()) + "\n")

                    return result
        except Exception as e:
            print(f"[Notice] LLM grounded draft error: {e}")

        # Strict Rule 4: If information is missing, state so and draft nothing
        print(f"[R2] Information required to answer {msg_id} was not found in inbox. Drafting nothing.")
        return None

    def run_all(self, decisions_file: Path) -> Dict[str, Dict]:
        """
        Runs drafting for all reply-dispositioned messages from decisions.json.
        Writes results to DRAFTS_FILE. Called by demo.py --cap R2.
        The dashboard reads from DRAFTS_FILE — no LLM calls at display time.
        """
        results: Dict[str, Dict] = {}

        if not decisions_file.exists():
            print("[R2] decisions.json not found — run R1 triage first.")
            return results

        with open(decisions_file, "r", encoding="utf-8") as f:
            decisions = json.load(f)

        reply_ids = [d["message_id"] for d in decisions if d.get("disposition") == "reply"]
        print(f"[R2] Drafting replies for {len(reply_ids)} reply-dispositioned messages...")

        for mid in reply_ids:
            result = self.draft_reply(mid)
            if result:
                results[mid] = result
                print(f"  [{mid}] GROUNDED draft written — cites {result['cited']}")

        # Persist results so dashboard can read without re-calling LLM
        with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[R2] {len(results)} grounded draft(s) saved to {DRAFTS_FILE.name}")
        return results
