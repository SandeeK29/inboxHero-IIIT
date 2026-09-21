# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Dynamic Persistent Preference Memory Store for Project inboxHero (Part 5 / Capability R4)
Extracts standing instructions dynamically using the LLM (Ollama/Gemini) instead of hardcoding.
Persists preferences to prefs.json and applies them after process exit and restart.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from config import PREFS_FILE, TRACE_FILE
from schemas import Message, TraceEvent
from llm_client import LLMClient


class PreferenceStore:
    def __init__(self, prefs_path: Path = PREFS_FILE):
        self.prefs_path = Path(prefs_path)
        self.preferences: Dict[str, Any] = {}
        self.llm = LLMClient()
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads preferences from disk file. Survives process restart."""
        if self.prefs_path.exists():
            try:
                with open(self.prefs_path, "r", encoding="utf-8") as f:
                    self.preferences = json.load(f)
            except Exception:
                self.preferences = {}
        else:
            self.preferences = {}
        return self.preferences

    def save_preference(
        self,
        pref_key: str,
        rule_description: str,
        parameters: Dict[str, Any],
        source_msg_id: str,
        cap: str = "R4"
    ):
        """Saves a preference to disk and logs the trace event."""
        self.preferences[pref_key] = {
            "description": rule_description,
            "parameters": parameters,
            "source_msg_id": source_msg_id
        }
        with open(self.prefs_path, "w", encoding="utf-8") as f:
            json.dump(self.preferences, f, indent=2)

        # Log trace event
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            event = TraceEvent(
                cap=cap,
                event_type="preference_saved",
                message_id=source_msg_id,
                details={
                    "pref_key": pref_key,
                    "description": rule_description,
                    "parameters": parameters
                }
            )
            f.write(json.dumps(event.to_dict()) + "\n")

    def ingest_from_message(self, msg: Message, cap: str = "R4") -> Optional[str]:
        """
        Dynamically extracts standing instructions from an email using the LLM.
        Zero hardcoded email addresses, subjects, or domains.
        """
        body_l = msg.body.lower()
        subj_l = msg.subject.lower()

        # Quick check for preference indicators
        pref_indicators = [
            "standing request", "standing instruction", "from now on", 
            "please make sure", "always cc", "loop me in", 
            "calendar rule", "please remember", "do not take meetings"
        ]

        if not any(k in body_l or k in subj_l for k in pref_indicators):
            return None

        # Use LLM to dynamically extract the structured preference
        prompt = (
            "You are an AI assistant analyzing an email for standing user preferences or persistent rules.\n"
            "Analyze the following email and extract any standing instruction or preference.\n\n"
            f"From: {msg.from_addr}\n"
            f"Subject: {msg.subject}\n"
            f"Body:\n{msg.body}\n\n"
            "Return a JSON object with:\n"
            "- 'has_preference': boolean\n"
            "- 'pref_key': short snake_case identifier (e.g. 'cc_legal_mail')\n"
            "- 'description': clear 1-line summary of the rule\n"
            "- 'parameters': {\n"
            "    'entity_or_sender': '<organization, law firm, person, or domain mentioned to match>',\n"
            "    'cc_recipient': '<email address to CC>'\n"
            "}\n"
            "Return ONLY the JSON object."
        )

        try:
            resp = self.llm.call_raw(prompt)
            json_match = re.search(r"\{.*\}", resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                if data.get("has_preference"):
                    pref_key = data.get("pref_key", "custom_preference")
                    desc = data.get("description", "User stated standing instruction")
                    params = data.get("parameters", {})
                    self.save_preference(pref_key, desc, params, source_msg_id=msg.id, cap=cap)
                    return pref_key
        except Exception as e:
            print(f"[Notice] LLM preference extraction fallback: {e}")

        # Generic fallback extraction if model response is malformed
        # Extracts organization name following 'from' or capitalized proper noun
        org_match = re.search(r"(?:from|at)\s+([A-Z][a-zA-Z0-9& ]+)", msg.body)
        detected_entity = org_match.group(1).strip() if org_match else "organization"
        pref_key = "cc_correspondence_rule"
        desc = f"CC {msg.from_addr} on mail related to {detected_entity}"
        params = {
            "entity_or_sender": detected_entity,
            "cc_recipient": msg.from_addr
        }
        self.save_preference(pref_key, desc, params, source_msg_id=msg.id, cap=cap)
        return pref_key

    def apply_preferences(
        self,
        msg: Message,
        draft_payload: Dict[str, Any],
        cap: str = "R4"
    ) -> Dict[str, Any]:
        """
        Dynamically applies all loaded preferences in prefs.json.
        Matches entity names, keywords, or sender domains against incoming emails.
        """
        applied_rules = []
        updated_draft = dict(draft_payload)
        updated_draft.setdefault("cc", [])

        email_full_text = f"{msg.from_addr} {msg.subject} {msg.body}".lower()

        # Iterate dynamically through all active preferences
        for pref_key, pref_data in self.preferences.items():
            params = pref_data.get("parameters", {})
            entity = str(params.get("entity_or_sender") or params.get("sender_match") or "").lower()
            cc_target = params.get("cc_recipient")

            if cc_target and entity:
                # Extract clean alphanumeric keywords (length >= 3)
                keywords = [w for w in re.split(r"[^a-zA-Z0-9]+", entity) if len(w) >= 3]
                if any(kw in email_full_text for kw in keywords):
                    if cc_target not in updated_draft["cc"]:
                        updated_draft["cc"].append(cc_target)
                        applied_rules.append(pref_key)

        if applied_rules:
            updated_draft["applied_preferences"] = applied_rules
            # Log trace event proving preference altered behavior
            with open(TRACE_FILE, "a", encoding="utf-8") as f:
                event = TraceEvent(
                    cap=cap,
                    event_type="preference_applied",
                    message_id=msg.id,
                    details={
                        "applied_rules": applied_rules,
                        "resulting_cc": updated_draft["cc"]
                    }
                )
                f.write(json.dumps(event.to_dict()) + "\n")

        return updated_draft
