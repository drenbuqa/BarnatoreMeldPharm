import hashlib
import os
import re
import secrets
from datetime import datetime

from bson import ObjectId
from flask import g, has_request_context, request

# Known bot/crawler User-Agent substrings (case-insensitive)
_BOT_PATTERNS = re.compile(
    r'bot|crawl|spider|slurp|facebookexternalhit|meta-externalagent|'
    r'Twitterbot|LinkedInBot|WhatsApp|TelegramBot|Applebot|Bingbot|'
    r'DuckDuckBot|YandexBot|Baidu|Sogou|Exabot|ia_archiver|'
    r'python-requests|python-urllib|curl|wget|httpx|axios|java/',
    re.IGNORECASE
)

_COOKIE_NAME = '_meld_aid'
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def _is_bot() -> bool:
    ua = request.headers.get('User-Agent', '')
    if bool(_BOT_PATTERNS.search(ua)) or not ua:
        return True
    host = request.host.split(':')[0]
    if host in ('localhost', '127.0.0.1', '0.0.0.0'):
        return True
    return False


def _get_sid() -> str:
    """Return stable analytics session ID from a dedicated cookie (not Flask session)."""
    aid = request.cookies.get(_COOKIE_NAME)
    if not aid:
        aid = secrets.token_hex(16)
        # Signal after_request to set the cookie on the response
        g._meld_aid_new = aid
    return hashlib.sha256(aid.encode()).hexdigest()[:16]


def log_unique_visit() -> None:
    """Record at most one unique-visit event per session per day."""
    if not has_request_context() or _is_bot():
        return
    try:
        from models.db import mongo
        sid = _get_sid()
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        if not mongo.db.events.find_one({"e": "uv", "sid": sid, "ts": {"$gte": today}}):
            mongo.db.events.insert_one({"e": "uv", "sid": sid, "ts": datetime.utcnow()})
    except Exception:
        pass


def log_event(event_type: str, product_id=None, user_id=None) -> None:
    """Append one behaviour event to the events collection. Never raises.

    event_type values:
        'uv'  – unique visit (once per session, first time user arrives)
        'vp'  – product page viewed
        'ac'  – product added to cart
        'bc'  – checkout page opened (begin checkout)
        'pu'  – order placed (purchase)
    """
    if not has_request_context():
        return
    if _is_bot():
        return
    try:
        from models.db import mongo
        doc: dict = {"e": event_type, "sid": _get_sid(), "ts": datetime.utcnow()}
        if product_id is not None:
            try:
                doc["pid"] = ObjectId(str(product_id))
            except Exception:
                doc["pid"] = str(product_id)
        if user_id is not None:
            try:
                doc["uid"] = ObjectId(str(user_id))
            except Exception:
                pass
        mongo.db.events.insert_one(doc)
    except Exception:
        pass
