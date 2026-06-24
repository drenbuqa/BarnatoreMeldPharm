from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from models.product import Product
from models.order import Order
from models.user import User
from flask_login import current_user
cart_bp = Blueprint('cart', __name__, url_prefix='/cart')


def parse_cart_key(key):
    """Return (product_id, variant_id_or_None) from a cart key."""
    if '||' in str(key):
        pid, vid = str(key).split('||', 1)
        return pid.strip(), vid.strip() or None
    return str(key), None


def make_cart_key(product_id, variant_id=None):
    if variant_id:
        return f'{product_id}||{variant_id}'
    return str(product_id)


def _effective_price(product, variant_id):
    """Return (price, discount_price) respecting variant selection."""
    if variant_id:
        return Product.get_variant_price(product, variant_id)
    return float(product.get('price') or 0), \
           (float(product['discount_price']) if product.get('discount_price') else None)


def _variant_display_name(product, variant_id):
    """Return a short human-readable variant label for cart display."""
    if not variant_id:
        return product.get('size') or ''
    v = Product.get_variant_by_id(product, variant_id)
    if not v:
        return ''
    attrs = v.get('attributes') or {}
    return ', '.join(f'{k}: {val}' for k, val in attrs.items() if val)

def calculate_shipping(total_price, country):
    if not total_price or total_price <= 0:
        return 0
    
    country = country.lower() if country else 'kosova'
    
    if country in ['kosova', 'kosovë', 'kosovo']:
        # Kosovo: delivery €2.50, free only when order is strictly over 50
        if total_price > 50:
            return 0
        return 2.5
    elif country in ['shqipëria', 'shqiperia', 'albania'] or country in ['maqedonia', 'north macedonia']:
        # Albania and North Macedonia: flat €5.00 delivery, never free based on order total
        return 5.0
    
    # Default fallback: charge small fee unless over 50
    return 2.5 if total_price <= 50 else 0

def calculate_cart_totals(cart, country='Kosova'):
    total_price = 0
    total_items = 0
    total_savings = 0
    for cart_key, quantity in cart.items():
        product_id, variant_id = parse_cart_key(cart_key)
        product = Product.get_by_id(product_id)
        if product:
            qty_int = int(quantity)
            price, discount_price = _effective_price(product, variant_id)
            tmp = dict(product)
            tmp['price'] = price
            tmp['discount_price'] = discount_price
            pricing = Product.get_offer_pricing(tmp, qty_int)
            total_price += pricing['item_total']
            total_items += qty_int
            total_savings += pricing['item_savings']

    delivery_fee = calculate_shipping(total_price, country)
    grand_total = total_price + delivery_fee

    return total_price, total_items, total_savings, delivery_fee, grand_total

def get_wishlist_count():
    from flask import session
    from models.db import mongo
    from flask_login import current_user
    count = 0
    try:
        if current_user.is_authenticated:
            count = mongo.db.products.count_documents({
                "favorites": str(current_user.id),
                "is_deleted": {"$ne": True}
            })
        else:
            count = len(session.get('liked_products', []))
    except:
        pass
    return count

@cart_bp.route('/')
def view_cart():
    # session['cart'] structure: {'product_id': quantity, ...}
    cart = session.get('cart', {})
    cart_items = []
    total_price = 0
    total_savings = 0
    
    for cart_key, quantity in cart.items():
        product_id, variant_id = parse_cart_key(cart_key)
        product = Product.get_by_id(product_id)
        if product:
            qty_int = int(quantity)
            price, discount_price = _effective_price(product, variant_id)
            tmp = dict(product)
            tmp['price'] = price
            tmp['discount_price'] = discount_price
            pricing = Product.get_offer_pricing(tmp, qty_int)
            item_total = pricing['item_total']
            item_savings = pricing['item_savings']

            total_price += item_total
            total_savings += item_savings

            product['quantity'] = qty_int
            product['item_total'] = item_total
            product['item_savings'] = item_savings
            product['display_price'] = pricing['unit_price']
            product['offer_badge_text'] = pricing['offer_badge_text']
            product['offer_detail_text'] = pricing['offer_detail_text']
            product['offer_progress_text'] = pricing['offer_progress_text']
            product['free_items'] = pricing['free_items']
            product['cart_key'] = cart_key
            product['selected_variant_label'] = _variant_display_name(product, variant_id)
            if variant_id:
                v = Product.get_variant_by_id(product, variant_id)
                if v and v.get('image_url'):
                    product['display_image'] = v['image_url']
                else:
                    product['display_image'] = product.get('image_url')
            else:
                product['display_image'] = product.get('image_url')
            cart_items.append(product)

    country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
    delivery_fee = calculate_shipping(total_price, country)
    grand_total = total_price + delivery_fee

    return render_template('cart.html',
                           cart_items=cart_items,
                           total_price=total_price,
                           total_savings=total_savings,
                           delivery_fee=delivery_fee,
                           grand_total=grand_total)

@cart_bp.route('/add/<product_id>', methods=['POST'])
def add_to_cart(product_id):
    cart = session.get('cart', {})
    quantity = int(request.form.get('quantity', 1))
    variant_id = request.form.get('variant_id', '').strip() or None

    # Check that variant exists and is in stock when provided
    if variant_id:
        product = Product.get_by_id(product_id)
        if product:
            v = Product.get_variant_by_id(product, variant_id)
            if v and v.get('in_stock') is False:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'message': 'Kjo zgjedhje është jashtë stokut.'})
                flash('Kjo zgjedhje është jashtë stokut.', 'warning')
                return redirect(request.referrer or url_for('cart.view_cart'))

    cart_key = make_cart_key(product_id, variant_id)

    if cart_key in cart:
        cart[cart_key] = int(cart[cart_key]) + quantity
    else:
        cart[cart_key] = quantity

    session['cart'] = cart
    session.modified = True
    if current_user.is_authenticated:
        User.update_cart(current_user.id, cart)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
        total_price, total_items, _, _, _ = calculate_cart_totals(cart, country=country)
        return jsonify({
            'success': True,
            'message': 'Produkti u shtua në shportë.',
            'cart_count': total_items,
            'wishlist_count': get_wishlist_count()
        })

    flash('Produkti u shtua në shportë në mënyrë të sigurt.', 'success')
    return redirect(request.referrer or url_for('cart.view_cart'))

@cart_bp.route('/mini-cart-data')
def get_mini_cart_data():
    cart = session.get('cart', {})
    cart_items = []
    total_price = 0
    
    from bson import ObjectId
    from models.db import mongo
    
    product_ids = []
    for cart_key in cart.keys():
        pid, _ = parse_cart_key(cart_key)
        if pid and ObjectId.is_valid(str(pid)):
            product_ids.append(ObjectId(str(pid)))

    if product_ids:
        products_cursor = list(mongo.db.products.find({"_id": {"$in": product_ids}}))
        products_db = {str(p['_id']): p for p in products_cursor}

        for cart_key, quantity in cart.items():
            product_id, variant_id = parse_cart_key(cart_key)
            product = products_db.get(str(product_id))
            if product:
                qty = int(quantity)
                price, discount_price = _effective_price(product, variant_id)
                tmp = dict(product)
                tmp['price'] = price
                tmp['discount_price'] = discount_price
                pricing = Product.get_offer_pricing(tmp, qty)
                item_total = float(pricing['item_total'])
                item_savings = float(pricing['item_savings'])

                total_price += item_total
                variant_label = _variant_display_name(product, variant_id)
                img = product.get('image_url')
                if variant_id:
                    v = Product.get_variant_by_id(product, variant_id)
                    if v and v.get('image_url'):
                        img = v['image_url']
                cart_items.append({
                    '_id': str(product['_id']),
                    'cart_key': cart_key,
                    'name': product['name'],
                    'image_url': img,
                    'price': pricing['unit_price'],
                    'original_price': pricing['original_price'],
                    'quantity': qty,
                    'item_total': item_total,
                    'item_savings': item_savings,
                    'offer_type': pricing['offer_type'],
                    'multi_buy_type': pricing['multi_buy_type'],
                    'offer_badge_text': pricing['offer_badge_text'],
                    'offer_detail_text': pricing['offer_detail_text'],
                    'offer_progress_text': pricing['offer_progress_text'],
                    'free_items': pricing['free_items'],
                    'size': variant_label or product.get('size'),
                    'category': product.get('category'),
                    'brand': product.get('brand')
                })
        
    # Also get wishlist count to keep badges in sync
    wish_count = 0
    try:
        if current_user.is_authenticated:
            wish_count = mongo.db.products.count_documents({"favorites": str(current_user.id)})
        else:
            wish_count = len(session.get('liked_products', []))
    except:
        pass
            
    return jsonify({
        'cart_items': cart_items,
        'total_price': total_price,
        'cart_count': sum(int(v) for v in cart.values()) if cart else 0,
        'wishlist_count': get_wishlist_count()
    })

@cart_bp.route('/clear', methods=['POST'])
def clear_cart():
    session['cart'] = {}
    session.modified = True
    if current_user.is_authenticated:
        User.update_cart(current_user.id, {})
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    
    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/update/<path:cart_key>/<action>', methods=['POST'])
def update_quantity(cart_key, action):
    cart = session.get('cart', {})
    product_id, variant_id = parse_cart_key(cart_key)

    if cart_key in cart:
        current_qty = int(cart[cart_key])

        if action == 'increase':
            cart[cart_key] = current_qty + 1
        elif action == 'decrease':
            if current_qty > 1:
                cart[cart_key] = current_qty - 1
        elif action == 'remove':
            del cart[cart_key]

        session['cart'] = cart
        session.modified = True
        if current_user.is_authenticated:
            User.update_cart(current_user.id, cart)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
        total_price, total_items, total_savings, delivery_fee, grand_total = calculate_cart_totals(cart, country=country)
        product = Product.get_by_id(product_id)
        pricing = None
        item_total = 0
        item_savings = 0
        new_item_qty = 0
        if product and cart_key in cart:
            new_item_qty = cart[cart_key]
            price, discount_price = _effective_price(product, variant_id)
            tmp = dict(product)
            tmp['price'] = price
            tmp['discount_price'] = discount_price
            pricing = Product.get_offer_pricing(tmp, new_item_qty)
            item_total = pricing['item_total']
            item_savings = pricing['item_savings']

        return jsonify({
            'success': True,
            'total_price': total_price,
            'cart_total': total_price,
            'total_savings': total_savings,
            'delivery_fee': delivery_fee,
            'grand_total': grand_total,
            'cart_count': total_items,
            'item_total': item_total,
            'item_savings': item_savings,
            'quantity': new_item_qty,
            'action': action,
            'product_id': cart_key,
            'offer_type': pricing['offer_type'] if pricing else None,
            'offer_badge_text': pricing['offer_badge_text'] if pricing else None,
            'offer_progress_text': pricing['offer_progress_text'] if pricing else None,
            'free_items': pricing['free_items'] if pricing else 0,
            'wishlist_count': get_wishlist_count()
        })

    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/set/<path:cart_key>', methods=['POST'])
def set_quantity(cart_key):
    cart = session.get('cart', {})
    product_id, variant_id = parse_cart_key(cart_key)
    try:
        new_qty = int(request.form.get('quantity', 1))
        if new_qty < 1: new_qty = 1
    except ValueError:
        new_qty = 1

    if cart_key in cart:
        cart[cart_key] = new_qty
        session['cart'] = cart
        session.modified = True
        if current_user.is_authenticated:
            User.update_cart(current_user.id, cart)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
        total_price, total_items, total_savings, delivery_fee, grand_total = calculate_cart_totals(cart, country=country)
        product = Product.get_by_id(product_id)
        pricing = None
        item_total = 0
        item_savings = 0
        if product:
            price, discount_price = _effective_price(product, variant_id)
            tmp = dict(product)
            tmp['price'] = price
            tmp['discount_price'] = discount_price
            pricing = Product.get_offer_pricing(tmp, new_qty)
            item_total = pricing['item_total']
            item_savings = pricing['item_savings']

        return jsonify({
            'success': True,
            'total_price': total_price,
            'cart_total': total_price,
            'total_savings': total_savings,
            'delivery_fee': delivery_fee,
            'grand_total': grand_total,
            'cart_count': total_items,
            'item_total': item_total,
            'item_savings': item_savings,
            'quantity': new_qty,
            'offer_type': pricing['offer_type'] if pricing else None,
            'offer_badge_text': pricing['offer_badge_text'] if pricing else None,
            'offer_progress_text': pricing['offer_progress_text'] if pricing else None,
            'free_items': pricing['free_items'] if pricing else 0,
            'wishlist_count': get_wishlist_count()
        })

    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/remove/<path:cart_key>', methods=['POST'])
def remove_from_cart(cart_key):
    product_id = cart_key  # keep for compat; actual key used below
    cart = session.get('cart', {})
    if cart_key in cart:
        del cart[cart_key]
        session['cart'] = cart
        if current_user.is_authenticated:
            User.update_cart(current_user.id, cart)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
            total_price, total_items, total_savings, delivery_fee, grand_total = calculate_cart_totals(cart, country=country)
            return jsonify({
                'success': True,
                'message': 'Produkti u largua nga shporta.',
                'total_price': total_price,
                'total_savings': total_savings,
                'delivery_fee': delivery_fee,
                'grand_total': grand_total,
                'cart_count': total_items,
                'removed': True,
                'wishlist_count': get_wishlist_count()
            })
            
        flash('Produkti u largua nga shporta.', 'info')
    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/checkout')
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Shporta juaj është e zbrazët.', 'warning')
        return redirect(url_for('main.products'))
        
    cart_items = []
    total_price = 0
    
    for cart_key, quantity in cart.items():
        pid, vid = parse_cart_key(cart_key)
        product = Product.get_by_id(pid)
        if product:
            qty_int = int(quantity)
            price, discount_price = _effective_price(product, vid)
            tmp = dict(product)
            tmp['price'] = price
            tmp['discount_price'] = discount_price
            pricing = Product.get_offer_pricing(tmp, qty_int)
            item_total = pricing['item_total']
            item_savings = pricing['item_savings']

            total_price += item_total
            product['quantity'] = qty_int
            product['item_total'] = item_total
            product['item_savings'] = item_savings
            product['display_price'] = pricing['unit_price']
            product['offer_badge_text'] = pricing['offer_badge_text']
            product['offer_detail_text'] = pricing['offer_detail_text']
            product['offer_progress_text'] = pricing['offer_progress_text']
            product['free_items'] = pricing['free_items']
            product['cart_key'] = cart_key
            product['selected_variant_label'] = _variant_display_name(product, vid)
            if vid:
                v = Product.get_variant_by_id(product, vid)
                product['display_image'] = (v.get('image_url') if v and v.get('image_url') else product.get('image_url'))
            else:
                product['display_image'] = product.get('image_url')
            cart_items.append(product)
            
    country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
    shipping_cost = calculate_shipping(total_price, country)
    grand_total = total_price + shipping_cost
    
    return render_template('checkout.html', cart_items=cart_items, total_price=total_price, shipping_cost=shipping_cost, grand_total=grand_total)

@cart_bp.route('/place_order', methods=['POST'])
def place_order():
    method = request.form.get('payment_method')
    shipping_method = request.form.get('shipping_method', 'delivery')
    fullname = request.form.get('fullname')
    email = request.form.get('email')
    address = request.form.get('address')
    city = request.form.get('city')
    country = request.form.get('country')
    phone = request.form.get('phone')
    save_details = request.form.get('save_details') == '1'

    # If pickup, we don't need address details
    if shipping_method == 'pickup':
        address = "Marrje në dyqan"
        city = "N/A"
        country = "Kosova"
    
    if method == 'card':
        flash('Pagesat me kartë nuk janë ende aktive.', 'warning')
        return redirect(url_for('cart.checkout'))

    # Re-calculate Cart items for the order record
    cart = session.get('cart', {})
    if not cart:
        flash('Shporta është e zbrazët.', 'error')
        return redirect(url_for('main.products'))

    # Save user details if requested (only if delivery)
    if current_user.is_authenticated and save_details and shipping_method == 'delivery':
        User.update_profile(current_user.id, {
            'fullname': fullname,
            'address': address,
            'city': city,
            'country': country,
            'phone': phone
        })

    order_items = []
    total_price = 0
    
    for cart_key, quantity in cart.items():
        pid, vid = parse_cart_key(cart_key)
        product = Product.get_by_id(pid)
        if product:
            price, discount_price = _effective_price(product, vid)
            tmp = dict(product)
            tmp['price'] = price
            tmp['discount_price'] = discount_price
            pricing = Product.get_offer_pricing(tmp, int(quantity))
            item_total = pricing['item_total']
            total_price += item_total
            variant_label = _variant_display_name(product, vid)
            # Resolve image: prefer variant image, fall back to product image
            item_image = product.get('image_url', '')
            if vid:
                v = Product.get_variant_by_id(product, vid)
                if v and v.get('image_url'):
                    item_image = v['image_url']
            order_items.append({
                "product_id": str(product['_id']),
                "name": product['name'],
                "variant": variant_label or product.get('size') or '',
                "price": pricing['unit_price'],
                "quantity": int(quantity),
                "item_total": item_total,
                "offer_type": pricing['offer_type'],
                "multi_buy_type": pricing['multi_buy_type'],
                "image_url": item_image,
            })
            
    if shipping_method == 'pickup':
        shipping_cost = 0
    else:
        shipping_cost = calculate_shipping(total_price, country)
        
    grand_total = total_price + shipping_cost

    # Save to MongoDB
    Order.create({
        "fullname": fullname,
        "email": email,
        "address": address,
        "city": city,
        "country": country,
        "phone": phone,
        "payment_method": method,
        "shipping_method": shipping_method,
        "items": order_items,
        "total_price": total_price,
        "shipping_cost": shipping_cost,
        "grand_total": grand_total,
        "user_id": current_user.get_id() if current_user.is_authenticated else None,
        "status": "Pending"
    })
        
    # Process Cash on Delivery
    session.pop('cart', None)
    if current_user.is_authenticated:
        User.update_cart(current_user.id, {})

    # Notify admin of new order
    try:
        from models.email_utils import send_new_order_notification
        order_snapshot = {
            "fullname": fullname, "phone": phone, "email": email,
            "address": address, "city": city, "payment_method": method,
            "shipping_method": shipping_method, "items": order_items,
            "grand_total": grand_total,
        }
        send_new_order_notification(order_snapshot)
    except Exception:
        pass

    flash(f'Faleminderit {fullname}, porosia u realizua me sukses!', 'success')
    return redirect(url_for('main.index'))
