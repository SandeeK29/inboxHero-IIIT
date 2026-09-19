# Roll Number: evernorth-aai-1150010
# Student: Sandeep Kulkarni
"""
Generic Rule-Based Triage Engine for Project inboxHero (Part 2 / Capability R1)
Deterministically routes obvious noise, receipts, notifications, and digests
WITHOUT calling an LLM, reducing latency, API cost, and hallucination risk.
Uses generalized email patterns rather than hardcoded inbox addresses.
"""

from typing import Optional
import re
from schemas import Message, Decision, DispositionType


# Standard automated sender prefixes found across email services
AUTOMATED_PREFIXES = (
    "no-reply@",
    "noreply@",
    "no_reply@",
    "receipts@",
    "billing@",
    "orders@",
    "invoicing@",
    "invoice+",
    "alerts@",
    "notifications@",
    "notify@",
    "updates@",
    "newsletter@",
    "newsletters@",
    "digest@",
    "marketing@",
    "support@",
    "feedback@",
    "insights@",
)

# Common keywords indicating automated or transactional emails
TRANSACTIONAL_SUBJECT_KEYWORDS = [
    "receipt",
    "invoice",
    "statement",
    "bill is ready",
    "payment received",
    "payout is on the way",
    "order is delivered",
    "your order",
]

MONITORING_SUBJECT_KEYWORDS = [
    "uptime report",
    "monitor ok",
    "analytics",
    "system status",
    "incident resolved",
    "recording is ready",
    "actions minutes",
]

DIGEST_SUBJECT_KEYWORDS = [
    "daily digest",
    "weekly digest",
    "daily newsletter",
    "weekly newsletter",
    "roundup",
    "weekly activity",
    "monthly summary",
    "daily summary",
]


def evaluate_rules(msg: Message) -> Optional[Decision]:
    """
    Evaluates a message against deterministic, generic email rules.
    Returns Decision if matched, or None if the message requires model analysis.
    
    IMPORTANT SAFETY CHECK:
    Hostile prompt injections or financial phishing must NEVER be auto-archived.
    They are screened out from rule bypass.
    """
    from_l = msg.from_addr.lower()
    subj_l = msg.subject.lower()
    body_l = msg.body.lower()

    # Safety Guard: If there is any indicator of prompt injection or financial urgency,
    # do NOT bypass to rules. Must go through security / model inspection.
    if any(k in body_l or k in subj_l for k in [
        "ignore all previous instructions",
        "ignore previous",
        "system notice",
        "assistant configuration",
        "autonomous mode",
        "updated remittance details",
        "banking partner has changed",
        "password expires",
        "re-verify your credentials",
        "wire $",
    ]):
        return None

    # 1. Billing & Transactional Receipts
    if from_l.startswith(AUTOMATED_PREFIXES) and any(k in subj_l for k in TRANSACTIONAL_SUBJECT_KEYWORDS):
        return Decision(
            message_id=msg.id,
            disposition=DispositionType.ARCHIVE,
            reason="Automated transactional receipt / billing statement",
            handled_by="rule"
        )

    # Any sender starting with receipts@, billing@, or orders@
    if from_l.startswith(("receipts@", "billing@", "orders@", "invoicing@")):
        return Decision(
            message_id=msg.id,
            disposition=DispositionType.ARCHIVE,
            reason="Automated billing / payment notification",
            handled_by="rule"
        )

    # 2. Infrastructure & Monitoring Alerts
    if from_l.startswith(AUTOMATED_PREFIXES) and any(k in subj_l for k in MONITORING_SUBJECT_KEYWORDS):
        return Decision(
            message_id=msg.id,
            disposition=DispositionType.ARCHIVE,
            reason="Automated infrastructure monitoring / operational alert",
            handled_by="rule"
        )

    # 3. Newsletters & Reading Digests
    if from_l.startswith(("newsletter@", "digest@")) or any(k in subj_l for k in DIGEST_SUBJECT_KEYWORDS):
        return Decision(
            message_id=msg.id,
            disposition=DispositionType.ARCHIVE,
            reason="Periodic marketing newsletter / content digest",
            handled_by="rule"
        )

    # 4. Social & Platform Activity Notifications (no-reply notification digests)
    if from_l.startswith(("notifications@", "notify@", "updates@", "insights@")):
        return Decision(
            message_id=msg.id,
            disposition=DispositionType.ARCHIVE,
            reason="Automated SaaS platform notification / activity alert",
            handled_by="rule"
        )

    # No generic rule match -> Message requires semantic analysis by the model
    return None
