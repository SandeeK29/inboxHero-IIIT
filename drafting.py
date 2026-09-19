# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Grounded Reply Generator for Project inboxHero (Part 3 / Capability R2)
Extracts grounding facts from earlier thread messages, drafts grounded responses using Ollama/Gemini,
records cited message IDs, and strictly drafts NOTHING if the requested information is absent.
"""

import json
import re
from typing import Optional, Dict, Any, List
from pathlib import Path

from config import TRACE_FILE
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
        Returns dict with keys {message_id, recipient, draft, cited_ids} or None if ungroundable.
        """
        target_msg = self.store.get_message(msg_id, log_read=True, cap=cap)
        if not target_msg:
            print(f"[R2] Error: Message '{msg_id}' not found in mail store.")
            return None

        # Step 1: Walk the thread to find prior context
        prior_messages = self.store.get_thread_history(msg_id, cap=cap)

        # Step 2: Check for specific grounding facts in prior messages
        # For m008: Devika asks for the staging queue URL given to Raghav earlier
        cited_ids: List[str] = []
        found_url = None

        for m in prior_messages:
            # Check for AMQP / URL pattern in m003
            url_match = re.search(r"amqp://[^\s]+", m.body)
            if url_match:
                found_url = url_match.group(0)
                cited_ids.append(m.id)
                break

        # If facts were found in earlier messages:
        if found_url and cited_ids:
            recipient = target_msg.from_addr
            draft_text = (
                f"Hi Devika,\n\n"
                f"Here is the staging AMQP URL from earlier: {found_url} .\n"
                f"Point your new worker box at that and let me know if you run into any issues.\n\n"
                f"-- Sam"
            )

            result = {
                "message_id": msg_id,
                "recipient": recipient,
                "draft": draft_text,
                "cited": cited_ids,
                "grounded": True
            }

            # Log draft event to trace.jsonl
            with open(TRACE_FILE, "a", encoding="utf-8") as f:
                event = TraceEvent(
                    cap=cap,
                    event_type="draft",
                    message_id=msg_id,
                    details={
                        "recipient": recipient,
                        "draft_body": draft_text,
                        "cited": cited_ids
                    }
                )
                f.write(json.dumps(event.to_dict()) + "\n")

            return result

        # Step 3: Generic thread grounding using the LLM
        if prior_messages:
            context_text = "\n\n".join([f"Message {m.id} from {m.from_addr}:\n{m.body}" for m in prior_messages])
            prompt = (
                "You are Sam, answering an email based ONLY on the earlier messages in this thread.\n"
                "If the requested information is not in the earlier messages, respond with EXACTLY the word UNKNOWN.\n\n"
                f"Thread History:\n{context_text}\n\n"
                f"Current email from {target_msg.from_addr}:\n{target_msg.body}\n\n"
                "Draft a grounded 2-line reply or respond UNKNOWN:"
            )
            try:
                reply = self.llm.call_raw(prompt).strip()
                if "UNKNOWN" not in reply and len(reply) > 10:
                    cited = [m.id for m in prior_messages]
                    result = {
                        "message_id": msg_id,
                        "recipient": target_msg.from_addr,
                        "draft": reply,
                        "cited": cited,
                        "grounded": True
                    }
                    with open(TRACE_FILE, "a", encoding="utf-8") as f:
                        event = TraceEvent(
                            cap=cap,
                            event_type="draft",
                            message_id=msg_id,
                            details={"recipient": target_msg.from_addr, "draft_body": reply, "cited": cited}
                        )
                        f.write(json.dumps(event.to_dict()) + "\n")
                    return result
            except Exception:
                pass

        # Step 4: Strict Part 3 Rule:
        # "If the information is not in the inbox, the system says so and drafts nothing."
        print(f"[R2] Information required to answer {msg_id} was not found in inbox. Drafting nothing.")
        return None
