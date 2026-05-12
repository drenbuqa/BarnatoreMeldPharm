import os
import logging
from datetime import timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from models.db import init_db, mongo
from bson import ObjectId
from models.user import User
from routes.main import main
from routes.auth import auth
from routes.cart import cart_bp
from routes.admin import admin

csrf = CSRFProtect()

load_dotenv()

app = Flask(__name__)

# Trust headers from Render's proxy (Crucial for HTTPS)
if os.getenv('RENDER'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Security Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret_key')
app.config['MONGO_URI'] = os.getenv('MONGO_URI', 'mongodb://localhost:27017/meldpharm')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31) # Keep cart for 31 days
# Secure cookies only if explicit or safely on Render (HTTPS)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('RENDER') is not None 

@app.before_request
def make_session_permanent():
    session.permanent = True 

# Initialize Extensions
csrf.init_app(app)
init_db(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(user_id)

@app.context_processor
def inject_cart_count():
    from flask import session
    from models.categories import CATEGORIES
    from flask_login import current_user
    import logging
    
    # 1. Initialize Defaults
    cart_count = 0
    cart_items = []
    cart_total = 0.0
    cart_savings = 0.0
    delivery_fee = 0.0
    grand_total = 0.0
    wish_count = 0

    try:
        # 2. Calculate Wishlist Count FIRST (Standalone block)
        try:
            from models.db import mongo
            if current_user.is_authenticated:
                wish_count = mongo.db.products.count_documents({
                    "favorites": str(current_user.id),
                    "is_deleted": {"$ne": True}
                })
            else:
                wish_count = len(session.get('liked_products', []))
        except Exception as we:
            logging.error(f"Wishlist calculation failed: {we}")

        # 3. Process Cart (Independent block)
        try:
            cart = session.get('cart', {})
            if cart and mongo and mongo.db:
                from bson import ObjectId
                product_ids = []
                for pid in cart.keys():
                    if pid and ObjectId.is_valid(str(pid)):
                        product_ids.append(ObjectId(str(pid)))
                        
                if product_ids:
                    products_cursor = list(mongo.db.products.find({"_id": {"$in": product_ids}}))
                    products_db = {str(p['_id']): p for p in products_cursor}
                    
                    for pid, qty in cart.items():
                        product = products_db.get(str(pid))
                        if product:
                            try:
                                product['_id'] = str(product['_id'])
                                p_price = float(product.get('discount_price') or product.get('price') or 0.0)
                                original_price = float(product.get('price') or 0.0)
                                qty_int = int(qty)
                                
                                item_total = p_price * qty_int
                                item_savings = (original_price - p_price) * qty_int if product.get('discount_price') else 0.0
                                
                                cart_total += item_total
                                cart_savings += item_savings
                                cart_count += qty_int
                                
                                product['quantity'] = qty_int
                                product['item_total'] = item_total
                                product['item_savings'] = item_savings
                                cart_items.append(product)
                            except: continue

                # 4. Delivery
                from routes.cart import calculate_shipping
                country = current_user.country if current_user.is_authenticated and current_user.country else 'Kosova'
                delivery_fee = calculate_shipping(cart_total, country)
                grand_total = cart_total + delivery_fee
        except Exception as ce:
            logging.error(f"Cart processing failed: {ce}")

    except Exception as e:
        logging.error(f"Critical error in context processor: {e}")

    return dict(
        cart_count=int(cart_count), 
        cart_items=cart_items,
        cart_total=float(cart_total),
        cart_savings=float(cart_savings),
        delivery_fee=float(delivery_fee),
        grand_total=float(grand_total),
        wishlist_count=int(wish_count), 
        global_categories=CATEGORIES
    )

# Register Blueprints
app.register_blueprint(main)
app.register_blueprint(auth)
app.register_blueprint(cart_bp)
app.register_blueprint(admin)

# Error Handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5001'))
    debug = os.getenv('FLASK_DEBUG', '1').lower() not in ('0', 'false', 'no')
    use_reloader = os.getenv('FLASK_USE_RELOADER', '0').lower() in ('1', 'true', 'yes')
    app.run(debug=debug, use_reloader=use_reloader, host='0.0.0.0', port=port)
