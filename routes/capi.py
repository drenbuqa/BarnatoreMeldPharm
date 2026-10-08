"""Meta Conversions API (CAPI) — server-side event sender."""
import os, hashlib, time, uuid, logging, threading
import urllib.request, urllib.parse, json

log = logging.getLogger(__name__)

GRAPH_VER = 'v19.0'

def _pixel_id():
    return os.getenv('META_PIXEL_ID', '')

def _access_token():
    return os.getenv('META_CAPI_TOKEN', '')


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _user_data(request):
    """Extract hashed user signals from the current Flask request."""
    from flask_login import current_user
    ud = {}

    # IP
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    if ip:
        ud['client_ip_address'] = ip

    # User agent
    ua = request.headers.get('User-Agent', '')
    if ua:
        ud['client_user_agent'] = ua

    # Facebook browser cookie (fbp) and click id (fbc)
    fbp = request.cookies.get('_fbp', '')
    fbc = request.cookies.get('_fbc', '')
    if fbp:
        ud['fbp'] = fbp
    if fbc:
        ud['fbc'] = fbc

    # Hashed email for logged-in users
    if current_user.is_authenticated:
        email = getattr(current_user, 'email', '') or ''
        if email:
            ud['em'] = [_sha256(email)]
        phone = getattr(current_user, 'phone', '') or ''
        if phone:
            digits = ''.join(c for c in phone if c.isdigit())
            if digits:
                ud['ph'] = [_sha256(digits)]

    return ud


def _send(payload: dict):
    """POST to Graph API in a background thread so it never blocks the response."""
    pid = _pixel_id()
    tok = _access_token()
    if not pid or not tok:
        return

    url = f'https://graph.facebook.com/{GRAPH_VER}/{pid}/events?access_token={tok}'
    body = json.dumps(payload).encode()

    def _post():
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if os.getenv('META_PIXEL_DEBUG', '').lower() in ('1', 'true'):
                    log.info('[CAPI] %s', resp.read().decode())
        except Exception as e:
            log.warning('[CAPI] send failed: %s', e)

    threading.Thread(target=_post, daemon=True).start()


def _event(name, request, custom_data: dict, event_id: str | None = None):
    """Build and fire one CAPI event."""
    if not _pixel_id() or not _access_token():
        return

    eid = event_id or str(uuid.uuid4())
    payload = {
        'data': [{
            'event_name':    name,
            'event_time':    int(time.time()),
            'event_id':      eid,
            'action_source': 'website',
            'event_source_url': request.url,
            'user_data':     _user_data(request),
            'custom_data':   custom_data,
        }]
    }
    _send(payload)
    return eid


# ── Public helpers ────────────────────────────────────────────────────────────

def send_view_content(request, product_id: str, value: float, currency: str = 'EUR'):
    return _event('ViewContent', request, {
        'content_ids': [product_id],
        'content_type': 'product',
        'value': value,
        'currency': currency,
    })


def send_add_to_cart(request, product_id: str, value: float, currency: str = 'EUR'):
    return _event('AddToCart', request, {
        'content_ids': [product_id],
        'content_type': 'product',
        'value': value,
        'currency': currency,
    })


def send_initiate_checkout(request, product_ids: list, value: float, currency: str = 'EUR'):
    return _event('InitiateCheckout', request, {
        'content_ids': product_ids,
        'content_type': 'product',
        'value': value,
        'currency': currency,
        'num_items': len(product_ids),
    })


def send_purchase(request, order_id: str, product_ids: list, value: float, currency: str = 'EUR'):
    return _event('Purchase', request, {
        'content_ids': product_ids,
        'content_type': 'product',
        'value': value,
        'currency': currency,
        'order_id': order_id,
        'num_items': len(product_ids),
    }, event_id=f'purchase_{order_id}')  # stable event_id for deduplication
