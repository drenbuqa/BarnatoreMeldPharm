from flask_pymongo import PyMongo
from typing import Any
import certifi
import ssl
import logging

# Typing as Any to avoid static analysis errors where the DB attribute
# may not be recognized by type checkers before app initialization.
mongo: Any = PyMongo()


def _ensure_indexes():
    try:
        products = mongo.db.products
        banners = mongo.db.banners

        # Product query hotspots: listing filters, offers, favorites, and admin/dashboard lookups.
        products.create_index([("is_deleted", 1), ("_id", -1)], name="idx_products_deleted_id")
        products.create_index([("is_deleted", 1), ("discount_price", 1)], name="idx_products_deleted_discount")
        products.create_index([("is_deleted", 1), ("is_best_seller", 1)], name="idx_products_deleted_bestseller")
        products.create_index([("is_deleted", 1), ("category", 1)], name="idx_products_deleted_category")
        products.create_index([("is_deleted", 1), ("subcategory", 1)], name="idx_products_deleted_subcategory")
        products.create_index([("is_deleted", 1), ("brand", 1)], name="idx_products_deleted_brand")
        products.create_index([("offer_status", 1), ("offer_name", 1), ("is_deleted", 1)], name="idx_products_offer_status_name")
        products.create_index([("variant_group", 1), ("is_deleted", 1)], name="idx_products_variant_group")
        products.create_index([("favorites", 1)], name="idx_products_favorites")

        # Banner query hotspots: homepage active banners and admin ordering.
        banners.create_index([("is_active", 1), ("sort_order", 1)], name="idx_banners_active_sort")
        banners.create_index([("expires_at", 1)], name="idx_banners_expiry")
    except Exception as exc:
        logging.warning("Mongo index setup skipped: %s", exc)

def init_db(app):
    uri = app.config.get('MONGO_URI', '')
    
    is_cloud = 'mongodb+srv' in uri
    is_explicit_tls = 'tls=true' in uri.lower() or 'ssl=true' in uri.lower()
    
    if is_cloud or is_explicit_tls:
        mongo.init_app(app, tlsCAFile=certifi.where())
    else:
        # Explicitly pass tls=False to ensure no SSL handshake is attempted on localhost
        mongo.init_app(app, tls=False)

    _ensure_indexes()
