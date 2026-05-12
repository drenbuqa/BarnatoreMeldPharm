from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from models.db import mongo
from models.product import Product
from models.order import Order
from models.user import User
from models.categories import CATEGORIES
from models.banner import Banner
from models.conversation import Conversation
from flask_login import current_user, login_required
from bson import ObjectId
import uuid
import re
import json
import urllib.request
import urllib.error
import os
import ssl
import certifi
from dotenv import load_dotenv

# Load .env into environment for local development (keys remain on server only)
load_dotenv()

main = Blueprint('main', __name__)


def _get_guest_id():
    """Get or create a stable guest ID stored in session"""
    if 'guest_id' not in session:
        session['guest_id'] = 'guest_' + uuid.uuid4().hex
    return session['guest_id']


def _normalize_chat_query(value):
    return str(value or '').strip()


def _find_chatbot_products(query_text, limit=5):
    query_text = _normalize_chat_query(query_text)
    if not query_text:
        return []

    # Reuse the existing site search logic, then fall back to a direct regex search
    products, _, _ = Product.get_paginated(
        page=1,
        per_page=limit,
        search_query=query_text,
        sort='relevance'
    )
    if products:
        return products[:limit]

    terms = [term for term in re.split(r'\s+', query_text) if term]
    if not terms:
        return []

    and_parts = []
    for term in terms:
        escaped_term = re.escape(term)
        and_parts.append({
            '$or': [
                {'name': {'$regex': escaped_term, '$options': 'i'}},
                {'brand': {'$regex': escaped_term, '$options': 'i'}},
                {'category': {'$regex': escaped_term, '$options': 'i'}},
                {'subcategory': {'$regex': escaped_term, '$options': 'i'}},
                {'size': {'$regex': escaped_term, '$options': 'i'}},
            ]
        })

    search_query = {'$and': and_parts, 'is_deleted': {'$ne': True}}
    products = list(mongo.db.products.find(search_query).limit(limit))
    for product in products:
        product['_id'] = str(product['_id'])
    return products


def _product_summary(product):
    price = product.get('discount_price') or product.get('price') or 0
    brand = product.get('brand') or 'Pa markë'
    category = product.get('subcategory') or product.get('category') or 'Produkt'
    size = product.get('size') or ''
    stock = 'Në stok' if product.get('in_stock', True) else 'Jashtë stokut'
    details = [brand, category]
    if size:
        details.append(str(size))
    details.append(stock)
    return {
        'id': str(product.get('_id')),
        'name': product.get('name'),
        'brand': product.get('brand'),
        'category': product.get('category'),
        'subcategory': product.get('subcategory'),
        'size': product.get('size'),
        'price': product.get('price'),
        'discount_price': product.get('discount_price'),
        'image_url': product.get('image_url'),
        'summary': f"{product.get('name')} — {' • '.join([part for part in details if part])} — €{float(price):.2f}"
    }


def _build_products_url(user_query='', category=None, subcategory=None):
    params = {}
    if user_query:
        params['search'] = user_query
    if category:
        params['category'] = category
    if subcategory:
        params['subcategory'] = subcategory
    return url_for('main.products', **params) if params else url_for('main.products')


def _call_openai_chat(user_query, products_context, conversation_history=None, selected_category=None, selected_subcategory=None):
    api_key = (os.getenv('OPENAI_API_KEY') or os.getenv('GEMINI_API_KEY') or '').strip()
    if not api_key:
        return None

    api_url = os.getenv('OPENAI_API_URL') or os.getenv('GEMINI_API_URL') or 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
    model = os.getenv('OPENAI_MODEL') or os.getenv('GEMINI_MODEL') or 'gemini-2.5-flash'

    context_lines = []
    for product in products_context[:8]:
        context_lines.append(product['summary'])

    system_prompt = (
        'You are a professional pharmacy shopping assistant for Barnatore Meld Pharm. '
        'Answer in Albanian. Help users find products based on their need, category, brand, size, or price. '
        'Be concise, friendly, and practical. If you suggest products, list up to 3. '
        'If no exact match is available, still answer naturally, explain the best next step, '
        'and offer to browse more products. Never claim medical diagnosis. When relevant, '
        'advise consulting a pharmacist or doctor.'
    )

    user_prompt = f"User request: {user_query}"
    if context_lines:
        user_prompt += "\n\nAvailable catalog context:\n- " + "\n- ".join(context_lines)

    messages = []
    
    # Add system prompt
    messages.append({'role': 'system', 'content': system_prompt})
    
    # Add conversation history (last 10 messages to keep context manageable)
    if conversation_history:
        for msg in conversation_history[-10:]:  # Limit to last 10 messages
            if msg.get('role') in ['user', 'assistant']:
                messages.append({
                    'role': msg['role'],
                    'content': msg['content']
                })
    
    # Add current user message
    messages.append({'role': 'user', 'content': user_prompt})

    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0.4,
        'max_tokens': 2048,
        'top_p': 0.95,
    }

    request_obj = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(request_obj, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as response:
            response_payload = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"LLM API Error: {e}")
        return None

    text_chunks = []
    # Standard OpenAI / Gemini OpenAI compatibility structure
    for choice in response_payload.get('choices', []):
        msg = choice.get('message', {})
        content = msg.get('content')
        if isinstance(content, str) and content.strip():
            text_chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str) and part.strip():
                    text_chunks.append(part)
                elif isinstance(part, dict):
                    part_text = part.get('text') or part.get('content')
                    if isinstance(part_text, str) and part_text.strip():
                        text_chunks.append(part_text)

    if not text_chunks:
        output_text = response_payload.get('output_text')
        if isinstance(output_text, str) and output_text.strip():
            text_chunks.append(output_text)

    # Join chunks preserving paragraph structure
    full_text = ''.join(chunk for chunk in text_chunks if chunk).strip()
    return full_text if full_text else None


def _build_chatbot_reply(user_query, conversation_id=None):
    normalized = _normalize_chat_query(user_query)
    lowered = normalized.lower()
    
    # Get conversation history if conversation_id is provided
    conversation_history = None
    if conversation_id:
        user_id = str(current_user.id) if current_user.is_authenticated else None
        conversation_history = Conversation.get_conversation_messages(conversation_id, user_id)

    if not normalized:
        return {
            'reply': 'Përshëndetje! Më shkruani çfarë po kërkoni dhe unë do t’ju sugjeroj produktet më të përshtatshme.',
            'products': [],
            'quick_replies': ['Për akne', 'Për hidratim', 'Vitaminë C', 'Më të shiturat'],
            'needs_clarification': False
        }

    category_hints = [
        ('akne', 'Dermokozmetikë', 'Kundër Akneve'),
        ('anti aging', 'Dermokozmetikë', 'Anti-aging & Rrudhat'),
        ('anti-aging', 'Dermokozmetikë', 'Anti-aging & Rrudhat'),
        ('hidrat', 'Dermokozmetikë', 'Hidratues'),
        ('vitamin', 'Suplementë & Vitamina', None),
        ('suplement', 'Suplementë & Vitamina', None),
        ('baby', 'Baby & Mami', None),
        ('fëmij', 'Baby & Mami', None),
        ('flok', 'Flokët', None),
        ('diell', 'Dermokozmetikë', 'Mbrojtje nga Dielli'),
        ('spf', 'Dermokozmetikë', 'Mbrojtje nga Dielli'),
    ]

    selected_category = None
    selected_subcategory = None
    for hint, category_name, subcategory_name in category_hints:
        if hint in lowered:
            selected_category = category_name
            selected_subcategory = subcategory_name
            break

    products = []
    search_terms = normalized
    if selected_subcategory:
        products = Product.get_paginated(
            page=1,
            per_page=5,
            category=selected_category,
            subcategory=selected_subcategory,
            search_query=search_terms,
            sort='relevance'
        )[0]
    elif selected_category:
        products = Product.get_paginated(
            page=1,
            per_page=5,
            category=selected_category,
            search_query=search_terms,
            sort='relevance'
        )[0]
    else:
        products = _find_chatbot_products(search_terms, limit=5)

    if not products:
        products = _find_chatbot_products(search_terms, limit=5)

    product_cards = [_product_summary(product) for product in products[:5]]
    ai_reply = _call_openai_chat(normalized, product_cards, conversation_history, selected_category, selected_subcategory)

    if product_cards:
        reply = ai_reply or (
            'Kam gjetur disa opsione që duken të përshtatshme. '
            + '; '.join(card['summary'] for card in product_cards[:3])
            + '.'
        )
        return {
            'reply': reply,
            'products': [
                {
                    'id': card['id'],
                    'name': card['name'],
                    'brand': card['brand'],
                    'category': card['category'],
                    'subcategory': card['subcategory'],
                    'size': card['size'],
                    'price': card['price'],
                    'discount_price': card['discount_price'],
                    'image_url': card['image_url'],
                }
                for card in product_cards
            ],
            'quick_replies': ['Më trego më shumë', 'Kërko alternativa', 'Më të shiturat', 'Oferta'],
            'see_more_url': _build_products_url(normalized, selected_category, selected_subcategory),
            'needs_clarification': False
        }

    if ai_reply:
        fallback_reply = ai_reply
    else:
        # If AI is not available, show a clearer Albanian message and guidance
        api_key_present = bool((os.getenv('OPENAI_API_KEY') or os.getenv('GEMINI_API_KEY') or '').strip())
        if not api_key_present:
            fallback_reply = (
                "Më vjen keq — shërbimi i inteligjencës artificiale nuk është i konfiguruar në server. "
                "Për të marrë përgjigje më të plota, vendosni GEMINI_API_KEY ose OPENAI_API_KEY në variablat mjedisore të serverit (nuk duhet të vendoset çelësi në klient). "
                "Derisa të konfigurohet, më tregoni saktësisht markën, kategorinë ose përdorimin që kërkoni dhe unë do të kërkoj manualisht në katalog."
            )
        else:
            fallback_reply = (
                'Po e kuptoj kërkesën tuaj. Nuk gjeta përputhje të drejtpërdrejtë në katalog, por mund t’ju ndihmoj të gjeni alternativa nëse më jepni markën, kategorinë ose përdorimin që kërkoni.'
            )
    return {
        'reply': fallback_reply,
        'products': [],
        'quick_replies': ['Për akne', 'Për hidratim', 'Vitaminë C', 'Mbrojtje nga dielli'],
        'see_more_url': _build_products_url(normalized, selected_category, selected_subcategory),
        'needs_clarification': True
    }

@main.route('/')
def index():
    import math
    featured_products = Product.get_featured(limit=20)
    best_sellers = Product.get_best_sellers(limit=20)
    
    # Get regular products with count and total pages for pagination
    # Changed from get_regular to get_paginated(page=1) to include all products and match store logic
    regular_products, total_pages_regular, total_regular = Product.get_paginated(page=1, per_page=20)
    
    # Get active offer banners
    offer_banners = Banner.get_active()
    
    return render_template('index.html', 
                            featured_products=featured_products, 
                            best_sellers=best_sellers,
                            regular_products=regular_products,
                            total_pages_regular=total_pages_regular,
                            categories=CATEGORIES,
                            offer_banners=offer_banners)

@main.route('/guest_login')
def guest_login():
    session['guest_mode'] = True
    return redirect(url_for('main.index'))

@main.route('/exit_guest')
def exit_guest():
    session.pop('guest_mode', None)
    return redirect(url_for('main.index'))

@main.route('/products')
def products(): 
    # Automatically revert expired offers
    Product.revert_expired_offers()
    
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', 'all')
    subcategory = request.args.get('subcategory', 'all')
    search_query = request.args.get('search') or request.args.get('q', '')
    
    # Custom products comma separated support
    comma_searches = [s.strip() for s in search_query.split(',')] if ',' in search_query else None
    sort = request.args.get('sort', 'newest')
    brand = request.args.get('brand', 'all')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    discount_only = request.args.get('discount_only') == 'true'
    no_discount = request.args.get('no_discount') == 'true'
    best_sellers = request.args.get('best_sellers') == 'true'
    per_page = 20
    if request.args.get('all') == 'true':
        per_page = 1000 # Show all products
    
    pharmacist_choice = request.args.get('pharmacist_choice') == 'true'
    
    products, total_pages, total_count = Product.get_paginated(
        page, per_page, category, search_query, subcategory, 
        sort=sort, brand=brand, min_price=min_price, max_price=max_price,
        discount_only=discount_only, best_seller_only=best_sellers,
        no_discount=no_discount, pharmacist_choice=pharmacist_choice
    )
    
    # Get all unique brands for the filter sidebar
    filter_query = {"is_deleted": {"$ne": True}}
    if category != 'all':
        filter_query["category"] = category
    if subcategory != 'all':
        import re
        escaped_sub = re.escape(subcategory.strip())
        filter_query["subcategory"] = {"$regex": f"^\\s*{escaped_sub}\\s*$", "$options": "i"}
    raw_brands = mongo.db.products.distinct("brand", filter_query)
    brand_map = {}
    for rb in raw_brands:
        if rb:
            normalized = rb.strip().lower()
            # If we see multiple versions, prefer the one with most capital letters or just the first one
            if normalized not in brand_map:
                brand_map[normalized] = rb.strip()
    available_brands = sorted(brand_map.values(), key=lambda x: x.lower())
    
    # If it's an AJAX request (from our new filter system)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == '1':
        results = []
        for p in products:
            results.append({
                'id': str(p['_id']),
                'name': p['name'],
                'brand': p.get('brand', ''),
                'price': p['price'],
                'discount_price': p.get('discount_price'),
                'image_url': p.get('image_url'),
                'images': p.get('images', []),
                'category': p.get('category'),
                'subcategory': p.get('subcategory'),
                'in_stock': p.get('in_stock', True),
                'size': p.get('size', ''),
                'is_best_seller': p.get('is_best_seller', False),
                'is_favorite': (current_user.is_authenticated and p.get('favorites') and current_user.id in p.get('favorites')) or 
                               (not current_user.is_authenticated and str(p['_id']) in session.get('liked_products', []))
            })
        
        return jsonify({
            'products': results,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count,
            'current_category': category,
            'current_subcategory': subcategory,
            'current_brand': brand,
            'sort': sort,
            'best_sellers': best_sellers,
            'available_brands': available_brands
        })

    return render_template('products.html', 
                         products=products, 
                         page=page, 
                         total_pages=total_pages,
                         total_count=total_count,
                         current_category=category,
                         current_subcategory=subcategory,
                         current_brand=brand,
                         search_query=search_query,
                         categories=CATEGORIES,
                         brands=available_brands,
                         discount_only=discount_only,
                         best_sellers=best_sellers)

    # Debug print
    print(f"Products found: {len(products)} on page {page} in category {category} subcategory {subcategory} search: {search_query}")
    return render_template('products.html', 
                         products=products, 
                         page=page, 
                         total_pages=total_pages,
                         current_category=category,
                         current_subcategory=subcategory,
                         search_query=search_query,
                         categories=CATEGORIES)

@main.route('/product/<product_id>')
def product_detail(product_id):
    product = Product.get_by_id(product_id)
    if not product:
        return render_template('index.html') # Should be 404
    
    # Increment view count
    try:
        from bson import ObjectId
        from models.db import mongo
        mongo.db.products.update_one({"_id": ObjectId(product_id)}, {"$inc": {"views": 1}})
    except Exception as e:
        print(f"Error incrementing views: {e}")
    
    
    favorite_usernames = []
    if product.get('favorites'):
        for uid in product.get('favorites'):
            u = User.get_by_id(uid)
            if u:
                favorite_usernames.append(u.username)

    related_products = Product.get_related(product.get('category'), product.get('_id'), limit=12)
    # The limit is set to 12 directly inside get_related

    # Fetch variants only when an explicit group code exists.
    variants = []
    variant_group = product.get('variant_group')
    
    all_variants = Product.get_variants(
        variant_group,
    )
    if all_variants and len(all_variants) > 1:
        variants = all_variants

    return render_template('product_detail.html', 
                            product=product, 
                            related_products=related_products, 
                            favorite_usernames=favorite_usernames,
                            variants=variants)

@main.route('/about')
def about():
    return render_template('about.html')

@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        profile_data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'phone': request.form.get('phone')
        }
        User.update_profile(current_user.id, profile_data)
        flash('Të dhënat personale u përditësuan!', 'success')
        return redirect(url_for('main.profile'))
    return render_template('profile.html')

@main.route('/profile/address', methods=['GET', 'POST'])
@login_required
def address():
    if request.method == 'POST':
        address_data = {
            'address': request.form.get('address'),
            'city': request.form.get('city'),
            'country': request.form.get('country'),
            'specifikat': request.form.get('specifikat') # Optional field
        }
        User.update_profile(current_user.id, address_data)
        flash('Adresa u përditësua me sukses!', 'success')
        return redirect(url_for('main.address'))
    return render_template('address.html')

@main.route('/wishlist')
def wishlist():
    favorites = []
    if current_user.is_authenticated:
        favorites = Product.get_favorites_by_user(current_user.id)
    else:
        liked_ids = session.get('liked_products', [])
        if liked_ids:
            favorites = Product.get_by_ids(liked_ids)
    return render_template('wishlist.html', favorites=favorites)

@main.route('/orders')
def orders():
    if not current_user.is_authenticated:
        flash('Ju lutem kyçuni për të parë historinë e porosive.', 'info')
        return redirect(url_for('auth.login'))
        
    user_orders = Order.get_by_user(current_user.id)
    return render_template('orders.html', orders=user_orders)

@main.route('/product/favorite/<product_id>', methods=['POST'])
def toggle_favorite(product_id):
    if current_user.is_authenticated:
        action = Product.toggle_favorite(product_id, current_user.id)
    else:
        # Guest User Logic
        liked_products = session.get('liked_products', [])
        
        if product_id in liked_products:
            liked_products.remove(product_id)
            action = 'removed'
        else:
            liked_products.append(product_id)
            action = 'added'
        
        session['liked_products'] = liked_products
        session.modified = True
    
    if action:
        # Get new count
        if current_user.is_authenticated:
            # Count products where user_id is in favorites list
            new_count = mongo.db.products.count_documents({"favorites": str(current_user.id)})
        else:
            new_count = len(session.get('liked_products', []))
            
        return jsonify({'success': True, 'action': action, 'count': new_count})
    return jsonify({'success': False}), 400

@main.route('/api/search')
def search_api():
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 20, type=int)
    if not query or len(query) < 2:
        return jsonify([])
    
    # Fuzzy search: require all terms in the query to be present
    import re
    terms = [t for t in query.split() if t]
    search_query = {}
    if terms:
        and_parts = []
        for t in terms:
            escaped_term = re.escape(t)
            and_parts.append({
                "$or": [
                    {"name": {"$regex": escaped_term, "$options": "i"}},
                    {"brand": {"$regex": escaped_term, "$options": "i"}},
                    {"category": {"$regex": escaped_term, "$options": "i"}},
                    {"subcategory": {"$regex": escaped_term, "$options": "i"}}
                ]
            })
        search_query = {"$and": and_parts, "is_deleted": {"$ne": True}}
    else:
        return jsonify([])
    
    products = list(mongo.db.products.find(search_query).limit(limit))
    
    results = []
    for p in products:
        results.append({
            'id': str(p['_id']),
            'name': p['name'],
            'price': p['price'],
            'discount_price': p.get('discount_price'),
            'image_url': p.get('image_url'),
            'category': p.get('category'),
            'subcategory': p.get('subcategory'),
            'brand': p.get('brand', ''),
            'size': p.get('size', '')
        })
    
    return jsonify(results)


@main.route('/api/chatbot', methods=['POST'])
def chatbot_api():
    payload = request.get_json(silent=True) or {}
    user_query = payload.get('message', '').strip()
    conversation_id = payload.get('conversation_id')
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    
    # Create new conversation if no conversation_id provided
    if not conversation_id:
        # Auto-generate title from first message
        title = user_query[:30] + '...' if len(user_query) > 30 else user_query
        conversation = Conversation.create_conversation(user_id, title)
        conversation_id = conversation['_id']
    
    # Add user message to conversation
    Conversation.add_message(conversation_id, user_query, 'user', user_id)
    
    # Get AI response
    result = _build_chatbot_reply(user_query, conversation_id)
    
    # Add AI response to conversation
    if result and result.get('reply'):
        Conversation.add_message(conversation_id, result['reply'], 'assistant', user_id)
    
    return jsonify({
        'success': True,
        'message': result['reply'],
        'products': result['products'],
        'quick_replies': result['quick_replies'],
        'needs_clarification': result['needs_clarification'],
        'conversation_id': conversation_id
    })


@main.route('/api/chatbot/status')
def chatbot_status():
    # Return whether an AI API key is present on the server (no keys are returned)
    api_key_present = bool((os.getenv('OPENAI_API_KEY') or os.getenv('GEMINI_API_KEY') or '').strip())
    return jsonify({'ai_configured': api_key_present})


@main.route('/api/conversations', methods=['GET'])
def get_conversations():
    """Get all conversations for the current user"""
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    conversations = Conversation.get_user_conversations(user_id)
    return jsonify({'conversations': conversations})


@main.route('/api/conversations', methods=['POST'])
def create_conversation():
    """Create a new conversation"""
    payload = request.get_json(silent=True) or {}
    title = payload.get('title', 'Biseda e re')
    
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    conversation = Conversation.create_conversation(user_id, title)
    
    return jsonify({
        'success': True,
        'conversation': conversation
    })


@main.route('/api/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Get a specific conversation with its messages"""
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    conversation = Conversation.get_conversation(conversation_id, user_id)
    
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404
    
    messages = Conversation.get_conversation_messages(conversation_id, user_id)
    conversation['messages'] = messages
    
    return jsonify({'conversation': conversation})


@main.route('/api/conversations/<conversation_id>', methods=['PUT'])
def update_conversation(conversation_id):
    """Update conversation title"""
    payload = request.get_json(silent=True) or {}
    title = payload.get('title')
    
    if not title:
        return jsonify({'error': 'Title is required'}), 400
    
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    success = Conversation.update_conversation_title(conversation_id, title, user_id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Conversation not found or update failed'}), 404


@main.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """Delete a conversation"""
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    success = Conversation.delete_conversation(conversation_id, user_id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Conversation not found or deletion failed'}), 404


@main.route('/api/conversations/<conversation_id>/clear', methods=['POST'])
def clear_conversation(conversation_id):
    """Clear all messages in a conversation"""
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    success = Conversation.clear_conversation_messages(conversation_id, user_id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Conversation not found or clear failed'}), 404

@main.route('/quiz')
def quiz():
    return render_template('quiz.html')

@main.route('/quiz/results')
def quiz_results():
    skin_type = request.args.get('skin_type', '')
    concern = request.args.get('concern', '')
    
    # Advanced logic: Map concerns to specific subcategories
    mapping = {
        'Akne': 'Kundër Akneve',
        'Anti-aging': 'Anti-aging & Rrudhat',
        'Hidratim': 'Hidratues',
        'Shkëlqim': 'Serume & Trajtime'
    }
    
    subcategory = mapping.get(concern)
    
    if subcategory:
        return redirect(url_for('main.products', category='Dermokozmetikë', subcategory=subcategory))
    
    # Fallback to general search if no direct subcategory match
    query = f"{skin_type} {concern}".strip()
    return redirect(url_for('main.products', category='Dermokozmetikë', q=query))

@main.route('/banner/<banner_id>')
def click_banner(banner_id):
    from bson.objectid import ObjectId
    banner = Banner.get_by_id(banner_id)
    if not banner:
        return redirect(url_for('main.index'))
    
    link_type = banner.get('link_type')
    link_value = banner.get('link_value')
    
    if link_type == 'category':
        return redirect(url_for('main.products', category=link_value))
    elif link_type == 'brand':
        return redirect(url_for('main.products', brand=link_value))
    elif link_type == 'custom_products':
        # we can use the search query parameter for multiple products by passing link_value as a search query
        return redirect(url_for('main.products', q=link_value))
    else:
        # all_offers
        return redirect(url_for('main.products', on_offer='1'))
