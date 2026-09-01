import hashlib
import secrets
from datetime import datetime

from bson import ObjectId
from flask import has_request_context, session


def _get_sid() -> str:
    """Return a stable, anonymous session identifier (16 hex chars).

    Stored as '_aid' inside the existing Flask session cookie — no new cookie is created.
    The raw value is hashed before storage in MongoDB so it cannot be reversed.
    """
    if '_aid' not in session:
        session['_aid'] = secrets.token_hex(16)
        session.modified = True
    return hashlib.sha256(session['_aid'].encode()).hexdigest()[:16]


def log_event(event_type: str, product_id=None, user_id=None) -> None:
    """Append one behaviour event to the events collection. Never raises.

    event_type values:
        'vp'  – product page viewed
        'ac'  – product added to cart
        'bc'  – checkout page opened (begin checkout)
        'pu'  – order placed (purchase)

    All fields are optional except event_type and ts.
    No personal data (name, email, IP) is stored.
    """
    if not has_request_context():
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
