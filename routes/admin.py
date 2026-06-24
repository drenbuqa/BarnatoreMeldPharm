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
)
from models.categories import CATEGORIES
from functools import wraps
from datetime import datetime
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
    new_status = request.form.get('status')
    tracking_number = (request.form.get('tracking_number') or '').strip() or None
    if not new_status:
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

    if new_status in ('Konfirmuar', 'Confirmed', 'Pranuar') and old_status not in ('Konfirmuar', 'Confirmed', 'Pranuar'):
        sent, msg = send_order_confirmation_email(order_id)
        flash('Porosia u konfirmua dhe emaili u dërgua te klienti.' if sent else f'Konfirmuar, por emaili nuk u dërgua: {msg}', 'success' if sent else 'warning')
    elif new_status in ('Delivering', 'Në Dërgesë') and old_status not in ('Delivering', 'Në Dërgesë'):
        sent, msg = send_order_shipped_email(order_id, tracking_number=tracking_number)
        flash('Emaili i dërgesës u dërgua te klienti.' if sent else f'Statusi u ndryshua, por emaili nuk u dërgua: {msg}', 'success' if sent else 'warning')
    elif new_status in ('Delivered', 'Dorezuar') and old_status not in ('Delivered', 'Dorezuar'):
        sent, msg = send_order_delivered_email(order_id)
        flash('Emaili i dorëzimit u dërgua te klienti.' if sent else f'Statusi u ndryshua, por emaili nuk u dërgua: {msg}', 'success' if sent else 'warning')
    elif new_status in ('Cancelled', 'Anuluar', 'Refuzuar') and old_status not in ('Cancelled', 'Anuluar', 'Refuzuar'):
        sent, msg = send_order_cancelled_email(order_id)
        flash('Emaili i anulimit u dërgua te klienti.' if sent else f'Statusi u ndryshua, por emaili nuk u dërgua: {msg}', 'success' if sent else 'warning')
    else:
        flash(f'Statusi i porosisë u ndryshua në {new_status}.', 'success')

    return redirect(url_for('admin.orders', status=request.args.get('status', '')))

@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Revert expired offers (throttled — runs at most once every 15 minutes per worker)
    Product.revert_expired_offers()
    
    show_analytics = request.args.get('view') == 'analytics'
    filter_on_offer = request.args.get('on_offer') == '1'
    filter_category = request.args.get('category', '').strip()
    filter_brand    = request.args.get('brand', '').strip()
    filter_stock    = request.args.get('stock', '')  # 'out' | 'in' | ''

    # Use a lean projection — avoids loading large text fields
    all_products = Product.get_all_lean()

    # Build distinct category/brand lists for the filter dropdowns
    all_categories = sorted({str(p.get('category') or '').strip() for p in all_products if p.get('category')})
    all_brands     = sorted({str(p.get('brand') or '').strip() for p in all_products if p.get('brand')})

    products = all_products
    if filter_on_offer:
        products = [p for p in products if p.get('discount_price')]
    if filter_category:
        products = [p for p in products if (p.get('category') or '') == filter_category]
    if filter_brand:
        products = [p for p in products if (p.get('brand') or '').lower() == filter_brand.lower()]
    if filter_stock == 'out':
        products = [p for p in products if not p.get('in_stock')]
    elif filter_stock == 'in':
        products = [p for p in products if p.get('in_stock')]

    # --- Analytics: Sales at a Glance ---
    orders = Order.get_recent(limit=500)
    
    def safe_float(val):
        try:
            return float(val or 0)
        except (ValueError, TypeError):
            return 0.0

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_revenue    = sum(safe_float(o.get('grand_total')) for o in orders)
    revenue_month    = sum(safe_float(o.get('grand_total')) for o in orders
                          if o.get('created_at') and o['created_at'] >= month_start)
    orders_month     = sum(1 for o in orders if o.get('created_at') and o['created_at'] >= month_start)

    # Monthly trend — last 6 months
    from collections import defaultdict
    monthly_revenue = defaultdict(float)
    monthly_orders  = defaultdict(int)
    for o in orders:
        ts = o.get('created_at')
        if not ts: continue
        key = ts.strftime('%Y-%m')
        monthly_revenue[key] += safe_float(o.get('grand_total'))
        monthly_orders[key]  += 1
    # Build ordered labels for last 6 months
    import calendar
    trend_labels = []
    trend_revenue = []
    trend_orders  = []
    for i in range(5, -1, -1):
        m = (now.month - i - 1) % 12 + 1
        y = now.year - ((now.month - i - 1) // 12)
        key = f'{y}-{m:02d}'
        trend_labels.append(calendar.month_abbr[m])
        trend_revenue.append(round(monthly_revenue.get(key, 0), 2))
        trend_orders.append(monthly_orders.get(key, 0))

    analytics = {
        'total_products': len(all_products),
        'total_offers': len([p for p in all_products if Product._offer_is_active(p)]),
        'category_sales': {},
        'brand_distribution': {},
        'most_ordered': [],
        'out_of_stock': [p for p in all_products if not p.get('in_stock')][:5],
        'most_liked': [],
        'total_revenue': round(total_revenue, 2),
        'revenue_month': round(revenue_month, 2),
        'orders_month': orders_month,
        'total_orders': len(orders),
        'trend_labels': trend_labels,
        'trend_revenue': trend_revenue,
        'trend_orders': trend_orders,
    }

    # Helper for normalization
    brand_counts = {}
    category_counts = {}
    for p in all_products:
        # Category normalization
        raw_cat = str(p.get('category') or 'Tjera').strip()
        cat_key = raw_cat.title()
        category_counts[cat_key] = category_counts.get(cat_key, 0) + 1
        
        # Brand normalization
        raw_brand = str(p.get('brand') or 'Pa Brand').strip()
        brand_key = raw_brand.title()
        brand_counts[brand_key] = brand_counts.get(brand_key, 0) + 1

    analytics['brand_distribution'] = dict(sorted(brand_counts.items(), key=lambda x: x[1], reverse=True)[:6])
    analytics['category_sales'] = dict(sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:6])

    # Dynamic metrics
    # 1. Most liked (top 5) - based on length of favorites list
    analytics['most_liked'] = sorted(all_products, key=lambda x: len(x.get('favorites', [])), reverse=True)[:5]
    
    # 2. Most ordered (top 5 from recent orders)
    product_order_counts = {}
    for o in orders:
        items = o.get('items', [])
        if not isinstance(items, list): continue
        for item in items:
            if not isinstance(item, dict): continue
            try:
                pid = str(item.get('product_id') or item.get('_id') or 'unknown')
                product_order_counts[pid] = product_order_counts.get(pid, 0) + int(item.get('quantity', 1))
            except (ValueError, TypeError):
                continue
    
    # Map IDs back to product names
    product_map = {str(p['_id']): p for p in all_products}
    sorted_order_ids = sorted(product_order_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    for pid, count in sorted_order_ids:
        if pid in product_map:
            p_info = product_map[pid].copy()
            p_info['order_count'] = count
            analytics['most_ordered'].append(p_info)
        
    pending_orders_count = mongo.db.orders.count_documents({'status': {'$in': ['Pending', 'Në Pritje']}})
    # Recent pending orders for dashboard overview
    recent_pending = list(mongo.db.orders.find(
        {'status': {'$in': ['Pending', 'Në Pritje']}},
        {'fullname': 1, 'city': 1, 'grand_total': 1, 'created_at': 1, 'status': 1}
    ).sort('created_at', -1).limit(6))
    # Newsletter subscriber count
    newsletter_count = mongo.db.users.count_documents({'newsletter_subscribed': True}) + \
                       mongo.db.newsletter_subscribers.count_documents({})
    return render_template('admin/dashboard.html',
                           analytics=analytics,
                           show_analytics=show_analytics,
                           pending_orders_count=pending_orders_count,
                           recent_pending=recent_pending,
                           newsletter_count=newsletter_count)

@admin.route('/products')
@login_required
@admin_required
def products_page():
    filter_category = request.args.get('category', '').strip()
    filter_brand    = request.args.get('brand', '').strip()
    filter_on_offer = request.args.get('on_offer') == '1'
    filter_stock    = request.args.get('stock', '')

    all_products = Product.get_all_lean()
    all_categories = sorted({str(p.get('category') or '').strip() for p in all_products if p.get('category')})
    all_brands     = sorted({str(p.get('brand') or '').strip() for p in all_products if p.get('brand')})

    products = all_products
    if filter_category:
        products = [p for p in products if (p.get('category') or '') == filter_category]
    if filter_brand:
        products = [p for p in products if (p.get('brand') or '').lower() == filter_brand.lower()]
    if filter_on_offer:
        products = [p for p in products if p.get('discount_price')]
    if filter_stock == 'out':
        products = [p for p in products if not p.get('in_stock')]
    elif filter_stock == 'in':
        products = [p for p in products if p.get('in_stock')]

    pending_orders_count = mongo.db.orders.count_documents({'status': {'$in': ['Pending', 'Në Pritje']}})
    return render_template('admin/products.html',
                           products=products,
                           all_categories=all_categories,
                           all_brands=all_brands,
                           filter_category=filter_category,
                           filter_brand=filter_brand,
                           filter_on_offer=filter_on_offer,
                           filter_stock=filter_stock,
                           total_count=len(all_products),
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


@admin.route('/orders/export')
@login_required
@admin_required
def export_orders():
    import csv, io
    status_filter = request.args.get('status', '')
    query = {}
    if status_filter:
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

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Data', 'Emri', 'Email', 'Telefoni', 'Qyteti', 'Adresa', 'Statusi', 'Pagesa', 'Totali (€)', 'Produktet', 'Shënim Admin'])
    for o in all_orders:
        items_str = '; '.join(f"{i.get('quantity',1)}x {i.get('name','')}" for i in (o.get('items') or []))
        writer.writerow([
            str(o.get('_id', '')),
            o['created_at'].strftime('%d.%m.%Y %H:%M') if o.get('created_at') else '',
            o.get('fullname', ''),
            o.get('email', ''),
            o.get('phone', ''),
            o.get('city', ''),
            o.get('address', ''),
            o.get('status', ''),
            o.get('payment_method', ''),
            f"{float(o.get('grand_total', 0)):.2f}",
            items_str,
            o.get('admin_note', ''),
        ])

    response = Response(
        '﻿' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=porosi_{datetime.utcnow().strftime("%Y%m%d")}.csv'}
    )
    return response


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


@admin.route('/product/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_product():
    if request.method == 'POST':
        # Process images
        main_img = request.form.get('image_url')
        additional_str = request.form.get('additional_images', '')
        images = [main_img]
        if additional_str:
            extras = [x.strip() for x in additional_str.replace(',', '\n').split('\n') if x.strip()]
            for img in extras:
                if img != main_img:
                    images.append(img)

        product_data = {
            "name": request.form.get('name'),
            "brand": request.form.get('brand'),
            "category": request.form.get('category'),
            "subcategory": request.form.get('subcategory'),
            "size": request.form.get('size'),
            "price": _form_float('price'),
            "discount_price": _form_optional_float('discount_price'),
            "discount_until": _form_optional_date('discount_until'),
            "description": request.form.get('description'),
            "image_url": main_img,
            "images": images,
            "featured": request.form.get('featured') == 'on',
            "is_best_seller": request.form.get('is_best_seller') == 'on',
            "is_pharmacist_choice": request.form.get('is_pharmacist_choice') == 'on',
            "in_stock": request.form.get('in_stock') == 'on',
            "how_to_use": request.form.get('how_to_use'),
            "key_ingredients": request.form.get('key_ingredients'),
            "variant_group": request.form.get('variant_group', '').strip() or None
        }
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
        # Process images
        main_img = request.form.get('image_url')
        additional_str = request.form.get('additional_images', '')
        images = [main_img]
        if additional_str:
            extras = [x.strip() for x in additional_str.replace(',', '\n').split('\n') if x.strip()]
            for img in extras:
                if img != main_img:
                    images.append(img)

        product_data = {
            "name": request.form.get('name'),
            "brand": request.form.get('brand'),
            "category": request.form.get('category'),
            "subcategory": request.form.get('subcategory'),
            "size": request.form.get('size'),
            "price": _form_float('price'),
            "discount_price": _form_optional_float('discount_price'),
            "discount_until": _form_optional_date('discount_until'),
            "description": request.form.get('description'),
            "image_url": main_img,
            "images": images,
            "featured": request.form.get('featured') == 'on',
            "is_best_seller": request.form.get('is_best_seller') == 'on',
            "is_pharmacist_choice": request.form.get('is_pharmacist_choice') == 'on',
            "in_stock": request.form.get('in_stock') == 'on',
            "how_to_use": request.form.get('how_to_use'),
            "key_ingredients": request.form.get('key_ingredients'),
            "variant_group": request.form.get('variant_group', '').strip() or None
        }
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
            discount_until = request.form.get('discount_until')
            query = {"_id": {"$in": [ObjectId(pid) for pid in selected_ids]}}
                
            products = list(mongo.db.products.find(query))
            count = 0
            expiry_date = datetime.strptime(discount_until, '%Y-%m-%d') if discount_until else None
            
            for p in products:
                if action == 'apply':
                    price = float(p.get('price', 0))
                    if price > 0:
                        update_data = {
                            "discount_until": expiry_date,
                            "offer_name": offer_name if offer_name else None,
                            "offer_type": offer_type,
                            "offer_status": "active",
                            "offer_ended_at": None,
                            "updated_at": datetime.now()
                        }
                        
                        if offer_type == 'discount':
                            discount_percent = float(request.form.get('discount_percent', 0))
                            discount_price = price * (1 - (discount_percent / 100))
                            update_data['discount_price'] = round(discount_price, 2)
                            update_data['multi_buy_type'] = None
                        elif offer_type == 'multi_buy':
                            multi_buy_type = request.form.get('multi_buy_type', '1+1')
                            discount_price = calculate_multi_buy_price(price, multi_buy_type)
                            update_data['discount_price'] = round(discount_price, 2)
                            update_data['multi_buy_type'] = multi_buy_type
                        
                        mongo.db.products.update_one({"_id": p["_id"]}, {"$set": update_data})
                        count += 1
                else: # remove action
                    mongo.db.products.update_one(
                        {"_id": p["_id"]}, 
                        {"$set": {"discount_price": None, "discount_until": None, "offer_status": "expired", "offer_ended_at": datetime.now(), "updated_at": datetime.now()}}
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
        }
    ).sort("created_at", -1))
    
    # Enhanced Active Offers Aggregation
    # We want Name, Type, Value, Expiry, Count
    pipeline = [
        {"$match": {"offer_name": {"$ne": None}, "offer_status": {"$ne": "expired"}, "is_deleted": {"$ne": True}}},
        {"$group": {
            "_id": "$offer_name",
            "count": {"$sum": 1},
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
            "expiry": r["expiry"].strftime('%Y-%m-%d') if r["expiry"] else None,
            "type": offer_type,
            "value": value
        })

    return render_template('admin/bulk_offers.html', 
                         categories=all_categories, 
                         brands=brands, 
                         all_products=all_products,
                         active_offers_info=active_offers_info)


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
        data = {
            "image_url": request.form.get("image_url"),
            "link_type": request.form.get("link_type"), # 'brand', 'category', 'custom_products', 'all_offers'
            "link_value": request.form.get("link_value"), # 'Vichy', 'Dermokozmetikë', 'product_id_1,product_id_2'
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
    return render_template('admin/banners.html', banners=banners, categories=categories, brands=brands, all_products=all_products, available_offers=available_offers, next_banner_order=next_banner_order)

@admin.route('/banners/edit/<banner_id>', methods=['POST'])
@login_required
@admin_required
def edit_banner(banner_id):
    data = {
        "image_url": request.form.get("image_url"),
        "link_type": request.form.get("link_type"),
        "link_value": request.form.get("link_value"),
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

            html_body = _build_newsletter_html(template, headline, intro_text, selected_products, SITE_BASE_URL)
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

    default_subject = f"🌟 Ofertat e Javës {week_num} — Zbritje deri {max_pct}% | Meld Pharm" if max_pct else f"✨ Produkte të Reja — {month_alb} | Meld Pharm"
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

    site_base = _os.getenv('SITE_BASE_URL', 'https://barnatora.meldpharm.com')
    return render_template('admin/newsletter.html',
                           subscriber_count=len(subscribers),
                           sent_count=sent_count,
                           pending_orders_count=pending_orders_count,
                           all_products=all_products,
                           site_base_url=site_base,
                           default_subject=default_subject,
                           default_headline=default_headline,
                           default_intro=default_intro)


def _build_newsletter_html(template, headline, intro_text, products, base_url):
    """Generate a beautiful inline-styled HTML email."""

    # Header
    header = f"""
    <div style="background:linear-gradient(135deg,#0f766e 0%,#14b8a6 100%);padding:32px 40px;text-align:center;">
      <div style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-0.3px;">Barnatore Meld Pharm</div>
    </div>
    """

    # Headline + intro
    hero = ""
    if headline or intro_text:
        hero = f"""
        <div style="padding:32px 40px 24px;text-align:center;border-bottom:1px solid #f1f5f9;">
          {'<h1 style="margin:0 0 12px;font-size:26px;font-weight:800;color:#1e293b;line-height:1.2;">'+headline+'</h1>' if headline else ''}
          {'<p style="margin:0;font-size:15px;color:#475569;line-height:1.7;">'+intro_text+'</p>' if intro_text else ''}
        </div>
        """

    # Products section
    products_html = ""
    if products:
        if template == 'grid':
            products_html = _products_grid(products, base_url)
        elif template == 'list':
            products_html = _products_list(products, base_url)
        else:  # hero_grid
            products_html = _products_hero_grid(products, base_url)

    # CTA button
    cta = f"""
    <div style="padding:28px 40px;text-align:center;border-top:1px solid #f1f5f9;">
      <a href="{base_url}/products" style="display:inline-block;background:linear-gradient(135deg,#0f766e,#14b8a6);color:#fff;text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;border-radius:12px;letter-spacing:0.2px;">
        🛒 Shiko Të Gjitha Produktet
      </a>
    </div>
    """

    # Footer
    footer = f"""
    <div style="background:#f8fafc;padding:20px 40px;text-align:center;border-top:1px solid #e2e8f0;">
      <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;">Barnatore Meld Pharm · 72 Eqrem Çabej, Prishtinë 10000</p>
      <p style="margin:0;font-size:12px;color:#94a3b8;">+383 045 590455 · <a href="{base_url}" style="color:#0f766e;text-decoration:none;">{base_url.replace('https://','')}</a></p>
    </div>
    """

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
  <div style="max-width:620px;margin:24px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    {header}{hero}{products_html}{cta}{footer}
  </div>
</body></html>"""


def _product_price_html(p):
    price = p.get('price', 0)
    disc  = p.get('discount_price')
    if disc:
        pct = round((price - disc) / price * 100) if price else 0
        return (
            f'<span style="font-size:11px;color:#94a3b8;text-decoration:line-through;">€{price:.2f}</span> '
            f'<span style="font-size:16px;font-weight:800;color:#0f766e;">€{disc:.2f}</span> '
            f'<span style="background:#fef3c7;color:#92400e;font-size:10px;font-weight:700;padding:2px 6px;border-radius:6px;margin-left:4px;">-{pct}%</span>'
        )
    return f'<span style="font-size:16px;font-weight:800;color:#1e293b;">€{price:.2f}</span>'


def _product_card_grid(p, base_url, width='45%'):
    img = p.get('image_url', '')
    name = p.get('name', '')
    brand = p.get('brand', '')
    pid = str(p['_id'])
    return f"""
    <td style="width:{width};padding:8px;vertical-align:top;">
      <a href="{base_url}/product/{pid}" style="text-decoration:none;display:block;background:#f8fafc;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;">
        <img src="{img}" alt="{name}" width="100%" style="display:block;height:180px;object-fit:cover;background:#e2e8f0;">
        <div style="padding:12px 14px 16px;">
          {f'<div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">{brand}</div>' if brand else ''}
          <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:8px;line-height:1.4;">{name}</div>
          <div style="margin-bottom:10px;">{_product_price_html(p)}</div>
          <div style="background:#0f766e;color:#fff;text-align:center;padding:8px;border-radius:8px;font-size:12px;font-weight:700;">Shiko Produktin →</div>
        </div>
      </a>
    </td>"""


def _products_grid(products, base_url):
    rows = ""
    pairs = [products[i:i+2] for i in range(0, len(products), 2)]
    for pair in pairs:
        cells = _product_card_grid(pair[0], base_url)
        if len(pair) > 1:
            cells += _product_card_grid(pair[1], base_url)
        else:
            cells += '<td style="width:45%;padding:8px;"></td>'
        rows += f'<tr>{cells}</tr>'
    return f"""
    <div style="padding:24px 32px;">
      <h2 style="margin:0 0 20px;font-size:18px;font-weight:800;color:#1e293b;">🏷️ Ofertat e Limituara</h2>
      <table width="100%" cellpadding="0" cellspacing="0"><tbody>{rows}</tbody></table>
    </div>"""


def _products_list(products, base_url):
    items = ""
    for p in products:
        img = p.get('image_url', '')
        name = p.get('name', '')
        brand = p.get('brand', '')
        pid = str(p['_id'])
        items += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #f1f5f9;">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
              <td style="width:90px;vertical-align:top;padding-right:16px;">
                <img src="{img}" alt="{name}" width="80" height="80" style="border-radius:10px;object-fit:cover;background:#e2e8f0;display:block;">
              </td>
              <td style="vertical-align:top;">
                {f'<div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">{brand}</div>' if brand else ''}
                <div style="font-size:14px;font-weight:700;color:#1e293b;margin:2px 0 6px;">{name}</div>
                <div style="margin-bottom:10px;">{_product_price_html(p)}</div>
                <a href="{base_url}/product/{pid}" style="font-size:12px;font-weight:700;color:#0f766e;text-decoration:none;">Shiko Produktin →</a>
              </td>
            </tr></table>
          </td>
        </tr>"""
    return f"""
    <div style="padding:24px 40px;">
      <h2 style="margin:0 0 16px;font-size:18px;font-weight:800;color:#1e293b;">🏷️ Ofertat e Limituara</h2>
      <table width="100%" cellpadding="0" cellspacing="0"><tbody>{items}</tbody></table>
    </div>"""


def _products_hero_grid(products, base_url):
    if not products:
        return ""
    hero_p = products[0]
    img = hero_p.get('image_url', '')
    name = hero_p.get('name', '')
    brand = hero_p.get('brand', '')
    pid = str(hero_p['_id'])
    hero_html = f"""
    <div style="padding:24px 32px 16px;">
      <a href="{base_url}/product/{pid}" style="text-decoration:none;display:block;background:#f0fdf4;border-radius:14px;overflow:hidden;border:2px solid #a7f3d0;">
        <img src="{img}" alt="{name}" width="100%" style="display:block;height:240px;object-fit:cover;">
        <div style="padding:18px 20px 20px;">
          {f'<div style="font-size:11px;color:#0f766e;font-weight:700;text-transform:uppercase;">{brand}</div>' if brand else ''}
          <div style="font-size:18px;font-weight:800;color:#1e293b;margin:4px 0 10px;">{name}</div>
          <div style="margin-bottom:14px;">{_product_price_html(hero_p)}</div>
          <div style="background:#0f766e;color:#fff;display:inline-block;padding:10px 24px;border-radius:10px;font-size:13px;font-weight:700;">Bli Tani →</div>
        </div>
      </a>
    </div>"""
    rest_html = ""
    if len(products) > 1:
        rest_html = _products_grid(products[1:], base_url)
    return hero_html + rest_html


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

    pending_orders_count = mongo.db.orders.count_documents({'status': 'Pending'})
    return render_template('admin/users.html', users=raw_users, pending_orders_count=pending_orders_count)


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
