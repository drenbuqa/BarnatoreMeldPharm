from .db import mongo
from bson import ObjectId
from datetime import datetime
import time

class Product:
    _expired_offer_cleanup_interval_seconds = 900
    _last_expired_offer_cleanup_monotonic = 0.0

    @staticmethod
    def _offer_deadline_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
            try:
                return value
            except Exception:
                return None
        if isinstance(value, str):
            for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        return None

    @staticmethod
    def _offer_is_active(product):
        if not product:
            return False

        status = str(product.get('offer_status') or '').strip().lower()
        if status and status != 'active':
            return False

        deadline_date = Product._offer_deadline_date(product.get('discount_until'))
        if deadline_date and deadline_date < datetime.now().date():
            return False

        return bool(product.get('discount_price') not in (None, 0, 0.0) or product.get('offer_name'))

    @staticmethod
    def _multi_buy_rules(multi_buy_type):
        rules = {
            '1+1': {'buy_qty': 1, 'free_qty': 1, 'label': '1+1', 'title': 'Bli 1, Merr 1 Falas'},
            '2+1': {'buy_qty': 2, 'free_qty': 1, 'label': '2+1', 'title': 'Bli 2, Merr 1 Falas'},
            '3+1': {'buy_qty': 3, 'free_qty': 1, 'label': '3+1', 'title': 'Bli 3, Merr 1 Falas'},
            'buy2get50': {'buy_qty': 2, 'free_qty': 0, 'label': '2+1', 'title': 'Bli 2, Merr 50% Zbritje në Paketë'}
        }
        return rules.get(multi_buy_type)

    @staticmethod
    def get_offer_pricing(product, quantity=1):
        """Return pricing details for discount and multi-buy offers."""
        quantity = max(int(quantity or 1), 1)
        original_price = float(product.get('price') or 0)
        discount_price = product.get('discount_price')
        offer_type = product.get('offer_type')
        multi_buy_type = product.get('multi_buy_type')

        if not Product._offer_is_active(product):
            discount_price = None
            offer_type = None
            multi_buy_type = None

        pricing = {
            'original_price': original_price,
            'unit_price': original_price,
            'item_total': original_price * quantity,
            'item_savings': 0,
            'offer_badge_text': None,
            'offer_detail_text': None,
            'offer_progress_text': None,
            'qualifies_for_free_item': False,
            'free_items': 0,
            'offer_type': offer_type,
            'multi_buy_type': multi_buy_type
        }

        if offer_type == 'multi_buy' and multi_buy_type and original_price > 0:
            rules = Product._multi_buy_rules(multi_buy_type)
            if rules:
                buy_qty = rules['buy_qty']
                free_qty = rules['free_qty']
                bundle_size = buy_qty + free_qty if free_qty else buy_qty
                promo_text = rules['title']

                if multi_buy_type == 'buy2get50':
                    full_bundles = quantity // buy_qty
                    remainder = quantity % buy_qty
                    item_total = (full_bundles * original_price * 1.5) + (remainder * original_price)
                    free_items = 0
                    progress_text = f'U aplikua për paketën {rules["title"]}'
                    qualifies = False
                else:
                    full_bundles = quantity // bundle_size
                    remainder = quantity % bundle_size
                    item_total = (full_bundles * buy_qty * original_price) + (remainder * original_price)
                    free_items = full_bundles * free_qty
                    qualifies = remainder == 0 and quantity >= bundle_size
                    if remainder == 0:
                        progress_text = f'U fitua {free_items} produkt falas'
                    else:
                        missing = bundle_size - remainder
                        progress_text = f'Shto edhe {missing} për {free_qty} falas'

                    if free_qty == 1:
                        promo_text = f'Blini {buy_qty}, merrni {free_qty} falas'
                    else:
                        promo_text = f'Blini {buy_qty} dhe merrni {free_qty} falas'

                pricing.update({
                    'item_total': item_total,
                    'item_savings': (quantity * original_price) - item_total,
                    'offer_badge_text': rules['label'],
                    'offer_detail_text': promo_text,
                    'offer_progress_text': progress_text,
                    'qualifies_for_free_item': qualifies,
                    'free_items': free_items,
                })
                return pricing

        if discount_price is not None and float(discount_price) > 0 and original_price > 0:
            discount_price = float(discount_price)
            pricing.update({
                'unit_price': discount_price,
                'item_total': discount_price * quantity,
                'item_savings': (original_price - discount_price) * quantity,
                'offer_badge_text': f'-{round(((original_price - discount_price) / original_price) * 100)}%',
                'offer_detail_text': 'Zbritje speciale'
            })

        return pricing

    @staticmethod
    def apply_offer_context(product, quantity=1):
        pricing = Product.get_offer_pricing(product, quantity)
        product['display_price'] = pricing['unit_price']
        product['display_original_price'] = pricing['original_price']
        product['display_item_total'] = pricing['item_total']
        product['display_item_savings'] = pricing['item_savings']
        product['offer_badge_text'] = pricing['offer_badge_text']
        product['offer_detail_text'] = pricing['offer_detail_text']
        product['offer_progress_text'] = pricing['offer_progress_text']
        product['qualifies_for_free_item'] = pricing['qualifies_for_free_item']
        product['free_items'] = pricing['free_items']
        return product

    @staticmethod

    def get_all():
        Product.revert_expired_offers()

        # Clean _id for json serialization if needed, or just return cursor list

        return list(mongo.db.products.find({"is_deleted": {"$ne": True}}))

    @staticmethod
    def get_all_lean(projection=None):
        """
        Fetch all non-deleted products with an optional field projection.
        Use this instead of get_all() whenever the full document is not needed —
        it skips the revert_expired_offers() call and avoids loading large fields
        such as description, images[], key_ingredients, and how_to_use.
        """
        default_projection = {
            "name": 1, "brand": 1, "category": 1, "subcategory": 1,
            "price": 1, "discount_price": 1, "offer_status": 1,
            "offer_name": 1, "offer_type": 1, "multi_buy_type": 1,
            "discount_until": 1, "is_best_seller": 1, "is_pharmacist_choice": 1,
            "in_stock": 1, "favorites": 1, "image_url": 1, "size": 1,
            "variant_group": 1, "created_at": 1, "is_deleted": 1,
        }
        proj = projection if projection is not None else default_projection
        return list(mongo.db.products.find({"is_deleted": {"$ne": True}}, proj))



    @staticmethod
    def get_paginated(page=1, per_page=20, category=None, search_query=None, subcategory=None, sort=None, brand=None, min_price=None, max_price=None, discount_only=False, best_seller_only=False, no_discount=False, pharmacist_choice=False, offer_name=None):
        Product.revert_expired_offers()
        query = {"is_deleted": {"$ne": True}}
        if category and category != 'all':
            query["category"] = category
        
        if subcategory and subcategory != 'all':
            import re
            escaped_sub = re.escape(subcategory.strip())
            query["subcategory"] = {"$regex": f"^\\s*{escaped_sub}\\s*$", "$options": "i"}

        if brand and brand != 'all':
            import re
            # Use case-insensitive regex, allow leading/trailing spaces, and escape special characters
            escaped_brand = re.escape(brand.strip())
            query["brand"] = {"$regex": f"^\\s*{escaped_brand}\\s*$", "$options": "i"}

        if discount_only:
            query["discount_price"] = {"$ne": None, "$gt": 0}
        elif no_discount:
            query["$or"] = [
                {"discount_price": {"$exists": False}},
                {"discount_price": None},
                {"discount_price": 0}
            ]

        if best_seller_only:
            query["is_best_seller"] = True

        if pharmacist_choice:
            query["is_pharmacist_choice"] = True

        if offer_name and offer_name != 'all':
            import re
            escaped_offer = re.escape(offer_name.strip())
            query["offer_name"] = {"$regex": f"^\\s*{escaped_offer}\\s*$", "$options": "i"}

        if min_price is not None or max_price is not None:
            # Match against effective_price instead of just price
            if "effective_price" not in query:
                # We need to use $expr to access the calculated effective_price in $match
                # or simpler: match against both price and discount_price since we can't match against addFields in $match stage of aggregate directly if we want to use the same logic
                pass

        if search_query:
            import re
            
            # Fuzzy match: split by spaces and require all parts to be present somewhere
            if ',' in search_query: # Multi-query support (e.g. "Vichy 89, CeraVe cleanser")
                full_terms = [t.strip() for t in search_query.split(',') if t.strip()]
                or_conditions = []
                for full_t in full_terms:
                    parts = [p for p in full_t.split() if p]
                    and_parts = []
                    for part in parts:
                        escaped_part = re.escape(part)
                        part_cond = {
                            "$or": [
                                {"name": {"$regex": escaped_part, "$options": "i"}},
                                {"brand": {"$regex": escaped_part, "$options": "i"}},
                                {"category": {"$regex": escaped_part, "$options": "i"}},
                                {"subcategory": {"$regex": escaped_part, "$options": "i"}},
                                {"description": {"$regex": escaped_part, "$options": "i"}}
                            ]
                        }
                        and_parts.append(part_cond)
                    or_conditions.append({"$and": and_parts})
                search_filter = {"$or": or_conditions}
            else:
                parts = [p for p in search_query.split() if p]
                if parts:
                    and_parts = []
                    for part in parts:
                        escaped_part = re.escape(part)
                        part_cond = {
                            "$or": [
                                {"name": {"$regex": escaped_part, "$options": "i"}},
                                {"brand": {"$regex": escaped_part, "$options": "i"}},
                                {"category": {"$regex": escaped_part, "$options": "i"}},
                                {"subcategory": {"$regex": escaped_part, "$options": "i"}},
                                {"description": {"$regex": escaped_part, "$options": "i"}}
                            ]
                        }
                        and_parts.append(part_cond)
                    search_filter = {"$and": and_parts}
                else:
                    search_filter = {}

            if search_filter:
                if "$and" not in query:
                    query["$and"] = []
                # if there is already an active $or (like from no_discount), move it to $and
                if "$or" in query:
                    existing_or = query.pop("$or")
                    query["$and"].append({"$or": existing_or})
                query["$and"].append(search_filter)
            
        # Determine sort order
        # Default sort
        sort_dict = {"_id": -1}
        if sort == 'price-low':
            sort_dict = {"effective_price": 1}
        elif sort == 'price-high':
            sort_dict = {"effective_price": -1}
        elif sort == 'newest':
            sort_dict = {"_id": -1}
        elif sort == 'discount':
            sort_dict = {"discount_percent": -1}
        elif sort == 'relevance':
            sort_dict = {"relevance_score": -1}

        # Use aggregation to handle dynamic sorting by effective price (discount_price if exists, else price)
        pipeline = [
            {
                "$addFields": {
                    "effective_price": {
                        "$cond": [
                            {"$and": [
                                {"$gt": ["$discount_price", 0]},
                                {"$ne": ["$discount_price", None]}
                            ]},
                            "$discount_price",
                            "$price"
                        ]
                    },
                    "discount_percent": {
                        "$cond": [
                            {"$and": [
                                {"$gt": ["$discount_price", 0]},
                                {"$ne": ["$discount_price", None]}
                            ]},
                            {"$divide": [{"$subtract": ["$price", "$discount_price"]}, "$price"]},
                            0
                        ]
                    }
                }
            },
            {
                # "Best products first, but shuffled" — weighted random ranking (Efraimidis-Spirakis):
                # best-seller/pharmacist-choice/discounted products get a higher weight so they land
                # near the top more *often*, but it's not a guarantee — plain products can still surface.
                "$addFields": {
                    "_relevance_weight": {
                        "$add": [
                            1,
                            {"$cond": ["$is_best_seller", 3, 0]},
                            {"$cond": ["$is_pharmacist_choice", 2, 0]},
                            {"$cond": [{"$gt": ["$discount_percent", 0]}, 1, 0]}
                        ]
                    }
                }
            },
            {
                "$addFields": {
                    "relevance_score": {
                        "$pow": [{"$rand": {}}, {"$divide": [1, "$_relevance_weight"]}]
                    }
                }
            }
        ]

        # Apply basic filters first
        match_query = query.copy()
        # Remove price filter from match_query as we'll apply it after addFields
        match_query.pop("price", None)
        
        # Insert initial match
        pipeline.insert(0, {"$match": match_query})

        # Apply price filter on effective_price
        price_filter = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        
        if price_filter:
            pipeline.append({"$match": {"effective_price": price_filter}})

        # Get total count after price filtering
        count_pipeline = pipeline[:]
        count_pipeline.append({"$count": "total"})
        count_result = list(mongo.db.products.aggregate(count_pipeline))
        total_products = count_result[0]['total'] if count_result else 0

        # Add remaining stages
        pipeline.extend([
            {"$sort": sort_dict},
            {"$skip": (page - 1) * per_page if page > 0 else 0},
            {"$limit": per_page}
        ])
        
        products = list(mongo.db.products.aggregate(pipeline))
        for p in products:
            p["_id"] = str(p["_id"])

        products = Product._decorate_products(products)
        
        import math
        total_pages = math.ceil(total_products / per_page)
        
        return products, total_pages, total_products



    @staticmethod
    def _decorate_product(product, quantity=1):
        if not product:
            return None
        pricing = Product.get_offer_pricing(product, quantity)
        product['display_price'] = pricing['unit_price']
        product['display_original_price'] = pricing['original_price']
        product['display_item_total'] = pricing['item_total']
        product['display_item_savings'] = pricing['item_savings']
        product['offer_badge_text'] = pricing['offer_badge_text']
        product['offer_detail_text'] = pricing['offer_detail_text']
        product['offer_progress_text'] = pricing['offer_progress_text']
        product['qualifies_for_free_item'] = pricing['qualifies_for_free_item']
        product['free_items'] = pricing['free_items']
        return product

    @staticmethod
    def _decorate_products(products, quantity=1):
        return [Product._decorate_product(product, quantity) for product in products]

    @staticmethod
    def get_by_category(category):
        products = list(mongo.db.products.find({"category": category, "is_deleted": {"$ne": True}}))
        return Product._decorate_products(products)



    @staticmethod
    def get_by_id(product_id):
        try:
            Product.revert_expired_offers()
            product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
            return Product._decorate_product(product)
        except:
            return None

    @staticmethod

    def get_featured(limit=15):
        Product.revert_expired_offers()

        # Changed to return discounted products as per request

        products = list(mongo.db.products.find({

            "discount_price": {"$ne": None, "$gt": 0},
            "is_deleted": {"$ne": True}

        }).sort([('_id', -1)]).limit(limit))
        return Product._decorate_products(products)

    @staticmethod
    def get_best_sellers(limit=15):
        Product.revert_expired_offers()
        products = list(mongo.db.products.find({"is_best_seller": True, "is_deleted": {"$ne": True}}).sort([('_id', -1)]).limit(limit))
        return Product._decorate_products(products)

    @staticmethod
    def get_regular(limit=20):
        Product.revert_expired_offers()
        # Returns products WITHOUT a discount_price
        # Align with get_paginated default sort (_id: -1)
        products = list(mongo.db.products.find({
            "$or": [
                {"discount_price": {"$exists": False}},
                {"discount_price": None},
                {"discount_price": 0}
            ],
            "is_deleted": {"$ne": True}
        }).sort([('_id', -1)]).limit(limit))
        return Product._decorate_products(products)

    @staticmethod
    def get_regular_preview(limit=20):
        Product.revert_expired_offers()
        rows = list(mongo.db.products.find({
            "$or": [
                {"discount_price": {"$exists": False}},
                {"discount_price": None},
                {"discount_price": 0}
            ],
            "is_deleted": {"$ne": True}
        }).sort([('_id', -1)]).limit(limit + 1))

        has_more = len(rows) > limit
        return Product._decorate_products(rows[:limit]), has_more

    @staticmethod
    def get_regular_count():
        return mongo.db.products.count_documents({
            "$or": [
                {"discount_price": {"$exists": False}},
                {"discount_price": None},
                {"discount_price": 0}
            ],
            "is_deleted": {"$ne": True}
        })

    @staticmethod

    def get_related(category, exclude_id, limit=4):

        try:

            Product.revert_expired_offers()

            products = list(mongo.db.products.find({

                "category": category,
                "is_deleted": {"$ne": True},
                "_id": {"$ne": ObjectId(exclude_id)}

            }).limit(limit))

            return Product._decorate_products(products)

        except:

            return []



    @staticmethod

    def create(data):

        return mongo.db.products.insert_one(data)



    @staticmethod

    def update(product_id, data):

        return mongo.db.products.update_one(

            {"_id": ObjectId(product_id)},

            {"$set": data}

        )

    

    @staticmethod

    def toggle_favorite(product_id, user_id):

        try:

            pid = ObjectId(product_id)

            product = mongo.db.products.find_one({"_id": pid})

            if not product:

                return None

            

            favorites = product.get('favorites', [])

            action = 'added'

            

            if user_id in favorites:

                mongo.db.products.update_one(

                    {"_id": pid}, 

                    {"$pull": {"favorites": user_id}}

                )

                action = 'removed'

            else:

                mongo.db.products.update_one(

                    {"_id": pid}, 

                    {"$addToSet": {"favorites": user_id}}

                )

                

            return action

        except:

            return None



    @staticmethod

    @staticmethod
    def delete(product_id):
        # Perform soft delete for safety
        return mongo.db.products.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"is_deleted": True}}
        )

    @staticmethod
    def revert_expired_offers(force=False):
        now_monotonic = time.monotonic()
        if not force:
            last_cleanup = getattr(Product, '_last_expired_offer_cleanup_monotonic', 0.0)
            if now_monotonic - last_cleanup < Product._expired_offer_cleanup_interval_seconds:
                return 0

        Product._last_expired_offer_cleanup_monotonic = now_monotonic

        now = datetime.now()
        today = now.date()
        # Evaluate in Python so date-only offers stay active through the end of the selected day.
        expired = mongo.db.products.find({
            "discount_until": {"$ne": None},
            "offer_status": {"$ne": "expired"},
            "is_deleted": {"$ne": True}
        })
        
        count = 0
        for product in expired:
            deadline_date = Product._offer_deadline_date(product.get('discount_until'))
            if not deadline_date or deadline_date >= today:
                continue
            mongo.db.products.update_one(
                {"_id": product["_id"]},
                {"$set": {
                    "discount_price": None,
                    "discount_until": None
                    ,"offer_status": "expired",
                    "offer_ended_at": now
                }}
            )
            count += 1
        return count

    @staticmethod
    def get_favorites_by_user(user_id):
        Product.revert_expired_offers()
        products = list(mongo.db.products.find({"favorites": user_id}))
        for p in products:
            p["_id"] = str(p["_id"])
        return Product._decorate_products(products)

    @staticmethod
    def get_by_ids(id_list):
        Product.revert_expired_offers()
        if not id_list:
            return []
        try:
            from bson import ObjectId
            obj_ids = [ObjectId(pid) for pid in id_list]
            products = list(mongo.db.products.find({"_id": {"$in": obj_ids}}))
            for p in products:
                p["_id"] = str(p["_id"])
            return Product._decorate_products(products)
        except Exception as e:
            print(f"Error in get_by_ids: {e}")
            return []

    @staticmethod
    def get_variants(variant_group, name=None, brand=None, category=None, subcategory=None):
        try:
            def normalize_text(value):
                text = str(value or "").strip()
                if text.lower() in {"none", "null", "nil", ""}:
                    return ""
                return text

            group_key = normalize_text(variant_group)
            if not group_key:
                return []

            variants = list(mongo.db.products.find({
                "variant_group": group_key,
                "is_deleted": {"$ne": True}
            }))

            # Remove duplicates and sort by size so the pills stay compact and predictable.
            seen_sizes = set()
            deduped = []
            for variant in variants:
                size_key = normalize_text(variant.get("size")).lower()
                if size_key in seen_sizes:
                    continue
                seen_sizes.add(size_key)
                deduped.append(variant)

            def sort_key(variant):
                size_value = normalize_text(variant.get("size"))
                if not size_value:
                    return (1, "zzz", str(variant.get("_id")))
                import re
                numeric_match = re.search(r"\d+(?:[.,]\d+)?", size_value)
                if numeric_match:
                    try:
                        numeric_value = float(numeric_match.group(0).replace(",", "."))
                    except ValueError:
                        numeric_value = float("inf")
                    return (0, numeric_value, size_value.lower())
                return (0, float("inf"), size_value.lower())

            deduped.sort(key=sort_key)

            for v in deduped:
                v["_id"] = str(v["_id"])
            return deduped
        except:
            return []
