"""Shared promo helpers — importable from any route without circular imports."""
from datetime import datetime as _dt

_OCT_PROMO_YEAR  = 2026
_OCT_PROMO_MONTH = 10


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


def effective_price_with_promo(product, base_price, base_discount):
    """Apply oct promo on top of the base price/discount if eligible."""
    if base_discount is not None:
        return base_price, base_discount
    if not is_oct_promo_active():
        return base_price, None
    if base_price > 0:
        return base_price, round(base_price * 0.95, 2)
    return base_price, None
