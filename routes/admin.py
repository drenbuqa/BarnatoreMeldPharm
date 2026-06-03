from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models.product import Product
from models.db import mongo
from models.banner import Banner

from models.order import Order
from models.email_utils import send_order_confirmation_email
from models.categories import CATEGORIES
from functools import wraps
from datetime import datetime

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
    per_page = 50
    orders, total_pages, total = Order.get_paginated(page=page, per_page=per_page)
    return render_template('admin/orders.html', orders=orders, page=page, total_pages=total_pages, total=total)

@admin.route('/order/update_status/<order_id>', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    new_status = request.form.get('status')
    if new_status:
        existing_order = Order.get_by_id(order_id)
        Order.update_status(order_id, new_status)
        if new_status in ('Confirmed', 'Pranuar') and existing_order and existing_order.get('status') not in ('Confirmed', 'Pranuar'):
            sent, message = send_order_confirmation_email(order_id)
            if sent:
                flash('Porosia u konfirmua dhe emaili u dërgua te klienti.', 'success')
            else:
                flash(f'Porosia u konfirmua, por emaili nuk u dërgua: {message}', 'warning')
        else:
            flash(f'Statusi i porosisë u ndryshua në {new_status}.', 'success')
    return redirect(url_for('admin.orders'))

@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Revert expired offers (throttled — runs at most once every 15 minutes per worker)
    Product.revert_expired_offers()
    
    show_analytics = request.args.get('view') == 'analytics'
    filter_on_offer = request.args.get('on_offer') == '1'

    # Use a lean projection — avoids loading large text fields (description, how_to_use, etc.)
    all_products = Product.get_all_lean()
    
    if filter_on_offer:
        products = [p for p in all_products if p.get('discount_price')]
    else:
        products = all_products

    # --- Analytics: Sales at a Glance ---
    # get_recent(200) is enough for meaningful analytics and avoids loading
    # the entire orders collection on every dashboard request.
    orders = Order.get_recent(limit=200)
    
    def safe_float(val):
        try:
            return float(val or 0)
        except (ValueError, TypeError):
            return 0.0

    analytics = {
        'total_products': len(all_products),
        'total_offers': len([p for p in all_products if Product._offer_is_active(p)]),
        'category_sales': {},
        'brand_distribution': {},
        'most_ordered': [],
        'out_of_stock': [p for p in all_products if not p.get('in_stock')][:5],
        'most_liked': []
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
        
    return render_template('admin/dashboard.html', 
                           products=products, 
                           filter_on_offer=filter_on_offer,
                           analytics=analytics,
                           show_analytics=show_analytics)

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
    current_index = next((index for index, banner in enumerate(banners) if str(banner.get('_id')) == str(banner_id)), None)
    if current_index is None:
        flash('Baneri nuk u gjet.', 'danger')
        return redirect(url_for('admin.manage_banners'))

    target_index = current_index - 1 if direction == 'up' else current_index + 1 if direction == 'down' else current_index
    if target_index < 0 or target_index >= len(banners):
        return redirect(url_for('admin.manage_banners'))

    current_banner = banners[current_index]
    target_banner = banners[target_index]
    current_order = int(current_banner.get('sort_order') or current_index + 1)
    target_order = int(target_banner.get('sort_order') or target_index + 1)

    Banner.update(str(current_banner['_id']), {'sort_order': target_order})
    Banner.update(str(target_banner['_id']), {'sort_order': current_order})
    flash('Renditja e banerit u përditësua.', 'success')
    return redirect(url_for('admin.manage_banners'))

@admin.route('/banners/delete/<banner_id>', methods=['POST'])
@login_required
@admin_required
def delete_banner(banner_id):
    Banner.delete(banner_id)
    flash("Baneri u fshi!", "info")
    return redirect(url_for("admin.manage_banners"))

