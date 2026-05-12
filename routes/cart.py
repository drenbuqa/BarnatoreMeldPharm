from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from models.product import Product
from models.order import Order
from models.user import User
from flask_login import current_user
cart_bp = Blueprint('cart', __name__, url_prefix='/cart')

def calculate_shipping(total_price, country):
    if not total_price or total_price <= 0:
        return 0
    
    country = country.lower() if country else 'kosova'
    
    if country in ['kosova', 'kosovë', 'kosovo']:
        if total_price >= 50:
            return 0
        return 2.0
    elif country in ['shqipëria', 'shqiperia', 'albania', 'maqedonia', 'north macedonia']:
        if total_price >= 100:
            return 0
        return 5.0
    
    # Default fallback
    return 2.0 if total_price < 50 else 0

def calculate_cart_totals(cart, country='Kosova'):
    total_price = 0
    total_items = 0
    total_savings = 0
    for product_id, quantity in cart.items():
        product = Product.get_by_id(product_id)
        if product:
            price = product.get('discount_price') if product.get('discount_price') else product.get('price')
            original_price = product.get('price') or 0
            qty_int = int(quantity)
            
            total_price += price * qty_int
            total_items += qty_int
            if product.get('discount_price'):
                total_savings += (float(original_price) - float(price)) * qty_int
                
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
    
    for product_id, quantity in cart.items():
        product = Product.get_by_id(product_id)
        if product:
            price = product.get('discount_price') if product.get('discount_price') else product.get('price')
            original_price = product.get('price') or 0
            qty_int = int(quantity)
            
            item_total = price * qty_int
            item_savings = (float(original_price) - float(price)) * qty_int if product.get('discount_price') else 0
            
            total_price += item_total
            total_savings += item_savings
            
            product['quantity'] = qty_int
            product['item_total'] = item_total
            product['item_savings'] = item_savings
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
    
    if product_id in cart:
        cart[product_id] = int(cart[product_id]) + quantity
    else:
        cart[product_id] = quantity
        
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
    for pid in cart.keys():
        if pid and ObjectId.is_valid(str(pid)):
            product_ids.append(ObjectId(str(pid)))
            
    if product_ids:
        products_cursor = list(mongo.db.products.find({"_id": {"$in": product_ids}}))
        products_db = {str(p['_id']): p for p in products_cursor}
        
        for product_id, quantity in cart.items():
            product = products_db.get(str(product_id))
            if product:
                price = product.get('discount_price') or product.get('price') or 0
                original_price = product.get('price') or 0
                qty = int(quantity)
                item_total = float(price) * qty
                
                # Calculate item savings for AJAX response
                item_savings = 0
                if product.get('discount_price'):
                    item_savings = (float(original_price) - float(price)) * qty
                
                total_price += item_total
                cart_items.append({
                    '_id': str(product['_id']),
                    'name': product['name'],
                    'image_url': product['image_url'],
                    'price': price,
                    'original_price': original_price,
                    'quantity': qty,
                    'item_total': item_total,
                    'item_savings': item_savings,
                    'size': product.get('size'),
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

@cart_bp.route('/update/<product_id>/<action>', methods=['POST'])
def update_quantity(product_id, action):
    cart = session.get('cart', {})
    
    if product_id in cart:
        current_qty = int(cart[product_id])
        
        if action == 'increase':
            cart[product_id] = current_qty + 1
        elif action == 'decrease':
            if current_qty > 1:
                cart[product_id] = current_qty - 1
        elif action == 'remove':
            del cart[product_id]
        
        session['cart'] = cart
        session.modified = True
        if current_user.is_authenticated:
            User.update_cart(current_user.id, cart)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
        total_price, total_items, total_savings, delivery_fee, grand_total = calculate_cart_totals(cart, country=country)
        # Get specific item totals
        product = Product.get_by_id(product_id)
        item_total = 0
        item_savings = 0
        new_item_qty = 0
        if product and product_id in cart:
            price = product.get('discount_price') if product.get('discount_price') else product.get('price')
            original_price = product.get('price') or 0
            new_item_qty = cart[product_id]
            item_total = price * new_item_qty
            if product.get('discount_price'):
                item_savings = (float(original_price) - float(price)) * new_item_qty
            
        return jsonify({
            'success': True,
            'total_price': total_price,
            'total_savings': total_savings,
            'delivery_fee': delivery_fee,
            'grand_total': grand_total,
            'cart_count': total_items,
            'item_total': item_total,
            'item_savings': item_savings,
            'quantity': new_item_qty,
            'action': action,
            'product_id': product_id,
            'wishlist_count': get_wishlist_count()
        })

    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/set/<product_id>', methods=['POST'])
def set_quantity(product_id):
    cart = session.get('cart', {})
    try:
        new_qty = int(request.form.get('quantity', 1))
        if new_qty < 1: new_qty = 1
    except ValueError:
        new_qty = 1
        
    if product_id in cart:
        cart[product_id] = new_qty
        session['cart'] = cart
        session.modified = True
        if current_user.is_authenticated:
            User.update_cart(current_user.id, cart)
        
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
        total_price, total_items, total_savings, delivery_fee, grand_total = calculate_cart_totals(cart, country=country)
        product = Product.get_by_id(product_id)
        item_total = 0
        item_savings = 0
        if product:
            price = product.get('discount_price') if product.get('discount_price') else product.get('price')
            original_price = product.get('price') or 0
            item_total = price * new_qty
            if product.get('discount_price'):
                item_savings = (float(original_price) - float(price)) * new_qty
            
        return jsonify({
            'success': True,
            'total_price': total_price,
            'total_savings': total_savings,
            'delivery_fee': delivery_fee,
            'grand_total': grand_total,
            'cart_count': total_items,
            'item_total': item_total,
            'item_savings': item_savings,
            'quantity': new_qty,
            'wishlist_count': get_wishlist_count()
        })
        
    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/remove/<product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    if product_id in cart:
        del cart[product_id]
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
    
    for product_id, quantity in cart.items():
        product = Product.get_by_id(product_id)
        if product:
            price = product.get('discount_price') if product.get('discount_price') else product.get('price')
            original_price = product.get('price') or 0
            qty_int = int(quantity)
            item_total = price * qty_int
            
            # Calculate item savings for the template
            item_savings = 0
            if product.get('discount_price'):
                item_savings = (float(original_price) - float(price)) * qty_int
                
            total_price += item_total
            product['quantity'] = qty_int
            product['item_total'] = item_total
            product['item_savings'] = item_savings
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
    
    for product_id, quantity in cart.items():
        product = Product.get_by_id(product_id)
        if product:
            price = product.get('discount_price') if product.get('discount_price') else product.get('price')
            item_total = price * int(quantity)
            total_price += item_total
            order_items.append({
                "product_id": str(product['_id']),
                "name": product['name'],
                "price": price,
                "quantity": int(quantity),
                "item_total": item_total
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
    flash(f'Faleminderit {fullname}, porosia u realizua me sukses!', 'success')
    return redirect(url_for('main.index'))
