"""Conservative escalation floor; a model cannot clear these cases for automation.

Keyword coverage is deliberately supplementary. It does not establish customer identity
or replace tool authorization, send checks, or an operator's review.
"""
import re

SENSITIVE = re.compile(r'\b(booking|refund\w*|cancel\w*|order|payment|password\w*|account|invoice|credit|card|credential\w*|api\s+key|system\s+prompt)\b', re.I)
PRIVACY = re.compile(r"\b(other|another)\s+customer(?:'s|s)?\b", re.I)
UNCERTAIN = re.compile(r"\b(cannot|can't|unable|unavailable|not available|not confirmed|human|investigate|unconfirmed)\b", re.I)


def requires_review(content, reply):
    return bool(SENSITIVE.search(content) or PRIVACY.search(content) or UNCERTAIN.search(reply))
