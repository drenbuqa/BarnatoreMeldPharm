import os
import logging
import time
from datetime import timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
try:
    from flask_compress import Compress
except ImportError:
    Compress = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from models.db import init_db, mongo
from bson import ObjectId
from models.user import User
from routes.main import main
from routes.auth import auth
from routes.cart import cart_bp
from routes.admin import admin

csrf = CSRFProtect()
compress = Compress() if Compress else None
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")

from authlib.integrations.flask_client import OAuth
oauth = OAuth()

load_dotenv(override=True)

app = Flask(__name__)

# Trust headers from Render's proxy (Crucial for HTTPS)
if os.getenv('RENDER'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Security Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret_key')
app.config['MONGO_URI'] = os.getenv('MONGO_URI', 'mongodb://localhost:27017/meldpharm')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('RENDER') is not None
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB upload limit

# Google OAuth
app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID', '')
app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET', '')

@app.before_request
def make_session_permanent():
    session.permanent = True

# Initialize Extensions
csrf.init_app(app)
limiter.init_app(app)
if compress:
    compress.init_app(app)
init_db(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# Initialize OAuth once — must happen after app config is set
oauth.init_app(app)
oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(user_id)

# ------------------------------------------------------------------
# Security headers on every response
# ------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Block common scraper/bot user agents
    ua = request.headers.get('User-Agent', '')
    bot_keywords = ('scrapy', 'wget', 'curl', 'python-requests', 'go-http-client',
                    'httpclient', 'libwww', 'lynx', 'zgrab', 'masscan')
    if any(k in ua.lower() for k in bot_keywords):
        from flask import abort
        abort(403)
    return response

# ------------------------------------------------------------------
# Rate limit error handler
# ------------------------------------------------------------------
@app.errorhandler(429)
def ratelimit_handler(e):
    if request.is_json or request.path.startswith('/api/'):
        return jsonify(error="Shumë kërkesa. Provoni përsëri pas pak."), 429
    return render_template('errors/429.html'), 429

@app.context_processor
def inject_cart_count():
    from flask import session
    from models.categories import CATEGORIES
    from flask_login import current_user
    import logging

    cart_count = 0
    cart_items = []
    cart_total = 0.0
    cart_savings = 0.0
    delivery_fee = 0.0
    grand_total = 0.0
    wish_count = 0

    try:
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
                            except:
                                continue

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


@app.before_request
def _track_request_start_time():
    request._start_time = time.perf_counter()


@app.after_request
def _log_slow_requests(response):
    start_time = getattr(request, '_start_time', None)
    if start_time is None:
        return response
    duration_ms = (time.perf_counter() - start_time) * 1000
    if duration_ms >= 1000:
        logging.warning(
            "Slow request: %s %s -> %s in %.1fms",
            request.method, request.path, response.status_code, duration_ms,
        )
    return response


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
