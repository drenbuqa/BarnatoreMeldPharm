"""Shared promo helpers — importable from any route without circular imports."""
from datetime import datetime as _dt, timezone, timedelta

_OCT_PROMO_YEAR  = 2026
_OCT_PROMO_MONTH = 10

# ── Black Friday 2026 ──────────────────────────────────────────────────────────
# Austria uses CET (UTC+1) in November.
# All offers expire at midnight Dec 1 00:00:00 CET = Nov 30 23:00:00 UTC.
_CET = timezone(timedelta(hours=1))

_BF_START_ALL    = _dt(2026, 11, 18, 0, 0, 0, tzinfo=_CET)   # CeraVe, Vichy, La Roche-Posay, 5% all
_BF_START_EUCERIN = _dt(2026, 11, 20, 0, 0, 0, tzinfo=_CET)  # Eucerin joins on Nov 20
_BF_END          = _dt(2026, 12, 1,  0, 0, 0, tzinfo=_CET)   # exclusive end (after Nov 30 midnight)

_BF_BRANDS_20PCT = {'vichy', 'cerave', 'la roche-posay', 'eucerin'}
_BF_BRANDS_20PCT_NO_EUCERIN = {'vichy', 'cerave', 'la roche-posay'}


def _now_cet():
    return _dt.now(tz=_CET)


def get_bf_promo_status():
    """
    Returns a dict with keys:
      active        – any BF promo is live right now
      all_active    – the 5% + main 3-brand -20% window is open
      eucerin_active – Eucerin -20% window is open
      ends_at       – aware datetime when all promos expire (for countdown)
    """
    now = _now_cet()
    all_active     = _BF_START_ALL <= now < _BF_END
    eucerin_active = _BF_START_EUCERIN <= now < _BF_END
    return {
        'active':         all_active,
        'all_active':     all_active,
        'eucerin_active': eucerin_active,
        'ends_at':        _BF_END,
    }


def _bf_discount_for_product(product, bf_status):
    """
    Return the BF discount multiplier for a product, or None if no BF applies.
    Priority: products with an existing discount_price keep their own deal.
    """
    if not bf_status['active']:
        return None
    if product.get('discount_price'):
        return None  # already has a manual discount

    brand_raw = str(product.get('brand') or '').strip().lower()

    if brand_raw == 'eucerin':
        if bf_status['eucerin_active']:
            return 0.80  # -20%
        return 0.95  # -5% until Nov 23

    if brand_raw in _BF_BRANDS_20PCT_NO_EUCERIN:
        return 0.80  # -20%

    # all other products: 5% off
    return 0.95


def apply_bf_discounts(products):
    """
    Apply Black Friday discounts in-memory — does NOT write to DB.
    Returns a new list; original dicts are shallow-copied before mutation.
    """
    bf = get_bf_promo_status()
    if not bf['active']:
        return products

    result = []
    for p in products:
        mult = _bf_discount_for_product(p, bf)
        if mult is not None:
            orig = float(p.get('display_price') or p.get('price') or 0)
            if orig > 0:
                p = dict(p)
                p['auto_bf_discount'] = True
                disc = round(orig * mult, 2)
                p['display_original_price'] = orig
                p['display_price'] = disc
                pct = round((1 - mult) * 100)
                p['offer_badge_text'] = f'-{pct}%'
                p['bf_badge_pct'] = pct
        result.append(p)
    return result


def effective_price_with_promo(product, base_price, base_discount):
    """
    Apply the active promo (BF first, then Oct fallback) on top of base price.
    If the product already has a manual discount, that is kept as-is.
    """
    if base_discount is not None:
        return base_price, base_discount

    bf = get_bf_promo_status()
    mult = _bf_discount_for_product(product, bf)
    if mult is not None and base_price > 0:
        return base_price, round(base_price * mult, 2)

    # October fallback
    if is_oct_promo_active() and base_price > 0:
        return base_price, round(base_price * 0.95, 2)

    return base_price, None


# ── October 2026 promo (kept for reference / fallback) ───────────────────────

def is_oct_promo_active():
    now = _dt.now()
    return now.year == _OCT_PROMO_YEAR and now.month == _OCT_PROMO_MONTH


def apply_oct_5pct_discount(products):
    """In-memory only — does NOT write to DB."""
    if not is_oct_promo_active():
        return products
    result = []
    for p in products:
        if not p.get('discount_price') and not p.get('auto_oct_discount'):
            orig = float(p.get('display_price') or p.get('price') or 0)
            if orig > 0:
                p = dict(p)
                p['auto_oct_discount'] = True
                p['discount_price'] = round(orig * 0.95, 2)
                p['display_original_price'] = orig
                p['display_price'] = round(orig * 0.95, 2)
                p['offer_badge_text'] = '-5%'
        result.append(p)
    return result
