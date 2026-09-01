from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from models.product import Product
from models.db import mongo
from models.banner import Banner
from models.order import Order
from models.user import User
from models.email_utils import (
    send_order_confirmation_email,
    send_order_shipped_email,
    send_order_delivered_email,
    send_order_cancelled_email,
    send_newsletter_email,
    send_admin_digest,
    send_email_in_background,
)
from models.categories import CATEGORIES
from functools import wraps
from datetime import datetime, timedelta
import calendar as _calendar
import json, uuid

admin = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Ju nuk keni akses në këtë faqe.", "danger")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def _form_float(field_name, default=0.0):
    raw_value = request.form.get(field_name)
    if raw_value is None or raw_value == '':
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _form_optional_float(field_name):
    raw_value = request.form.get(field_name)
    if raw_value is None or raw_value == '':
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _form_optional_int(field_name):
    raw_value = request.form.get(field_name)
    if raw_value is None or raw_value == '':
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _form_optional_date(field_name):
    raw_value = request.form.get(field_name)
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, '%Y-%m-%d')
    except ValueError:
        return None

@admin.route('/orders')
@login_required
@admin_required
def orders():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    per_page = 50

    query = {}
    if status_filter:
        # Map filter key to all possible status values stored in DB
        status_map = {
            'pending':    ['Pending', 'Në Pritje'],
            'konfirmuar': ['Konfirmuar', 'Confirmed', 'Pranuar'],
            'dergese':    ['Delivering', 'Në Dërgesë'],
            'dorezuar':   ['Delivered', 'Dorezuar'],
            'anuluar':    ['Cancelled', 'Anuluar'],
            'refuzuar':   ['Refuzuar'],
        }
        statuses = status_map.get(status_filter, [status_filter])
        query['status'] = {'$in': statuses}

    all_orders = list(mongo.db.orders.find(query).sort('created_at', -1))
    total = len(all_orders)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    orders_page = all_orders[(page - 1) * per_page : page * per_page]

    counts = {
        'total': mongo.db.orders.count_documents({}),
        'pending': mongo.db.orders.count_documents({'status': {'$in': ['Pending', 'Në Pritje']}}),
        'konfirmuar': mongo.db.orders.count_documents({'status': {'$in': ['Konfirmuar', 'Confirmed', 'Pranuar']}}),
        'dergese': mongo.db.orders.count_documents({'status': {'$in': ['Delivering', 'Në Dërgesë']}}),
        'dorezuar': mongo.db.orders.count_documents({'status': {'$in': ['Delivered', 'Dorezuar']}}),
        'anuluar': mongo.db.orders.count_documents({'status': {'$in': ['Cancelled', 'Anuluar', 'Refuzuar']}}),
    }
    pending_orders_count = counts['pending']
    return render_template('admin/orders.html', orders=orders_page, page=page,
                           total_pages=total_pages, total=total, counts=counts,
                           status_filter=status_filter, pending_orders_count=pending_orders_count)


@admin.route('/order/update_status/<order_id>', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    new_status = request.form.get('status')
    tracking_number = (request.form.get('tracking_number') or '').strip() or None
    if not new_status:
        if is_ajax:
            from flask import jsonify
            return jsonify({'ok': False, 'error': 'No status provided'}), 400
        return redirect(url_for('admin.orders'))

    existing_order = Order.get_by_id(order_id)
    old_status = existing_order.get('status') if existing_order else None

    cancel_reason = (request.form.get('cancel_reason') or '').strip() or None
    update_fields = {'status': new_status}
    if tracking_number:
        update_fields['tracking_number'] = tracking_number
    if cancel_reason and new_status in ('Cancelled', 'Anuluar', 'Refuzuar'):
        update_fields['cancel_reason'] = cancel_reason
    from bson import ObjectId as _ObjId
    mongo.db.orders.update_one({'_id': _ObjId(order_id)}, {'$set': update_fields})

    msg = f'Statusi u ndryshua në {new_status}.'
    if new_status in ('Konfirmuar', 'Confirmed', 'Pranuar') and old_status not in ('Konfirmuar', 'Confirmed', 'Pranuar'):
        send_email_in_background(send_order_confirmation_email, order_id)
        msg = 'Porosia u konfirmua dhe emaili po dërgohet te klienti.'
    elif new_status in ('Delivering', 'Në Dërgesë') and old_status not in ('Delivering', 'Në Dërgesë'):
        send_email_in_background(send_order_shipped_email, order_id, tracking_number=tracking_number)
        msg = 'Statusi u ndryshua dhe emaili i dërgesës po dërgohet.'
    elif new_status in ('Delivered', 'Dorezuar') and old_status not in ('Delivered', 'Dorezuar'):
        send_email_in_background(send_order_delivered_email, order_id)
        msg = 'Statusi u ndryshua dhe emaili i dorëzimit po dërgohet.'
    elif new_status in ('Cancelled', 'Anuluar', 'Refuzuar') and old_status not in ('Cancelled', 'Anuluar', 'Refuzuar'):
        if new_status == 'Refuzuar':
            from models.email_utils import send_order_rejected_email
            send_email_in_background(send_order_rejected_email, order_id, cancel_reason)
            msg = 'Porosia u refuzua dhe emaili i refuzimit po dërgohet te klienti.'
        else:
            send_email_in_background(send_order_cancelled_email, order_id, cancel_reason)
            msg = 'Porosia u anulua dhe emaili po dërgohet te klienti.'

    if is_ajax:
        from flask import jsonify
        return jsonify({'ok': True, 'message': msg, 'new_status': new_status})

    flash(msg, 'success')
    return redirect(url_for('admin.orders', status=request.args.get('status', '')))

@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Revert expired offers (throttled — runs at most once every 15 minutes per worker)
    Product.revert_expired_offers()

    now        = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    six_months_ago = now - timedelta(days=186)

    # ── Products analytics via a single $facet aggregation ────────
    # Avoids loading 800+ documents into Python just to count/aggregate them.
    _to_double = {"$convert": {"input": "$grand_total", "to": "double",
                               "onError": 0, "onNull": 0}}
    prod_facet = list(mongo.db.products.aggregate([
        {"$match": {"is_deleted": {"$ne": True}}},
        {"$facet": {
            "total_count": [{"$count": "n"}],
            "out_of_stock": [
                {"$match": {"in_stock": {"$ne": True}}},
                {"$limit": 5},
                {"$project": {"name": 1, "image_url": 1}}
            ],
            "active_offers": [
                {"$match": {"offer_status": "active"}},
                {"$count": "n"}
            ],
            "brand_dist": [
                {"$match": {"brand": {"$nin": [None, ""]}}},
                {"$group": {
                    "_id": {"$toLower": {"$trim": {"input": {"$ifNull": ["$brand", ""]}}}},
                    "brand": {"$first": "$brand"},
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 6}
            ],
            "cat_dist": [
                {"$match": {"category": {"$nin": [None, ""]}}},
                {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 6}
            ],
            "most_liked": [
                {"$project": {
                    "name": 1, "image_url": 1,
                    "fav_count": {"$size": {"$ifNull": ["$favorites", []]}}
                }},
                {"$sort": {"fav_count": -1}},
                {"$limit": 5}
            ]
        }}
    ]))
    pf = prod_facet[0] if prod_facet else {}

    # ── Orders analytics via a single $facet aggregation ──────────
    ord_facet = list(mongo.db.orders.aggregate([
        {"$match": {"created_at": {"$gte": six_months_ago}}},
        {"$facet": {
            "revenue_total": [
                {"$group": {"_id": None,
                            "total": {"$sum": _to_double},
                            "count": {"$sum": 1}}}
            ],
            "revenue_month": [
                {"$match": {"created_at": {"$gte": month_start}}},
                {"$group": {"_id": None,
                            "total": {"$sum": _to_double},
                            "count": {"$sum": 1}}}
            ],
            "monthly_trend": [
                {"$group": {
                    "_id": {"y": {"$year": "$created_at"},
                            "m": {"$month": "$created_at"}},
                    "revenue": {"$sum": _to_double},
                    "orders":  {"$sum": 1}
                }},
                {"$sort": {"_id.y": 1, "_id.m": 1}}
            ],
            "most_ordered": [
                {"$unwind": "$items"},
                {"$group": {
                    "_id": {"$toString": {"$ifNull": ["$items.product_id", "$items._id"]}},
                    "name":  {"$first": "$items.name"},
                    "count": {"$sum": {"$convert": {"input": "$items.quantity",
                                                    "to": "int", "onError": 1, "onNull": 1}}}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 5}
            ]
        }}
    ]))
    of = ord_facet[0] if ord_facet else {}

    # ── Unpack order aggregation results ──────────────────────────
    rev_total_doc  = (of.get('revenue_total')  or [{}])[0]
    rev_month_doc  = (of.get('revenue_month')  or [{}])[0]
    total_revenue  = round(float(rev_total_doc.get('total') or 0), 2)
    total_orders   = int(rev_total_doc.get('count') or 0)
    revenue_month  = round(float(rev_month_doc.get('total') or 0), 2)
    orders_month   = int(rev_month_doc.get('count') or 0)

    # Monthly trend — exactly the last 6 months
    monthly_map = {(r['_id']['y'], r['_id']['m']): r
                   for r in (of.get('monthly_trend') or [])}
    trend_labels, trend_revenue, trend_orders = [], [], []
    for i in range(5, -1, -1):
        m = (now.month - i - 1) % 12 + 1
        y = now.year - ((now.month - i - 1) // 12)
        row = monthly_map.get((y, m), {})
        trend_labels.append(_calendar.month_abbr[m])
        trend_revenue.append(round(float(row.get('revenue') or 0), 2))
        trend_orders.append(int(row.get('orders') or 0))

    # Most ordered — look up image_url for the top-5 products
    most_ordered = []
    mo_items = of.get('most_ordered') or []
    if mo_items:
        from bson import ObjectId
        mo_ids = []
        for item in mo_items:
            pid = item.get('_id', '')
            if pid and ObjectId.is_valid(str(pid)):
                mo_ids.append(ObjectId(str(pid)))
        img_map = {}
        if mo_ids:
            for p in mongo.db.products.find(
                    {"_id": {"$in": mo_ids}},
                    {"image_url": 1}):
                img_map[str(p['_id'])] = p.get('image_url', '')
        for item in mo_items:
            most_ordered.append({
                'name':        item.get('name', '—'),
                'image_url':   img_map.get(str(item.get('_id', '')), ''),
                'order_count': item.get('count', 0),
            })

    analytics = {
        'total_products':    (pf.get('total_count')   or [{}])[0].get('n', 0),
        'total_offers':      (pf.get('active_offers') or [{}])[0].get('n', 0),
        'out_of_stock':      pf.get('out_of_stock', []),
        'most_liked':        pf.get('most_liked', []),
        'brand_distribution': {
            r['brand'].title(): r['count']
            for r in (pf.get('brand_dist') or []) if r.get('brand')
        },
        'category_sales':   {
            r['_id'].title(): r['count']
            for r in (pf.get('cat_dist') or []) if r.get('_id')
        },
        'most_ordered':  most_ordered,
        'total_revenue': total_revenue,
        'revenue_month': revenue_month,
        'orders_month':  orders_month,
        'total_orders':  total_orders,
        'trend_labels':  trend_labels,
        'trend_revenue': trend_revenue,
        'trend_orders':  trend_orders,
    }

    pending_orders_count = mongo.db.orders.count_documents(
        {'status': {'$in': ['Pending', 'Në Pritje']}})
    recent_pending = list(mongo.db.orders.find(
        {'status': {'$in': ['Pending', 'Në Pritje']}},
        {'fullname': 1, 'city': 1, 'grand_total': 1, 'created_at': 1, 'status': 1}
    ).sort('created_at', -1).limit(6))
    newsletter_count = (
        mongo.db.users.count_documents({'newsletter_subscribed': True})
        + mongo.db.newsletter_subscribers.count_documents({})
    )
    return render_template('admin/dashboard.html',
                           analytics=analytics,
                           pending_orders_count=pending_orders_count,
                           recent_pending=recent_pending,
                           newsletter_count=newsletter_count)

@admin.route('/products')
@login_required
@admin_required
def products_page():
    import re as _re
    filter_category = request.args.get('category', '').strip()
    filter_brand    = request.args.get('brand', '').strip()
    filter_on_offer = request.args.get('on_offer') == '1'
    filter_stock    = request.args.get('stock', '')
    search_q        = request.args.get('q', '').strip()
    page            = max(1, int(request.args.get('page', 1) or 1))
    per_page        = 100

    lean_proj = {
        "name": 1, "brand": 1, "category": 1, "subcategory": 1,
        "price": 1, "discount_price": 1, "offer_name": 1, "offer_type": 1,
        "in_stock": 1, "image_url": 1, "size": 1, "is_deleted": 1,
    }

    # Build category/brand lists via lightweight facet (no full product load)
    meta = list(mongo.db.products.aggregate([
        {"$match": {"is_deleted": {"$ne": True}}},
        {"$facet": {
            "total": [{"$count": "n"}],
            "cats":  [{"$match": {"category": {"$nin": [None, ""]}}},
                      {"$group": {"_id": "$category"}},
                      {"$sort": {"_id": 1}}],
            "brands":[{"$match": {"brand": {"$nin": [None, ""]}}},
                      {"$group": {"_id": "$brand"}},
                      {"$sort": {"_id": 1}}],
        }}
    ]))
    m = meta[0] if meta else {}
    all_categories = [r['_id'] for r in m.get('cats', []) if r.get('_id')]
    all_brands     = [r['_id'] for r in m.get('brands', []) if r.get('_id')]
    total_count    = (m.get('total') or [{}])[0].get('n', 0)

    # Build query with all active filters + search
    query = {"is_deleted": {"$ne": True}}
    if filter_category:
        query["category"] = filter_category
    if filter_brand:
        query["brand"] = {"$regex": f"^{_re.escape(filter_brand)}$", "$options": "i"}
    if filter_on_offer:
        query["discount_price"] = {"$nin": [None, ""]}
    if filter_stock == 'out':
        query["in_stock"] = {"$ne": True}
    elif filter_stock == 'in':
        query["in_stock"] = True
    if search_q:
        escaped = _re.escape(search_q)
        query["$or"] = [
            {"name":  {"$regex": escaped, "$options": "i"}},
            {"brand": {"$regex": escaped, "$options": "i"}},
        ]

    filtered_total = mongo.db.products.count_documents(query)
    total_pages    = max(1, (filtered_total + per_page - 1) // per_page)
    page           = min(page, total_pages)

    products = list(
        mongo.db.products.find(query, lean_proj)
        .sort("_id", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    pending_orders_count = mongo.db.orders.count_documents(
        {'status': {'$in': ['Pending', 'Në Pritje']}})
    return render_template('admin/products.html',
                           products=products,
                           all_categories=all_categories,
                           all_brands=all_brands,
                           filter_category=filter_category,
                           filter_brand=filter_brand,
                           filter_on_offer=filter_on_offer,
                           filter_stock=filter_stock,
                           search_q=search_q,
                           total_count=total_count,
                           filtered_total=filtered_total,
                           page=page,
                           total_pages=total_pages,
                           per_page=per_page,
                           pending_orders_count=pending_orders_count)


@admin.route('/order/<order_id>/note', methods=['POST'])
@login_required
@admin_required
def order_note(order_id):
    note = request.form.get('note', '').strip()
    from bson import ObjectId
    mongo.db.orders.update_one(
        {'_id': ObjectId(order_id)},
        {'$set': {'admin_note': note, 'admin_note_updated': datetime.utcnow()}}
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True})
    flash('Shënimi u ruajt.', 'success')
    return redirect(url_for('admin.orders'))


@admin.route('/order/<order_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_order(order_id):
    from bson import ObjectId as _ObjId
    from flask import jsonify
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        mongo.db.orders.delete_one({'_id': _ObjId(order_id)})
        if is_ajax:
            return jsonify({'ok': True})
        flash('Porosia u fshi.', 'success')
    except Exception as e:
        if is_ajax:
            return jsonify({'ok': False, 'error': str(e)}), 500
        flash('Gabim gjatë fshirjes.', 'danger')
    return redirect(url_for('admin.orders'))


@admin.route('/users/<user_id>/orders')
@login_required
@admin_required
def user_orders(user_id):
    from bson import ObjectId
    try:
        user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    except Exception:
        user_data = None
    if not user_data:
        flash('Përdoruesi nuk u gjet.', 'danger')
        return redirect(url_for('admin.users'))

    user_obj = User(user_data)
    # Orders matched by user_id field or by email
    orders = list(mongo.db.orders.find({
        '$or': [
            {'user_id': str(user_id)},
            {'email': user_obj.email}
        ]
    }).sort('created_at', -1))

    pending_orders_count = mongo.db.orders.count_documents({'status': {'$in': ['Pending', 'Në Pritje']}})
    return render_template('admin/user_orders.html',
                           user=user_obj,
                           orders=orders,
                           pending_orders_count=pending_orders_count)


@admin.route('/digest/send', methods=['POST'])
@login_required
@admin_required
def send_digest():
    period = request.form.get('period', 'today')  # 'today' | 'week'
    now = datetime.utcnow()

    if period == 'week':
        from datetime import timedelta
        since = now - timedelta(days=7)
        period_label = "7 Ditët e Fundit"
    else:
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_label = f"Sot, {now.strftime('%d.%m.%Y')}"

    orders = list(mongo.db.orders.find({'created_at': {'$gte': since}}).sort('created_at', -1))

    def safe_float(v):
        try: return float(v or 0)
        except: return 0.0

    stats = {
        'total_orders':   len(orders),
        'total_revenue':  sum(safe_float(o.get('grand_total')) for o in orders),
        'pending':        sum(1 for o in orders if o.get('status') in ['Pending', 'Në Pritje']),
        'konfirmuar':     sum(1 for o in orders if o.get('status') in ['Konfirmuar', 'Confirmed', 'Pranuar']),
        'dergese':        sum(1 for o in orders if o.get('status') in ['Delivering', 'Në Dërgesë']),
        'dorezuar':       sum(1 for o in orders if o.get('status') in ['Delivered', 'Dorezuar']),
        'anuluar':        sum(1 for o in orders if o.get('status') in ['Cancelled', 'Anuluar', 'Refuzuar']),
        'recent_orders':  orders[:10],
    }

    import os
    admin_email = os.getenv('ADMIN_DIGEST_EMAIL') or os.getenv('SMTP_USER') or os.getenv('MAIL_USERNAME')
    if not admin_email:
        flash('Email i adminit nuk është konfiguruar (ADMIN_DIGEST_EMAIL).', 'warning')
        return redirect(url_for('admin.dashboard'))

    sent, msg = send_admin_digest(admin_email, period_label, stats)
    if sent:
        flash(f'Digest u dërgua te {admin_email}.', 'success')
    else:
        flash(f'Dërgimi dështoi: {msg}', 'danger')
    return redirect(url_for('admin.dashboard'))


def _parse_option_groups(raw_json, existing_variants=None):
    """Parse option_groups_json from the form and return (option_groups, variants, base_price, base_discount).
    existing_variants: list of already-saved variants so stable IDs are preserved across edits.
    """
    try:
        option_groups = json.loads(raw_json) if raw_json else []
    except (ValueError, TypeError):
        option_groups = []

    if not option_groups:
        return [], [], None, None

    from itertools import product as itertools_product

    groups_with_values = [og for og in option_groups if og.get('values')]
    if not groups_with_values:
        return option_groups, [], None, None

    value_lists = [og['values'] for og in groups_with_values]
    group_names = [og['name'] for og in groups_with_values]

    # Build a lookup from attribute combo → existing variant id so cart links survive edits
    existing_id_map = {}
    for ev in (existing_variants or []):
        attrs = ev.get('attributes') or {}
        key = tuple(sorted(attrs.items()))
        existing_id_map[key] = ev.get('id') or str(uuid.uuid4())

    variants = []
    for combo in itertools_product(*value_lists):
        first_val = combo[0]
        price = first_val.get('price') or None
        discount_price = first_val.get('discount_price') or None
        image_url = next((v.get('image_url') for v in combo if v.get('image_url')), None)
        in_stock = all(v.get('in_stock', True) for v in combo)
        attributes = {group_names[i]: combo[i]['value'] for i in range(len(group_names))}

        combo_key = tuple(sorted(attributes.items()))
        variant_id = existing_id_map.get(combo_key) or str(uuid.uuid4())

        variants.append({
            'id': variant_id,
            'attributes': attributes,
            'price': float(price) if price is not None else None,
            'discount_price': float(discount_price) if discount_price is not None else None,
            'image_url': image_url,
            'in_stock': in_stock,
        })

    base_price = next((v['price'] for v in variants if v['price'] is not None), None)
    base_discount = next((v['discount_price'] for v in variants if v['discount_price'] is not None), None)

    return option_groups, variants, base_price, base_discount


def _build_product_data(main_img, images, option_groups, variants, base_price, base_discount):
    labels_raw = request.form.get('labels_json', '[]')
    try:
        labels = json.loads(labels_raw)
    except (ValueError, TypeError):
        labels = []

    price = base_price if base_price is not None else _form_float('price')
    discount_price = base_discount if base_discount is not None else _form_optional_float('discount_price')

    return {
        "name": request.form.get('name'),
        "brand": request.form.get('brand'),
        "category": request.form.get('category'),
        "subcategory": request.form.get('subcategory'),
        "size": request.form.get('size'),
        "price": price,
        "discount_price": discount_price,
        "discount_from": _form_optional_date('discount_from'),
        "discount_until": _form_optional_date('discount_until'),
        "description": request.form.get('description'),
        "image_url": main_img,
        "images": images,
        "featured": 'featured' in labels or request.form.get('featured') == 'on',
        "is_best_seller": 'best_seller' in labels or request.form.get('is_best_seller') == 'on',
        "is_pharmacist_choice": 'pharmacist_choice' in labels or request.form.get('is_pharmacist_choice') == 'on',
        "in_stock": request.form.get('in_stock') == 'on',
        "how_to_use": request.form.get('how_to_use'),
        "key_ingredients": request.form.get('key_ingredients'),
        "variant_group": request.form.get('variant_group', '').strip() or None,
        "option_groups": option_groups,
        "variants": variants,
        "labels": labels,
    }


@admin.route('/product/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_product():
    if request.method == 'POST':
        main_img = request.form.get('image_url')
        additional_str = request.form.get('additional_images', '')
        images = [main_img]
        if additional_str:
            extras = [x.strip() for x in additional_str.replace(',', '\n').split('\n') if x.strip()]
            for img in extras:
                if img != main_img:
                    images.append(img)

        option_groups, variants, base_price, base_discount = _parse_option_groups(
            request.form.get('option_groups_json', '')
        )
        product_data = _build_product_data(main_img, images, option_groups, variants, base_price, base_discount)
        Product.create(product_data)
        flash('Produkti u krijua me sukses!', 'success')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/product_form.html', product=None, categories=CATEGORIES)

@admin.route('/product/edit/<product_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_product(product_id):
    product = Product.get_by_id(product_id)
    if not product:
        flash('Produkti nuk ekziston.', 'danger')
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        main_img = request.form.get('image_url')
        additional_str = request.form.get('additional_images', '')
        images = [main_img]
        if additional_str:
            extras = [x.strip() for x in additional_str.replace(',', '\n').split('\n') if x.strip()]
            for img in extras:
                if img != main_img:
                    images.append(img)

        option_groups, variants, base_price, base_discount = _parse_option_groups(
            request.form.get('option_groups_json', ''),
            existing_variants=product.get('variants') or []
        )
        product_data = _build_product_data(main_img, images, option_groups, variants, base_price, base_discount)
        Product.update(product_id, product_data)
        flash('Produkti u përditësua me sukses!', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/product_form.html', product=product, categories=CATEGORIES)

@admin.route('/product/delete/<product_id>', methods=['POST'])
@login_required
@admin_required
def delete_product(product_id):
    Product.delete(product_id)
    flash('Produkti u fshi.', 'success')
    return redirect(url_for('admin.dashboard'))
@admin.route('/bulk-offers', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_offers():
    from models.db import mongo
    from bson import ObjectId
    
    if request.method == 'POST':
        action = request.form.get('action', 'apply')
        offer_name = request.form.get('offer_name', '').strip()
        selected_ids = request.form.getlist('selected_products')
        
        # New: delete offer by name action (from the new Active Offers section)
        if action == 'delete_named_offer':
            target_name = request.form.get('target_name')
            if target_name:
                mongo.db.products.update_many(
                    {"offer_name": target_name},
                    {"$set": {"discount_price": None, "discount_until": None, "offer_status": "expired", "offer_ended_at": datetime.now(), "updated_at": datetime.now()}}
                )
                flash(f'Oferta "{target_name}" u fshi me sukses.', 'success')
            return redirect(url_for('admin.bulk_offers'))

        # Check if products are selected for apply/remove
        if not selected_ids:
            flash('Gabim: Asnjë produkt nuk është zgjedhur. Ju lutem zgjidhni të paktën një produkt.', 'warning')
            return redirect(url_for('admin.bulk_offers'))

        try:
            offer_type = request.form.get('offer_type', 'discount')
            discount_from = request.form.get('discount_from')
            discount_until = request.form.get('discount_until')
            query = {"_id": {"$in": [ObjectId(pid) for pid in selected_ids]}}

            products = list(mongo.db.products.find(query))
            count = 0
            start_date = datetime.strptime(discount_from, '%Y-%m-%d') if discount_from else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            expiry_date = datetime.strptime(discount_until, '%Y-%m-%d') if discount_until else None

            discount_percent = float(request.form.get('discount_percent', 0)) if offer_type == 'discount' else 0
            multi_buy_type = request.form.get('multi_buy_type', '1+1') if offer_type == 'multi_buy' else None

            for p in products:
                pid_str = str(p['_id'])
                excluded_variant_ids = set(request.form.getlist(f'excl_variants_{pid_str}'))

                if action == 'apply':
                    price = float(p.get('price', 0))
                    if price <= 0:
                        continue

                    def _calc_discount(base_price):
                        if offer_type == 'discount':
                            return round(base_price * (1 - discount_percent / 100), 2)
                        elif offer_type == 'multi_buy':
                            return round(calculate_multi_buy_price(base_price, multi_buy_type), 2)
                        return None

                    variants = p.get('variants') or []
                    if variants:
                        # Update each variant individually
                        updated_variants = []
                        all_included = True
                        for v in variants:
                            vid = v.get('id', '')
                            new_v = dict(v)
                            if vid not in excluded_variant_ids:
                                vp = float(v.get('price') or price)
                                new_v['discount_price'] = _calc_discount(vp)
                            else:
                                new_v['discount_price'] = None
                                all_included = False
                            updated_variants.append(new_v)

                        # Top-level discount only if all variants are on offer
                        top_discount = _calc_discount(price) if all_included else None
                        update_data = {
                            "variants": updated_variants,
                            "discount_price": top_discount,
                            "discount_from": start_date,
                            "discount_until": expiry_date,
                            "offer_name": offer_name or None,
                            "offer_type": offer_type,
                            "offer_status": "active",
                            "offer_ended_at": None,
                            "multi_buy_type": multi_buy_type,
                            "updated_at": datetime.now(),
                        }
                    else:
                        update_data = {
                            "discount_price": _calc_discount(price),
                            "discount_from": start_date,
                            "discount_until": expiry_date,
                            "offer_name": offer_name or None,
                            "offer_type": offer_type,
                            "offer_status": "active",
                            "offer_ended_at": None,
                            "multi_buy_type": multi_buy_type,
                            "updated_at": datetime.now(),
                        }

                    mongo.db.products.update_one({"_id": p["_id"]}, {"$set": update_data})
                    count += 1

                else:  # remove action
                    variants = p.get('variants') or []
                    if variants:
                        cleared = [{**v, 'discount_price': None} for v in variants]
                        mongo.db.products.update_one(
                            {"_id": p["_id"]},
                            {"$set": {"variants": cleared, "discount_price": None, "discount_until": None,
                                      "offer_status": "expired", "offer_ended_at": datetime.now(), "updated_at": datetime.now()}}
                        )
                    else:
                        mongo.db.products.update_one(
                            {"_id": p["_id"]},
                            {"$set": {"discount_price": None, "discount_until": None,
                                      "offer_status": "expired", "offer_ended_at": datetime.now(), "updated_at": datetime.now()}}
                        )
                    count += 1
            
            msg = f'Sukses! Oferta u aplikua për {count} produkte.' if action == 'apply' else f'Sukses! Ofertat u hoqën nga {count} produkte.'
            flash(msg, 'success')
            return redirect(url_for('admin.bulk_offers'))
        except Exception as e:
            flash(f'Gabim: {str(e)}', 'danger')
            return redirect(url_for('admin.bulk_offers'))
        
    # GET Logic (Normalize duplicates)
    raw_categories = mongo.db.products.distinct('category')
    all_categories = {}
    for cat in raw_categories:
        if cat:
            subcats = list(mongo.db.products.distinct('subcategory', {'category': cat}))
            all_categories[cat] = [s for s in subcats if s]

    # Normalize brands to avoid duplicates like "Brand", "brand", " BRAND"
    raw_brands = mongo.db.products.distinct('brand')
    brand_map = {}
    for b in raw_brands:
        if b:
            norm = b.strip().lower()
            if norm not in brand_map:
                brand_map[norm] = b.strip()
    brands = sorted(brand_map.values(), key=lambda x: x.lower())
    
    all_products = list(mongo.db.products.find(
        {"is_deleted": {"$ne": True}},
        {
            "name": 1, "brand": 1, "category": 1, "subcategory": 1,
            "price": 1, "discount_price": 1, "offer_name": 1, "offer_type": 1,
            "offer_status": 1, "multi_buy_type": 1, "discount_until": 1,
            "image_url": 1, "in_stock": 1, "created_at": 1,
            "variants": 1, "option_groups": 1,
        }
    ).sort("created_at", -1))
    
    # Enhanced Active Offers Aggregation
    # We want Name, Type, Value, Expiry, Count
    pipeline = [
        {"$match": {"offer_name": {"$ne": None}, "offer_status": {"$ne": "expired"}, "is_deleted": {"$ne": True}}},
        {"$group": {
            "_id": "$offer_name",
            "count": {"$sum": 1},
            "start": {"$first": "$discount_from"},
            "expiry": {"$first": "$discount_until"},
            "type": {"$first": "$offer_type"},
            "multi_buy_type": {"$first": "$multi_buy_type"},
            "discount_percent": {"$first": {"$round": [{"$multiply": [{"$subtract": [1, {"$divide": ["$discount_price", "$price"]}]}, 100]}, 0]}}
        }},
        {"$sort": {"_id": 1}}
    ]
    raw_active = list(mongo.db.products.aggregate(pipeline))
    active_offers_info = []
    for r in raw_active:
        offer_type = r.get("type", "discount")
        if offer_type == "discount":
            value = r.get("discount_percent", 0) or 0
        else:
            value = r.get("multi_buy_type", "1+1")
        
        active_offers_info.append({
            "name": r["_id"],
            "count": r["count"],
            "start": r["start"].strftime('%Y-%m-%d') if r.get("start") else None,
            "expiry": r["expiry"].strftime('%Y-%m-%d') if r.get("expiry") else None,
            "type": offer_type,
            "value": value
        })

    return render_template('admin/bulk_offers.html', 
                         categories=all_categories, 
                         brands=brands, 
                         all_products=all_products,
                         active_offers_info=active_offers_info)


def _resolve_banner_link_value(link_type, form):
    """Read link_value from the correct named form field for the given link_type.
    Named selects (link_value_brand, link_value_category, link_value_offer) are
    always submitted by the browser regardless of JS. The hidden link_value field
    is a JS fallback — we prefer the named fields so saves work without JS too."""
    if link_type == 'brand':
        return (form.get('link_value_brand') or form.get('link_value') or '').strip()
    elif link_type == 'category':
        return (form.get('link_value_category') or form.get('link_value') or '').strip()
    elif link_type == 'offer':
        return (form.get('link_value_offer') or form.get('link_value') or '').strip()
    else:
        # custom_products and all_offers both rely on the JS-populated hidden field
        return (form.get('link_value') or '').strip()


def _get_banner_offer_options():
    # Only fetch the fields needed to build the offer picker — no large text fields.
    products = Product.get_all_lean(projection={
        "name": 1, "offer_name": 1, "offer_type": 1,
        "offer_status": 1, "discount_price": 1, "discount_until": 1,
    }) or []
    offers = []
    seen = set()
    for product in products:
        if not Product._offer_is_active(product):
            continue
        offer_name = str(product.get('offer_name') or '').strip()
        offer_type = str(product.get('offer_type') or '').strip()
        label = offer_name or offer_type
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        offers.append({
            'value': label,
            'label': f"{label} - {product.get('name', 'Produkt')}"
        })
    return offers


def calculate_multi_buy_price(original_price, multi_buy_type):
    """Calculate the effective price per unit based on multi-buy offer"""
    if multi_buy_type == "1+1":
        # Buy 1, Get 1 Free: effective price = original_price / 2
        return original_price / 2
    elif multi_buy_type == "2+1":
        # Buy 2, Get 1 Free: effective price = 2 * original_price / 3
        return (2 * original_price) / 3
    elif multi_buy_type == "3+1":
        # Buy 3, Get 1 Free: effective price = 3 * original_price / 4
        return (3 * original_price) / 4
    elif multi_buy_type == "buy2get50":
        # Buy 2, Get 50% off: effective price when buying 2 = original_price + (original_price * 0.5)
        # So per unit: (original_price + (original_price * 0.5)) / 2 = original_price * 0.75
        return original_price * 0.75
    return original_price


@admin.route('/banners', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_banners():
    if request.method == 'POST':
        # Create
        current_banners = Banner.get_all()
        if any(b.get('sort_order') is None for b in current_banners):
            Banner.normalize_sort_order()
            current_banners = Banner.get_all()

        sort_order = _form_optional_int('sort_order')
        if sort_order is None:
            sort_order = (max([int(b.get('sort_order') or 0) for b in current_banners], default=0) + 1)
        link_type = request.form.get("link_type")
        link_value = _resolve_banner_link_value(link_type, request.form)
        data = {
            "image_url": request.form.get("image_url"),
            "link_type": link_type,
            "link_value": link_value,
            "is_active": request.form.get("is_active") == 'on',
            "expires_at": _form_optional_date('expires_at'),
            "sort_order": sort_order,
        }
        Banner.create(data)
        flash("Baneri u shtua me sukses!", "success")
        return redirect(url_for("admin.manage_banners"))
        
    banners = Banner.get_all()
    if any(b.get('sort_order') is None for b in banners):
        Banner.normalize_sort_order()
        banners = Banner.get_all()
    # We should get existing brands and categories to populate the dropdowns
    categories = list(CATEGORIES.keys())
    raw_brands = mongo.db.products.distinct("brand")
    brands = [b for b in raw_brands if b]
    
    # Only fetch _id and name for the product picker dropdown — the full document is not needed.
    all_products = Product.get_all_lean(projection={"name": 1, "image_url": 1})
    available_offers = _get_banner_offer_options()
    next_banner_order = (max([int(b.get('sort_order') or 0) for b in banners], default=0) + 1)
    today = datetime.now().date()
    return render_template('admin/banners.html', banners=banners, categories=categories, brands=brands, all_products=all_products, available_offers=available_offers, next_banner_order=next_banner_order, today=today)

@admin.route('/banners/edit/<banner_id>', methods=['POST'])
@login_required
@admin_required
def edit_banner(banner_id):
    link_type = request.form.get("link_type")
    link_value = _resolve_banner_link_value(link_type, request.form)
    data = {
        "image_url": request.form.get("image_url"),
        "link_type": link_type,
        "link_value": link_value,
        "is_active": request.form.get("is_active") == 'on',
        "expires_at": _form_optional_date('expires_at'),
        "sort_order": _form_optional_int('sort_order'),
    }
    Banner.update(banner_id, data)
    flash("Baneri u perditesua!", "success")
    return redirect(url_for("admin.manage_banners"))


@admin.route('/banners/reorder/<banner_id>', methods=['POST'])
@login_required
@admin_required
def reorder_banner(banner_id):
    direction = request.form.get('direction', '')
    banners = Banner.get_all()
    current_index = next((i for i, b in enumerate(banners) if str(b.get('_id')) == str(banner_id)), None)
    if current_index is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False}), 404
        flash('Baneri nuk u gjet.', 'danger')
        return redirect(url_for('admin.manage_banners'))

    target_index = current_index - 1 if direction == 'up' else current_index + 1
    if target_index < 0 or target_index >= len(banners):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'reason': 'boundary'}), 400
        return redirect(url_for('admin.manage_banners'))

    cb, tb = banners[current_index], banners[target_index]
    co = int(cb.get('sort_order') or current_index + 1)
    to_ = int(tb.get('sort_order') or target_index + 1)
    Banner.update(str(cb['_id']), {'sort_order': to_})
    Banner.update(str(tb['_id']), {'sort_order': co})

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True})
    flash('Renditja e banerit u përditësua.', 'success')
    return redirect(url_for('admin.manage_banners'))

@admin.route('/banners/reorder-bulk', methods=['POST'])
@login_required
@admin_required
def reorder_banners_bulk():
    data = request.get_json(silent=True) or {}
    ids = data.get('order', [])
    if not ids:
        return jsonify({'ok': False}), 400
    for idx, banner_id in enumerate(ids, start=1):
        try:
            Banner.update(banner_id, {'sort_order': idx})
        except Exception:
            pass
    return jsonify({'ok': True})


@admin.route('/banners/delete/<banner_id>', methods=['POST'])
@login_required
@admin_required
def delete_banner(banner_id):
    Banner.delete(banner_id)
    flash("Baneri u fshi!", "info")
    return redirect(url_for("admin.manage_banners"))



@admin.route('/newsletter/generate', methods=['POST'])
@login_required
@admin_required
def newsletter_generate():
    """Call Gemini API to generate newsletter subject + body."""
    import os, json as _json
    prompt = request.form.get('prompt', '').strip()
    if not prompt:
        return jsonify({'error': 'Prompt është bosh.'}), 400

    api_key = os.getenv('GEMINI_API_KEY', '')
    api_url = os.getenv('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
    model   = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

    if not api_key:
        return jsonify({'error': 'GEMINI_API_KEY nuk është konfiguruar.'}), 500

    # Fetch active offer products for context
    offer_products = list(mongo.db.products.find(
        {'discount_price': {'$exists': True, '$ne': None}, 'in_stock': True},
        {'name': 1, 'price': 1, 'discount_price': 1, 'brand': 1}
    ).limit(6))
    offer_lines = '\n'.join(
        f"- {p.get('brand','') + ' ' if p.get('brand') else ''}{p['name']}: "
        f"€{p.get('discount_price',0):.2f} (ishte €{p.get('price',0):.2f})"
        for p in offer_products
    ) or '(Nuk ka oferta aktive)'

    system_prompt = (
        "Ti je asistent i marketingut për Barnatore Meld Pharm, një barnatore online në Prishtinë, Kosovë. "
        "Shkruaj emaile profesionale të buletinit (newsletter) në gjuhën shqipe. "
        "Email-i duhet të jetë miqësor, bindës dhe me ton profesional. "
        "Kthe VETËM një objekt JSON me dy fusha: \"subject\" (titulli i email-it) dhe \"content\" (trupi i email-it si tekst i thjeshtë me paragrafë, pa HTML). "
        "Mos shto asgjë tjetër jashtë JSON-it.\n\n"
        f"Produktet me ofertë aktive:\n{offer_lines}"
    )
    user_message = f"Tema/Udhëzimi: {prompt}"

    # Use same HTTP approach as the chatbot (urllib + certifi SSL context)
    import urllib.request as _urllib_req
    import ssl as _ssl
    import certifi as _certifi
    import time as _time

    api_url = os.getenv('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
    ssl_ctx = _ssl.create_default_context(cafile=_certifi.where())

    # Try requested model first, fall back to gemini-1.5-flash if 503
    models_to_try = [model, 'gemini-1.5-flash']

    for attempt_model in models_to_try:
        payload_bytes = _json.dumps({
            "model": attempt_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message}
            ],
            "max_tokens": 900,
            "temperature": 0.75
        }).encode('utf-8')

        req = _urllib_req.Request(
            api_url,
            data=payload_bytes,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
            method='POST'
        )
        try:
            with _urllib_req.urlopen(req, timeout=30, context=ssl_ctx) as resp:
                result = _json.loads(resp.read().decode('utf-8'))
            text = result['choices'][0]['message']['content'].strip()

            # Try to extract JSON from the response however it's formatted
            subject, content = '', ''
            try:
                # Strip markdown code fences
                clean = text
                if '```' in clean:
                    parts = clean.split('```')
                    # take the content inside the first fence
                    clean = parts[1] if len(parts) > 1 else parts[0]
                    if clean.lower().startswith('json'):
                        clean = clean[4:]
                    clean = clean.strip()
                parsed = _json.loads(clean)
                subject = parsed.get('subject', '')
                content = parsed.get('content', '')
            except _json.JSONDecodeError:
                # Fallback: look for a JSON object anywhere in the text
                import re as _re
                m = _re.search(r'\{[\s\S]*\}', text)
                if m:
                    try:
                        parsed = _json.loads(m.group())
                        subject = parsed.get('subject', '')
                        content = parsed.get('content', '')
                    except Exception:
                        pass

                # Last resort: treat first line as subject, rest as content
                if not subject and not content:
                    lines = text.strip().splitlines()
                    subject = lines[0].lstrip('#').strip() if lines else ''
                    content = '\n'.join(lines[1:]).strip() if len(lines) > 1 else text

            return jsonify({'subject': subject, 'content': content})
        except Exception as e:
            err = str(e)
            if '503' in err and attempt_model != models_to_try[-1]:
                _time.sleep(1)
                continue  # try fallback model
            return jsonify({'error': f'Gabim: {err[:250]}'}), 500


@admin.route('/test-email')
@login_required
@admin_required
def test_email():
    """Send a test email to verify SMTP is working. Visit /admin/test-email"""
    import os as _os
    from models.email_utils import _get_smtp_config, _send_simple_email
    cfg = _get_smtp_config()
    recipient = _os.getenv('ORDER_NOTIFY_EMAIL') or cfg['sender_email']
    ok, msg = _send_simple_email(
        cfg, recipient,
        'Test Email — Meld Pharm',
        'Ky është një email testues nga Meld Pharm.',
        '<p>Ky është një <strong>email testues</strong> nga Meld Pharm. SMTP po funksionon!</p>'
    )
    if ok:
        flash(f'Email testues u dërgua me sukses tek {recipient}!', 'success')
    else:
        flash(f'SMTP dështoi: {msg}', 'danger')
    return redirect(url_for('admin.dashboard'))


@admin.route('/cleanup/chats', methods=['POST'])
@login_required
@admin_required
def cleanup_chats():
    """Delete conversations older than N days (default 30)."""
    days = int(request.form.get('days', 30))
    cutoff = datetime.utcnow() - __import__('datetime').timedelta(days=days)
    result = mongo.db.conversations.delete_many({'updated_at': {'$lt': cutoff}})
    flash(f'{result.deleted_count} biseda u fshinë (më të vjetra se {days} ditë).', 'success')
    return redirect(url_for('admin.dashboard'))


@admin.route('/orders/bulk_status', methods=['POST'])
@login_required
@admin_required
def bulk_order_status():
    from bson import ObjectId
    order_ids = request.form.getlist('order_ids')
    new_status = request.form.get('status', '').strip()
    valid_statuses = ['Pending', 'Konfirmuar', 'Delivering', 'Delivered', 'Anuluar', 'Refuzuar']
    if not order_ids or new_status not in valid_statuses:
        flash('Të dhëna të pavlefshme.', 'danger')
        return redirect(url_for('admin.orders'))

    status_map = {
        'Delivering': 'Në Dërgesë',
        'Delivered':  'Dorëzuar',
    }
    display_status = status_map.get(new_status, new_status)
    updated = 0
    for oid in order_ids:
        try:
            mongo.db.orders.update_one(
                {'_id': ObjectId(oid)},
                {'$set': {'status': display_status, 'updated_at': datetime.utcnow()}}
            )
            updated += 1
        except Exception:
            pass
    flash(f'{updated} porosi u ndryshuan në "{display_status}".', 'success')
    return redirect(url_for('admin.orders', status=request.form.get('status_filter', '')))


@admin.route('/newsletter/send-test', methods=['POST'])
@login_required
@admin_required
def newsletter_send_test():
    """Send the composed newsletter to a single test address only."""
    from bson import ObjectId
    from models.email_utils import SITE_BASE_URL, _get_smtp_config, _send_simple_email

    subject      = request.form.get('subject', '').strip() or 'Test Newsletter — Meld Pharm'
    template     = request.form.get('template', 'grid')
    headline     = request.form.get('headline', '').strip()
    intro_text   = request.form.get('intro_text', '').strip()
    product_ids  = request.form.getlist('product_ids')
    accent_color = request.form.get('accent_color', '#4F5D4E').strip() or '#4F5D4E'
    cta_text     = request.form.get('cta_text', 'Shiko Të Gjitha Produktet').strip() or 'Shiko Të Gjitha Produktet'
    footer_note  = request.form.get('footer_note', '').strip()
    test_email   = request.form.get('test_email', '').strip()

    if not test_email:
        return {'ok': False, 'msg': 'Adresa email është e zbrazët.'}, 400

    selected_products = []
    for pid in product_ids[:8]:
        try:
            p = mongo.db.products.find_one({'_id': ObjectId(pid)})
            if p:
                selected_products.append(p)
        except Exception:
            pass

    html_body  = _build_newsletter_html(template, headline, intro_text, selected_products, SITE_BASE_URL,
                                        accent_color=accent_color, cta_text=cta_text, footer_note=footer_note)
    text_body  = f"[TEST] {headline}\n\n{intro_text}\n\nVisitoni: {SITE_BASE_URL}"
    test_subj  = f"[TEST] {subject}"

    cfg = _get_smtp_config()
    import logging as _log
    _log.info(f"[newsletter_send_test] sending to={test_email} subj={test_subj!r} smtp_host={cfg.get('smtp_host')} sender={cfg.get('sender_email')}")
    ok, msg = _send_simple_email(cfg, test_email, test_subj, text_body, html_body)
    _log.info(f"[newsletter_send_test] result ok={ok} msg={msg!r}")
    if ok:
        return jsonify({'ok': True, 'msg': f'Email testues u dërgua te {test_email}'})
    return jsonify({'ok': False, 'msg': msg}), 500


@admin.route('/newsletter', methods=['GET', 'POST'])
@login_required
@admin_required
def newsletter():
    import os as _os
    from bson import ObjectId
    from models.email_utils import SITE_BASE_URL, _get_smtp_config, _send_simple_email

    sent_count = 0

    if request.method == 'POST':
        subject    = request.form.get('subject', '').strip()
        template   = request.form.get('template', 'grid')
        headline   = request.form.get('headline', '').strip()
        intro_text = request.form.get('intro_text', '').strip()
        product_ids = request.form.getlist('product_ids')
        accent_color = request.form.get('accent_color', '#4F5D4E').strip() or '#4F5D4E'
        cta_text     = request.form.get('cta_text', 'Shiko Të Gjitha Produktet').strip() or 'Shiko Të Gjitha Produktet'
        footer_note  = request.form.get('footer_note', '').strip()

        if not subject:
            flash('Titulli (subject) është i detyrueshëm.', 'danger')
        else:
            # Fetch selected products
            selected_products = []
            for pid in product_ids[:8]:
                try:
                    p = mongo.db.products.find_one({'_id': ObjectId(pid)})
                    if p:
                        selected_products.append(p)
                except Exception:
                    pass

            html_body = _build_newsletter_html(template, headline, intro_text, selected_products, SITE_BASE_URL, accent_color=accent_color, cta_text=cta_text, footer_note=footer_note)
            text_body = f"{headline}\n\n{intro_text}\n\nVisitoni: {SITE_BASE_URL}"

            subscribers = User.get_newsletter_subscribers()
            failed = 0
            cfg = _get_smtp_config()
            for sub in subscribers:
                ok, msg = _send_simple_email(cfg, sub['email'], subject, text_body, html_body)
                if ok:
                    sent_count += 1
                else:
                    failed += 1
            if sent_count:
                flash(f'Buletini u dërgua te {sent_count} abonentë.', 'success')
            if failed:
                flash(f'{failed} emaile nuk u dërguan.', 'warning')

    subscribers = User.get_newsletter_subscribers()
    registered_sub_count = mongo.db.users.count_documents({'newsletter_subscribed': True})
    guest_sub_count = len(subscribers) - registered_sub_count
    pending_orders_count = mongo.db.orders.count_documents({'status': 'Pending'})

    # All products for picker (show offers first)
    all_products = list(mongo.db.products.find(
        {}, {'name': 1, 'brand': 1, 'price': 1, 'discount_price': 1, 'image_url': 1, 'category': 1, 'in_stock': 1}
    ).sort([('discount_price', -1)]).limit(120))

    # Build smart defaults for the newsletter form
    offer_products = [p for p in all_products if p.get('discount_price')]
    max_pct = 0
    brands_on_offer = []
    cats_on_offer = []
    for p in offer_products[:12]:
        price, disc = p.get('price', 0), p.get('discount_price', 0)
        if price:
            pct = round((price - disc) / price * 100)
            if pct > max_pct:
                max_pct = pct
        if p.get('brand') and p['brand'] not in brands_on_offer:
            brands_on_offer.append(p['brand'])
        if p.get('category') and p['category'] not in cats_on_offer:
            cats_on_offer.append(p['category'])

    import locale
    week_num = datetime.utcnow().isocalendar()[1]
    month_alb = ['Janar','Shkurt','Mars','Prill','Maj','Qershor','Korrik','Gusht','Shtator','Tetor','Nëntor','Dhjetor'][datetime.utcnow().month - 1]

    default_subject = f"Ofertat e Javës {week_num} — Zbritje deri {max_pct}% | Meld Pharm" if max_pct else f"Produkte të Reja — {month_alb} | Meld Pharm"
    brand_line = ', '.join(brands_on_offer[:3]) if brands_on_offer else 'brendeve tona'
    cat_line   = ', '.join(cats_on_offer[:3]).lower() if cats_on_offer else 'produkteve tona'
    default_headline = f"Ofertat e Javës {week_num} kanë ardhur! ✨" if offer_products else f"Produkte të Reja — {month_alb}"
    default_intro = (
        f"Kjo javë kemi zgjedhur për ju ofertat tona më të mira me zbritje deri në {max_pct}%. "
        f"Gjeni produkte nga {brand_line} në kategorinë e {cat_line}. "
        f"Të gjitha ofertat janë të disponueshme në barnatoren tonë online — sasi të kufizuara!"
        if offer_products else
        f"Kemi zgjedhur për ju produktet tona më të reja dhe cilësore. "
        f"Vizitoni faqen tonë dhe zbuloni gjithçka që kemi në dispozicion për shëndetin dhe mirëqenien tuaj."
    )

    site_base = _os.getenv('SITE_BASE_URL', 'https://barnatoremeldpharm.com')
    return render_template('admin/newsletter.html',
                           subscriber_count=registered_sub_count,
                           guest_sub_count=guest_sub_count,
                           sent_count=sent_count,
                           pending_orders_count=pending_orders_count,
                           all_products=all_products,
                           site_base_url=site_base,
                           default_subject=default_subject,
                           default_headline=default_headline,
                           default_intro=default_intro)


def _build_newsletter_html(template, headline, intro_text, products, base_url,
                           accent_color='#4F5D4E', cta_text='Shiko Të Gjitha Produktet', footer_note=''):
    """Generate a beautiful inline-styled HTML email."""
    _sans  = "font-family:'DM Sans',Arial,sans-serif"
    _serif = "font-family:'Playfair Display',Georgia,'Times New Roman',serif"

    header = f"""
    <div style="background:{accent_color};height:5px;"></div>
    <div style="background:#ffffff;padding:22px 40px;text-align:center;border-bottom:1px solid #eef0ed;">
      <img src="https://res.cloudinary.com/drljgepgy/image/upload/v1788282469/ChatGPT_Image_Sep_1_2026_at_07_06_44_PM_kluztv.png"
           alt="Barnatore Meld Pharm" width="310"
           style="display:inline-block;max-width:310px;height:auto;">
    </div>
    """

    hero = ""
    if headline or intro_text:
        hero = f"""
        <div style="padding:36px 44px 28px;text-align:center;border-bottom:1px solid #eef0ed;">
          {('<h1 style="margin:0 0 14px;' + _serif + ';font-size:28px;font-weight:800;color:#1a1f18;line-height:1.2;letter-spacing:-0.3px;">' + headline + '</h1>') if headline else ''}
          {('<p style="margin:0;' + _sans + ';font-size:15px;font-weight:400;color:#6b7a6e;line-height:1.8;max-width:440px;margin-left:auto;margin-right:auto;">' + intro_text + '</p>') if intro_text else ''}
        </div>
        """

    products_html = ""
    if products:
        if template == 'list':
            products_html = _products_list(products, base_url, accent_color)
        else:
            products_html = _products_grid(products, base_url, accent_color)

    cta = f"""
    <div style="padding:28px 40px;text-align:center;border-top:1px solid #f1f5f9;">
      <a href="{base_url}/products?discount_only=true" style="display:inline-block;background:{accent_color};color:#fff;text-decoration:none;font-family:'DM Sans',Arial,sans-serif;font-size:14px;font-weight:700;padding:14px 38px;border-radius:10px;letter-spacing:0.4px;">
        {cta_text}
      </a>
    </div>
    """

    footer_extra = ('<p style="margin:8px 0 0;' + _sans + ';font-size:12px;color:#6b7280;font-style:italic;">' + footer_note + '</p>') if footer_note else ''
    footer = f"""
    <div style="background:#f8faf7;padding:22px 40px;text-align:center;border-top:1px solid #e8ebe6;">
      <p style="margin:0 0 4px;font-family:'DM Sans',Arial,sans-serif;font-size:11px;font-weight:500;color:#9aa095;letter-spacing:0.2px;">Barnatore Meld Pharm · 72 Eqrem Çabej, Prishtinë 10000</p>
      <p style="margin:0;font-family:'DM Sans',Arial,sans-serif;font-size:11px;color:#9aa095;">+383 45 590 455 · <a href="{base_url}" style="color:{accent_color};text-decoration:none;">{base_url.replace('https://','')}</a></p>
      {footer_extra}
    </div>
    """

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=DM+Sans:wght@400;500;700&display=swap');
</style>
</head>
<body style="margin:0;padding:0;background:#F7F3EE;font-family:'DM Sans',Arial,sans-serif;">
  <div style="max-width:620px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    {header}{hero}{products_html}{cta}{footer}
  </div>
</body></html>"""


_EMAIL_SANS  = "font-family:'DM Sans',Arial,sans-serif"
_EMAIL_SERIF = "font-family:'Playfair Display',Georgia,'Times New Roman',serif"


def _product_price_html(p, accent_color='#4F5D4E'):
    price = p.get('price', 0)
    disc  = p.get('discount_price')
    if disc:
        pct = round((price - disc) / price * 100) if price else 0
        return (
            f'<span style="{_EMAIL_SANS};font-size:11px;color:#9aa095;text-decoration:line-through;">€{price:.2f}</span> '
            f'<span style="{_EMAIL_SANS};font-size:14px;font-weight:700;color:{accent_color};">€{disc:.2f}</span> '
            f'<span style="{_EMAIL_SANS};background:#fef3c7;color:#92400e;font-size:9px;font-weight:700;padding:2px 6px;border-radius:5px;margin-left:3px;">-{pct}%</span>'
        )
    return f'<span style="{_EMAIL_SANS};font-size:14px;font-weight:700;color:#1a1f18;">€{price:.2f}</span>'


def _product_card_grid(p, base_url, accent_color='#4F5D4E', width='45%'):
    img = p.get('image_url', '')
    name = p.get('name', '')
    brand = p.get('brand', '')
    pid = str(p['_id'])
    return f"""
    <td style="width:{width};padding:8px;vertical-align:top;">
      <a href="{base_url}/product/{pid}" style="text-decoration:none;display:block;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #eef0ed;">
        <img src="{img}" alt="{name}" width="100%" style="display:block;height:180px;object-fit:contain;background:#fff;padding:10px;box-sizing:border-box;">
        <div style="padding:12px 14px 14px;">
          {('<div style="' + _EMAIL_SANS + ';font-size:9px;font-weight:700;color:#9aa095;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;height:14px;overflow:hidden;">' + brand + '</div>') if brand else '<div style="height:18px;"></div>'}
          <div style="{_EMAIL_SANS};font-size:12px;font-weight:500;color:#1a1f18;margin-bottom:7px;line-height:1.45;height:34px;overflow:hidden;">{name}</div>
          <div style="margin-bottom:9px;height:22px;overflow:hidden;">{_product_price_html(p, accent_color)}</div>
          <div style="background:{accent_color};color:#fff;text-align:center;padding:7px;border-radius:7px;{_EMAIL_SANS};font-size:10px;font-weight:700;letter-spacing:0.3px;">Shiko Produktin →</div>
        </div>
      </a>
    </td>"""


def _products_grid(products, base_url, accent_color='#4F5D4E'):
    rows = ""
    pairs = [products[i:i+2] for i in range(0, len(products), 2)]
    for pair in pairs:
        cells = _product_card_grid(pair[0], base_url, accent_color)
        if len(pair) > 1:
            cells += _product_card_grid(pair[1], base_url, accent_color)
        else:
            cells += '<td style="width:45%;padding:8px;"></td>'
        rows += f'<tr>{cells}</tr>'
    return f"""
    <div style="padding:24px 28px;">
      <p style="margin:0 0 4px;font-family:'DM Sans',Arial,sans-serif;font-size:11px;font-weight:700;color:{accent_color};text-transform:uppercase;letter-spacing:1.2px;">Produktet e Zgjedhura</p>
      <h2 style="margin:0 0 18px;font-family:'Playfair Display',Georgia,'Times New Roman',serif;font-size:20px;font-weight:800;color:#1a1f18;line-height:1.2;">Ofertat e Limituara</h2>
      <table width="100%" cellpadding="0" cellspacing="0"><tbody>{rows}</tbody></table>
    </div>"""


def _products_list(products, base_url, accent_color='#4F5D4E'):
    items = ""
    for p in products:
        img = p.get('image_url', '')
        name = p.get('name', '')
        brand = p.get('brand', '')
        pid = str(p['_id'])
        items += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #f0f2ef;">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
              <td style="width:84px;vertical-align:top;padding-right:14px;">
                <img src="{img}" alt="{name}" width="72" height="72" style="border-radius:10px;object-fit:contain;background:#f8faf7;display:block;padding:4px;box-sizing:border-box;">
              </td>
              <td style="vertical-align:top;">
                {('<div style="' + _EMAIL_SANS + ';font-size:9px;color:#9aa095;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:3px;">' + brand + '</div>') if brand else ''}
                <div style="{_EMAIL_SANS};font-size:13px;font-weight:500;color:#1a1f18;margin:2px 0 6px;line-height:1.4;">{name}</div>
                <div style="margin-bottom:8px;">{_product_price_html(p, accent_color)}</div>
                <a href="{base_url}/product/{pid}" style="{_EMAIL_SANS};font-size:11px;font-weight:700;color:{accent_color};text-decoration:none;letter-spacing:0.2px;">Shiko Produktin →</a>
              </td>
            </tr></table>
          </td>
        </tr>"""
    return f"""
    <div style="padding:24px 36px;">
      <p style="margin:0 0 4px;font-family:'DM Sans',Arial,sans-serif;font-size:11px;font-weight:700;color:{accent_color};text-transform:uppercase;letter-spacing:1.2px;">Produktet e Zgjedhura</p>
      <h2 style="margin:0 0 16px;font-family:'Playfair Display',Georgia,'Times New Roman',serif;font-size:20px;font-weight:800;color:#1a1f18;line-height:1.2;">Ofertat e Limituara</h2>
      <table width="100%" cellpadding="0" cellspacing="0"><tbody>{items}</tbody></table>
    </div>"""



@admin.route('/product/toggle_stock/<product_id>', methods=['POST'])
@login_required
@admin_required
def toggle_stock(product_id):
    from bson import ObjectId
    product = mongo.db.products.find_one({'_id': ObjectId(product_id)}, {'in_stock': 1})
    if product:
        new_val = not bool(product.get('in_stock', True))
        mongo.db.products.update_one({'_id': ObjectId(product_id)}, {'$set': {'in_stock': new_val}})
        flash(f'Stoku u ndryshua në {"Në Stok" if new_val else "Jo Stok"}.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin.route('/users')
@login_required
@admin_required
def users():
    raw_users = list(mongo.db.users.find(
        {},
        {"username": 1, "email": 1, "is_admin": 1, "created_at": 1, "newsletter_subscribed": 1}
    ).sort("created_at", -1))

    # Count orders per user by email
    pipeline = [
        {"$group": {"_id": "$email", "count": {"$sum": 1}}}
    ]
    order_counts = {r['_id']: r['count'] for r in mongo.db.orders.aggregate(pipeline)}

    for u in raw_users:
        u['order_count'] = order_counts.get(u.get('email'), 0)

    # Use the same subscriber source as the newsletter page for consistency
    from models.user import User as _User
    all_subs = _User.get_newsletter_subscribers()
    total_subscriber_count = len(all_subs)

    # Guests = subscribers who are NOT in the registered users collection
    registered_emails = {u.get('email', '') for u in raw_users}
    guest_subscribers = [s for s in all_subs if s.get('email') not in registered_emails]

    pending_orders_count = mongo.db.orders.count_documents({'status': 'Pending'})
    return render_template('admin/users.html',
                           users=raw_users,
                           guest_subscribers=guest_subscribers,
                           total_subscriber_count=total_subscriber_count,
                           pending_orders_count=pending_orders_count)


@admin.route('/users/toggle_admin/<user_id>', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    from bson import ObjectId
    if str(current_user.get_id()) == str(user_id):
        flash('Nuk mund të ndryshoni rolin tuaj.', 'danger')
        return redirect(url_for('admin.users'))
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)}, {'is_admin': 1})
    if user:
        new_val = not bool(user.get('is_admin', False))
        mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': {'is_admin': new_val}})
        flash('Roli u ndryshua me sukses.', 'success')
    return redirect(url_for('admin.users'))


@admin.route('/analytics')
@login_required
@admin_required
def analytics_page():
    from bson import ObjectId
    from collections import defaultdict

    days = int(request.args.get('days', 30))
    days = days if days in (7, 30, 90) else 30
    cutoff = datetime.utcnow() - timedelta(days=days)
    now = datetime.utcnow()
    six_months_ago = now - timedelta(days=186)
    _to_double = {"$convert": {"input": "$grand_total", "to": "double", "onError": 0, "onNull": 0}}

    # ── Sales data (always 6 months) ─────────────────────────────
    sales_facet = list(mongo.db.orders.aggregate([
        {"$match": {"created_at": {"$gte": six_months_ago}}},
        {"$facet": {
            "monthly_trend": [
                {"$group": {
                    "_id": {"y": {"$year": "$created_at"}, "m": {"$month": "$created_at"}},
                    "revenue": {"$sum": _to_double},
                    "orders": {"$sum": 1}
                }},
                {"$sort": {"_id.y": 1, "_id.m": 1}}
            ],
            "most_ordered": [
                {"$unwind": "$items"},
                {"$group": {
                    "_id": {"$toString": {"$ifNull": ["$items.product_id", "$items._id"]}},
                    "name": {"$first": "$items.name"},
                    "count": {"$sum": {"$convert": {"input": "$items.quantity", "to": "int", "onError": 1, "onNull": 1}}}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 8}
            ]
        }}
    ]))
    sf = sales_facet[0] if sales_facet else {}

    # Monthly trend (last 6 months)
    monthly_map = {(r["_id"]["y"], r["_id"]["m"]): r for r in (sf.get("monthly_trend") or [])}
    trend_labels, trend_revenue, trend_orders = [], [], []
    for i in range(5, -1, -1):
        m = (now.month - i - 1) % 12 + 1
        y = now.year - ((now.month - i - 1) // 12)
        row = monthly_map.get((y, m), {})
        import calendar as _cal
        trend_labels.append(_cal.month_abbr[m])
        trend_revenue.append(round(float(row.get("revenue") or 0), 2))
        trend_orders.append(int(row.get("orders") or 0))

    # Resolve most-ordered product images
    most_ordered = []
    mo_items = sf.get("most_ordered") or []
    if mo_items:
        mo_ids = [ObjectId(str(i["_id"])) for i in mo_items if i.get("_id") and ObjectId.is_valid(str(i.get("_id", "")))]
        img_map = {str(p["_id"]): p.get("image_url", "") for p in mongo.db.products.find(
            {"_id": {"$in": mo_ids}, "is_deleted": {"$ne": True}}, {"image_url": 1})} if mo_ids else {}
        for item in mo_items:
            pid = str(item.get("_id", ""))
            if pid not in img_map:
                continue  # product deleted or not found
            most_ordered.append({"pid": pid,
                                  "name": item.get("name", "—"),
                                  "image_url": img_map.get(pid, ""),
                                  "order_count": item.get("count", 0)})

    # ── Product data ──────────────────────────────────────────────
    prod_facet = list(mongo.db.products.aggregate([
        {"$match": {"is_deleted": {"$ne": True}}},
        {"$facet": {
            "brand_dist": [
                {"$match": {"brand": {"$nin": [None, ""]}}},
                {"$group": {"_id": {"$toLower": {"$trim": {"input": {"$ifNull": ["$brand", ""]}}}},
                             "brand": {"$first": "$brand"}, "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}, {"$limit": 8}
            ],
            "cat_dist": [
                {"$match": {"category": {"$nin": [None, ""]}}},
                {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}, {"$limit": 8}
            ],
            "most_liked": [
                {"$project": {"name": 1, "image_url": 1,
                               "fav_count": {"$size": {"$ifNull": ["$favorites", []]}}}},
                {"$sort": {"fav_count": -1}}, {"$limit": 8}
            ]
        }}
    ]))
    pf = prod_facet[0] if prod_facet else {}
    brand_distribution = {r["brand"].title(): r["count"] for r in (pf.get("brand_dist") or []) if r.get("brand")}
    category_sales = {r["_id"].title(): r["count"] for r in (pf.get("cat_dist") or []) if r.get("_id")}
    most_liked = pf.get("most_liked") or []

    # ── Behaviour events (period-filtered) ───────────────────────
    raw = list(mongo.db.events.aggregate([
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$facet": {
            # Unique sessions per event type (one session opening 10 products = 1 view session)
            "funnel": [
                {"$group": {"_id": {"e": "$e", "sid": "$sid"}}},
                {"$group": {"_id": "$_id.e", "n": {"$sum": 1}}}
            ],
            # Total product page view events (not de-duped by session — shows real browse volume)
            "total_vp": [
                {"$match": {"e": "vp"}},
                {"$count": "n"}
            ],
            "top_viewed": [
                {"$match": {"e": "vp", "pid": {"$exists": True}}},
                {"$group": {"_id": "$pid", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}, {"$limit": 10}
            ],
            "top_carted": [
                {"$match": {"e": "ac", "pid": {"$exists": True}}},
                {"$group": {"_id": "$pid", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}, {"$limit": 10}
            ],
            # Unique visitors = all distinct sessions with any tracked event
            "unique_visitors": [{"$group": {"_id": "$sid"}}, {"$count": "n"}],
            "daily_trend": [
                {"$group": {"_id": {
                    "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
                    "e": "$e"
                }, "n": {"$sum": 1}}},
                {"$sort": {"_id.day": 1}}
            ]
        }}
    ]))
    f = raw[0] if raw else {}

    def pct(num, denom):
        return round(num / denom * 100, 1) if denom else 0

    funnel_map = {r["_id"]: r["n"] for r in (f.get("funnel") or [])}
    # Sessions that viewed ≥1 product (used for cart/checkout/purchase rates)
    view_sessions = funnel_map.get("vp", 0)
    adds          = funnel_map.get("ac", 0)
    checkouts     = funnel_map.get("bc", 0)
    purchases     = funnel_map.get("pu", 0)
    visitors      = (f.get("unique_visitors") or [{}])[0].get("n", 0)
    # Total individual product page opens (can exceed unique visitors)
    total_views   = (f.get("total_vp") or [{}])[0].get("n", 0)

    funnel = [
        {"label": "Vizita Unike",        "count": visitors,    "icon": "fa-users",       "color": "#4F5D4E",
         "desc": "Vizitorë unikë (home/produkte)",  "rate_label": None},
        {"label": "Faqe Produkti Hapur", "count": total_views, "icon": "fa-eye",         "color": "#6b7c6a",
         "desc": "Hapje totale faqesh produkti",
         "rate": round(total_views / visitors, 2) if visitors else 0,
         "rate_label": "faqe produkti mesatarisht për vizitor", "rate_is_avg": True},
        {"label": "Shtuar në Shportë",   "count": adds,      "icon": "fa-cart-plus",   "color": "#f59e0b",
         "desc": "nga ata që hapën produkte", "rate": pct(adds, view_sessions),
         "rate_label": "nga ata që hapën ≥1 produkt"},
        {"label": "Nisën Checkout",      "count": checkouts, "icon": "fa-credit-card", "color": "#3b82f6",
         "desc": "nga shporta",          "rate": pct(checkouts, adds),
         "rate_label": "nga ata që shtuan në shportë"},
        {"label": "Porosi e Plotësuar",  "count": purchases, "icon": "fa-check-circle","color": "#10b981",
         "desc": "nga checkout",         "rate": pct(purchases, checkouts),
         "rate_label": "nga ata që nisën checkout"},
    ]
    abandonment_rate = round(100 - pct(purchases, checkouts), 1) if checkouts else None

    def _resolve_products(items):
        ids = [r["_id"] for r in items if r.get("_id") and ObjectId.is_valid(str(r["_id"]))]
        if not ids:
            return []
        # Only include products that still exist and are not deleted
        name_map = {str(p["_id"]): p for p in mongo.db.products.find(
            {"_id": {"$in": [ObjectId(str(i)) for i in ids]}, "is_deleted": {"$ne": True}},
            {"name": 1, "image_url": 1, "brand": 1})}
        return [{"pid": str(r["_id"]),
                 "name": name_map.get(str(r["_id"]), {}).get("name", "—"),
                 "brand": name_map.get(str(r["_id"]), {}).get("brand", ""),
                 "image_url": name_map.get(str(r["_id"]), {}).get("image_url", ""),
                 "count": r["n"]}
                for r in items if str(r["_id"]) in name_map]  # skip deleted/missing

    top_viewed = _resolve_products(f.get("top_viewed") or [])
    top_carted = _resolve_products(f.get("top_carted") or [])

    carted_map = {p["pid"]: p["count"] for p in top_carted}
    low_conversion = sorted(
        [{"pid": p["pid"], "name": p["name"], "brand": p["brand"], "image_url": p["image_url"],
          "count": p["count"], "cart_count": carted_map.get(p["pid"], 0),
          "rate": pct(carted_map.get(p["pid"], 0), p["count"])}
         for p in top_viewed if p["count"] >= 5 and pct(carted_map.get(p["pid"], 0), p["count"]) < 15],
        key=lambda x: x["count"], reverse=True
    )[:8]

    day_data: dict = defaultdict(lambda: {"vp": 0, "ac": 0, "pu": 0})
    for r in (f.get("daily_trend") or []):
        day_data[r["_id"]["day"]][r["_id"]["e"]] = r["n"]
    sorted_days = sorted(day_data.keys())
    activity_trend = {
        "labels":    sorted_days,
        "views":     [day_data[d]["vp"] for d in sorted_days],
        "adds":      [day_data[d]["ac"] for d in sorted_days],
        "purchases": [day_data[d]["pu"] for d in sorted_days],
    }
    has_activity = bool(sorted_days)

    pending_orders_count = mongo.db.orders.count_documents({'status': {'$in': ['Pending', 'Në Pritje']}})

    return render_template('admin/analytics.html',
                           days=days,
                           funnel=funnel,
                           abandonment_rate=abandonment_rate,
                           top_viewed=top_viewed,
                           top_carted=top_carted,
                           low_conversion=low_conversion,
                           activity_trend=activity_trend,
                           has_activity=has_activity,
                           trend_labels=trend_labels,
                           trend_revenue=trend_revenue,
                           trend_orders=trend_orders,
                           most_ordered=most_ordered,
                           most_liked=most_liked,
                           brand_distribution=brand_distribution,
                           category_sales=category_sales,
                           pending_orders_count=pending_orders_count)


@admin.route('/recent-events')
@login_required
@admin_required
def recent_events():
    """Show the last 20 real events — use this to verify tracking is working."""
    from bson import ObjectId
    docs = list(mongo.db.events.find({}, {"_id": 0}).sort("ts", -1).limit(20))
    for d in docs:
        d["ts"] = d["ts"].strftime("%Y-%m-%d %H:%M:%S") if d.get("ts") else ""
        if "pid" in d:
            d["pid"] = str(d["pid"])
        if "uid" in d:
            d["uid"] = str(d["uid"])
    from flask import jsonify
    return jsonify(docs)


@admin.route('/seed-test-events', methods=['POST'])
@login_required
@admin_required
def seed_test_events():
    """Insert realistic fake events for the last 30 days — only in DEBUG mode."""
    import os
    if not os.getenv('FLASK_DEBUG', '1') in ('1', 'true', 'True'):
        from flask import abort
        abort(403)
    import random
    from bson import ObjectId
    from datetime import datetime, timedelta

    # Get up to 20 real product IDs to reference
    products = list(mongo.db.products.find({"is_deleted": {"$ne": True}}, {"_id": 1}).limit(20))
    if not products:
        return {"error": "Nuk ka produkte"}, 400

    pids = [p["_id"] for p in products]
    now = datetime.utcnow()
    docs = []

    for day_offset in range(30):
        ts_base = now - timedelta(days=day_offset)
        n_visits = random.randint(3, 25)
        for _ in range(n_visits):
            sid = f"seed_{random.randint(1000, 9999)}"
            ts = ts_base.replace(hour=random.randint(8, 22), minute=random.randint(0, 59))
            # View a product
            pid = random.choice(pids)
            docs.append({"e": "vp", "pid": pid, "sid": sid, "ts": ts})
            # ~40% add to cart
            if random.random() < 0.40:
                docs.append({"e": "ac", "pid": pid, "sid": sid,
                              "ts": ts + timedelta(minutes=random.randint(1, 5))})
                # ~50% of those start checkout
                if random.random() < 0.50:
                    docs.append({"e": "bc", "sid": sid,
                                 "ts": ts + timedelta(minutes=random.randint(6, 12))})
                    # ~60% of those complete order
                    if random.random() < 0.60:
                        docs.append({"e": "pu", "sid": sid,
                                     "ts": ts + timedelta(minutes=random.randint(13, 20))})

    mongo.db.events.insert_many(docs)
    return {"inserted": len(docs), "ok": True}
