# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Data Schemas for Project inboxHero
Defines typed models for emails, dispositions, gate actions, commitments, and traces.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum


class DispositionType(str, Enum):
    REPLY = "reply"
    ARCHIVE = "archive"
    DEFER = "defer"
    DELEGATE = "delegate"
    ESCALATE = "escalate"


@dataclass
class Message:
    id: str
    thread_id: str
    from_addr: str
    to_addr: str
    subject: str
    timestamp: str
    body: str
    unread: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            id=data["id"],
            thread_id=data["thread_id"],
            from_addr=data.get("from", ""),
            to_addr=data.get("to", ""),
            subject=data.get("subject", ""),
            timestamp=data.get("timestamp", ""),
            body=data.get("body", ""),
            unread=data.get("unread", False)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "from": self.from_addr,
            "to": self.to_addr,
            "subject": self.subject,
            "timestamp": self.timestamp,
            "body": self.body,
            "unread": self.unread
        }


@dataclass
class Decision:
    message_id: str
    disposition: DispositionType
    reason: str
    handled_by: str  # "rule" or "model"
    proposed_action: Optional[str] = None
    recipient: Optional[str] = None
    draft_body: Optional[str] = None
    cited_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["disposition"] = self.disposition.value
        return d


@dataclass
class GateDecision:
    message_id: str
    action: str  # "send", "delete"
    is_reversible: bool
    proposed_content: str
    recipient: str
    status: str  # "approved", "rejected", "dry_run"
    human_comment: Optional[str] = None


@dataclass
class Commitment:
    id: str
    title: str
    datetime_str: str
    source_message_ids: List[str]
    notes: str = ""
    is_conflict: bool = False
    conflict_with_id: Optional[str] = None


@dataclass
class TraceEvent:
    cap: str  # "R1", "R2", etc.
    event_type: str  # "decision", "draft", "gate", "refusal", "read"
    message_id: Optional[str]
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
