"""Tests for models/analytics.py — behaviour event logging.

Run with:  pytest tests/test_analytics.py -v

mongo is imported lazily inside log_event (via `from models.db import mongo`),
so we patch it at `models.db.mongo`, not `models.analytics.mongo`.
"""
import hashlib
import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask


@pytest.fixture
def app():
    a = Flask(__name__)
    a.config['SECRET_KEY'] = 'test-secret'
    a.config['TESTING'] = True
    return a


@pytest.fixture
def ctx(app):
    with app.test_request_context('/'):
        yield


def _mongo_mock():
    """Build a mock whose .db.events.insert_one is a plain MagicMock."""
    m = MagicMock()
    m.db.events = MagicMock()
    return m


# ---------------------------------------------------------------------------
# log_event — core behaviour
# ---------------------------------------------------------------------------

class TestLogEvent:

    def test_view_product_inserts_correct_fields(self, ctx):
        from bson import ObjectId
        fake_pid = str(ObjectId())
        mock_mongo = _mongo_mock()

        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('vp', product_id=fake_pid)

        assert mock_mongo.db.events.insert_one.called
        doc = mock_mongo.db.events.insert_one.call_args[0][0]
        assert doc['e'] == 'vp'
        assert isinstance(doc['pid'], ObjectId)
        assert str(doc['pid']) == fake_pid
        assert 'sid' in doc
        assert len(doc['sid']) == 16
        assert isinstance(doc['ts'], datetime)
        assert 'uid' not in doc

    def test_add_to_cart_includes_product_and_user(self, ctx):
        from bson import ObjectId
        pid = str(ObjectId())
        uid = str(ObjectId())
        mock_mongo = _mongo_mock()

        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('ac', product_id=pid, user_id=uid)

        doc = mock_mongo.db.events.insert_one.call_args[0][0]
        assert doc['e'] == 'ac'
        assert isinstance(doc['pid'], ObjectId)
        assert isinstance(doc['uid'], ObjectId)
        assert str(doc['uid']) == uid

    def test_begin_checkout_no_product_id(self, ctx):
        mock_mongo = _mongo_mock()
        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('bc')

        doc = mock_mongo.db.events.insert_one.call_args[0][0]
        assert doc['e'] == 'bc'
        assert 'pid' not in doc
        assert 'uid' not in doc

    def test_purchase_event_logged(self, ctx):
        from bson import ObjectId
        uid = str(ObjectId())
        mock_mongo = _mongo_mock()

        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('pu', user_id=uid)

        doc = mock_mongo.db.events.insert_one.call_args[0][0]
        assert doc['e'] == 'pu'
        assert 'pid' not in doc
        assert str(doc['uid']) == uid

    def test_no_raise_when_db_errors(self, ctx):
        """DB failure must be silently swallowed — never crash the request."""
        mock_mongo = _mongo_mock()
        mock_mongo.db.events.insert_one.side_effect = Exception("DB down")
        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('vp')   # must not raise

    def test_no_raise_outside_request_context(self):
        """Outside a Flask request context log_event must do nothing."""
        from models.analytics import log_event
        log_event('vp')   # no request context — should return silently

    def test_invalid_object_id_falls_back_to_string(self, ctx):
        mock_mongo = _mongo_mock()
        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('vp', product_id='not-an-objectid')

        doc = mock_mongo.db.events.insert_one.call_args[0][0]
        assert doc['pid'] == 'not-an-objectid'


# ---------------------------------------------------------------------------
# Anonymous session ID behaviour
# ---------------------------------------------------------------------------

class TestSessionId:

    def test_sid_is_16_hex_chars(self, ctx):
        mock_mongo = _mongo_mock()
        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('bc')

        doc = mock_mongo.db.events.insert_one.call_args[0][0]
        sid = doc['sid']
        assert len(sid) == 16
        assert all(c in '0123456789abcdef' for c in sid)

    def test_sid_stable_within_same_session(self, ctx):
        """Two events in the same session must share the same sid."""
        mock_mongo = _mongo_mock()
        with patch('models.db.mongo', mock_mongo):
            from models.analytics import log_event
            log_event('vp')
            log_event('ac')

        calls = mock_mongo.db.events.insert_one.call_args_list
        assert len(calls) == 2
        sid1 = calls[0][0][0]['sid']
        sid2 = calls[1][0][0]['sid']
        assert sid1 == sid2

    def test_sid_is_hash_not_raw_token(self, app):
        """The stored sid must be the SHA-256 hash of _aid, not the raw value."""
        from flask import session as flask_session
        with app.test_request_context('/'):
            flask_session['_aid'] = 'known-value'
            expected_sid = hashlib.sha256(b'known-value').hexdigest()[:16]
            mock_mongo = _mongo_mock()
            with patch('models.db.mongo', mock_mongo):
                from models.analytics import log_event
                log_event('bc')
            doc = mock_mongo.db.events.insert_one.call_args[0][0]
            assert doc['sid'] == expected_sid

    def test_sid_differs_across_sessions(self, app):
        """Different sessions must produce different sids."""
        sids = []
        for _ in range(2):
            with app.test_request_context('/'):
                mock_mongo = _mongo_mock()
                with patch('models.db.mongo', mock_mongo):
                    from models.analytics import log_event
                    log_event('vp')
                sids.append(mock_mongo.db.events.insert_one.call_args[0][0]['sid'])
        assert sids[0] != sids[1]


# ---------------------------------------------------------------------------
# db.py — index creation includes events collection
# ---------------------------------------------------------------------------

class TestIndexCreation:

    def test_events_indexes_are_created(self):
        """_ensure_indexes must create all four events indexes."""
        mock_mongo = MagicMock()
        events_col = MagicMock()
        mock_mongo.db.events = events_col

        with patch('models.db.mongo', mock_mongo):
            from models.db import _ensure_indexes
            _ensure_indexes()

        call_str = ' '.join(str(c) for c in events_col.create_index.call_args_list)
        assert 'idx_events_type_ts'     in call_str
        assert 'idx_events_pid_type_ts' in call_str
        assert 'idx_events_sid_type'    in call_str
        assert 'idx_events_ttl'         in call_str

    def test_ttl_index_has_correct_expire(self):
        """TTL index must expire after exactly 90 days (7 776 000 seconds)."""
        mock_mongo = MagicMock()
        events_col = MagicMock()
        mock_mongo.db.events = events_col

        with patch('models.db.mongo', mock_mongo):
            from models.db import _ensure_indexes
            _ensure_indexes()

        for c in events_col.create_index.call_args_list:
            kwargs = c[1]
            if kwargs.get('name') == 'idx_events_ttl':
                assert kwargs['expireAfterSeconds'] == 90 * 24 * 3600
                return
        pytest.fail("TTL index not found in create_index calls")
