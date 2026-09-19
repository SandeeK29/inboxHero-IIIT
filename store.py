# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Mail Store and Thread-Walking Retrieval for Project inboxHero (Part 3 / Capability R2)
Indexes inbox messages by ID and Thread ID, enables deterministic thread-walking,
and logs 'read' events to trace.jsonl to verify that cited messages were genuinely read.
"""

import json
from typing import List, Dict, Optional, Set
from pathlib import Path

from config import INBOX_FILE, TRACE_FILE
from schemas import Message, TraceEvent


class MailStore:
    def __init__(self, inbox_path: Path = INBOX_FILE):
        self.inbox_path = inbox_path
        self.messages: List[Message] = []
        self.by_id: Dict[str, Message] = {}
        self.by_thread: Dict[str, List[Message]] = {}
        self._load_store()

    def _load_store(self):
        """Loads and indexes all messages from the inbox file."""
        with open(self.inbox_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        self.messages = [Message.from_dict(m) for m in raw_data]
        self.by_id = {m.id: m for m in self.messages}

        # Index by thread_id, sorted chronologically
        self.by_thread = {}
        for m in self.messages:
            self.by_thread.setdefault(m.thread_id, []).append(m)

        for thread_id in self.by_thread:
            self.by_thread[thread_id].sort(key=lambda x: x.timestamp)

    def log_read_event(self, msg_id: str, cap: str = "R2", context: str = "thread-walk"):
        """Logs a 'read' event to trace.jsonl to prove the message was examined."""
        msg = self.by_id.get(msg_id)
        if not msg:
            return
        event = TraceEvent(
            cap=cap,
            event_type="read",
            message_id=msg_id,
            details={
                "thread_id": msg.thread_id,
                "from": msg.from_addr,
                "subject": msg.subject,
                "context": context
            }
        )
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def get_message(self, msg_id: str, log_read: bool = True, cap: str = "R2") -> Optional[Message]:
        """Retrieves a message by ID and logs the read event."""
        msg = self.by_id.get(msg_id)
        if msg and log_read:
            self.log_read_event(msg_id, cap=cap, context="direct-lookup")
        return msg

    def get_thread_history(self, msg_id: str, cap: str = "R2") -> List[Message]:
        """
        Retrieves all prior messages in the thread before the given message ID.
        Walks backwards along the thread and logs each accessed message as 'read'.
        """
        target_msg = self.by_id.get(msg_id)
        if not target_msg:
            return []

        # Target message itself was read
        self.log_read_event(msg_id, cap=cap, context="target-message")

        thread_msgs = self.by_thread.get(target_msg.thread_id, [])
        prior_messages = []
        for m in thread_msgs:
            if m.timestamp < target_msg.timestamp:
                prior_messages.append(m)
                # Log read event for earlier message in thread
                self.log_read_event(m.id, cap=cap, context="thread-history")

        return prior_messages

    def search_keyword(self, query: str, cap: str = "R2") -> List[Message]:
        """
        Fallback keyword search across the entire inbox.
        Logs read events for any returned matches.
        """
        q = query.lower()
        matches = []
        for m in self.messages:
            if q in m.subject.lower() or q in m.body.lower():
                matches.append(m)
                self.log_read_event(m.id, cap=cap, context=f"keyword-search:'{query}'")
        return matches
