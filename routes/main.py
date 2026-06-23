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
import time

# Load .env into environment for local development (keys remain on server only)
load_dotenv()

main = Blueprint('main', __name__)

_HOME_CACHE_TTL_SECONDS = int(os.getenv('HOME_CACHE_TTL_SECONDS', '60'))
_HOME_CACHE: dict[str, object] = {
    'expires_at': 0.0,
    'payload': None,
}


def _get_guest_id():
    """Get or create a stable guest ID stored in session"""
    if 'guest_id' not in session:
        session['guest_id'] = 'guest_' + uuid.uuid4().hex
    return session['guest_id']


def _normalize_chat_query(value):
    return str(value or '').strip()


# Maps symptom/need phrases → product ingredient/type keywords for database search
_SYMPTOM_TO_SEARCH = {
    'dhimbje koke': 'paracetamol ibuprofen analgjezik',
    'headache': 'paracetamol ibuprofen analgjezik',
    'migrenë': 'migraine paracetamol ibuprofen',
    'grip': 'flu ftohje vitamin c zink echinacea',
    'ftohje': 'grip flu vitamin c zink echinacea decongestant',
    'kollë': 'cough syrup shurup kollë bronkit',
    'alergjia': 'antihistamin loratadin cetirizin allergy rhinit',
    'stomak': 'antacid gastrit omeprazol pantoprazol digestiv',
    'refluks': 'antacid omeprazol refluks gastrit',
    'diare': 'probiotik loperamide elektrolitë zorrë',
    'konstipacion': 'laksativ fibra probiotik macrogol',
    'gjumë': 'melatonin sleep relaksim valerian',
    'stres': 'magnez ashwagandha stres relaksim b-complex',
    'ankth': 'magnez valerian ashwagandha relaksim',
    'lodhje': 'b12 hekur magnez energy fatigue multivitamin',
    'presion': 'magnez omega 3 hipertension',
    'kolesterol': 'omega 3 statin kolesterol berberine',
    'diabet': 'glukozë sheqer chromium berberine metformin',
    'imunitet': 'vitamin c zink echinacea propolis probiotik',
    'dhimbje muskulore': 'magnez krem muskulor ibuprofen',
    'plagë': 'antiseptik betadine kloheksidin bandazh',
    'sy': 'pika sysh lacrime artificiale konjunktivit',
    'vesh': 'pika veshësh otit cerumen',
    'dhëmbë': 'pasta dhëmbësh gingival mouthwash',
    'humbje peshe': 'diet slimming metabolism carnitine',
    'shtatzëni': 'acid folik multivitamin prenatal hekur',
}

_CHATBOT_QUERY_EXPANSIONS = {
    # Skin
    'akne': ['akne', 'acne', 'pimple', 'blemish', 'breakout', 'papule', 'comedone'],
    'hidrat': ['hidratues', 'hydrat', 'moistur', 'dry skin', 'lëkurë e thatë'],
    'diell': ['diell', 'sun', 'spf', 'uv', 'sunscreen', 'solar', 'bronzim'],
    'lëkur': ['lëkur', 'lekur', 'skin', 'derma', 'face', 'fytyrë', 'serum', 'tonik'],
    'anti aging': ['anti aging', 'anti-aging', 'rrudhat', 'wrinkle', 'aging', 'rinovim'],
    'njolla': ['njolla', 'hiperpigmentim', 'dark spot', 'pigment', 'tone', 'brightening'],
    'sensitive': ['sensitive', 'lëkurë e ndjeshme', 'ndjeshme', 'e kuqe', 'skuqje'],
    # Hair & body
    'flok': ['flok', 'hair', 'shampoo', 'shampo', 'conditioner', 'maskë flokësh', 'rënie flokësh'],
    'trup': ['trup', 'body', 'locion', 'krem trupi', 'dush', 'shower'],
    # Supplements & vitamins
    'vitamin': ['vitamin', 'multivitamin', 'supplement', 'suplemente', 'omega', 'zink', 'minerale', 'magnez'],
    'suplement': ['suplement', 'supplement', 'vitamin', 'omega', 'zink', 'minerale', 'magnez', 'probiotik'],
    'probiotik': ['probiotik', 'probiotic', 'flora', 'zorrë', 'tretje', 'mikrobiotë'],
    'imunitet': ['imunitet', 'imunitetin', 'immunity', 'echinacea', 'vitamin c', 'zink', 'propolis'],
    'energji': ['energji', 'energy', 'lodhje', 'fatigue', 'b12', 'hekur', 'iron', 'magnez'],
    'kolesterol': ['kolesterol', 'cholesterol', 'omega 3', 'trigliceride', 'zemër'],
    'diabet': ['diabet', 'diabetes', 'sheqer', 'glukozë', 'insulin', 'glicemi'],
    # Baby & family
    'baby': ['baby', 'fëmij', 'femij', 'pelen', 'formula', 'infant', 'foshnjë', 'lodër'],
    'shtatzëni': ['shtatzëni', 'shtatzen', 'shtatzani', 'graviditet', 'folat', 'acid folik', 'mami'],
    # Pain & cold
    'dhimbje': ['dhimbje', 'pain', 'ibuprofen', 'paracetamol', 'analgjezik', 'koke', 'muskulor'],
    'dhimbje koke': ['headache', 'migrenë', 'migraine', 'tension', 'paracetamol', 'ibuprofen'],
    'grip': ['grip', 'flu', 'ftohje', 'cold', 'hundë', 'kollë', 'temperature', 'ethe', 'febër'],
    'kollë': ['kollë', 'cough', 'bronkit', 'frymëmarrje', 'syrup', 'shurup'],
    'alergjia': ['alergjia', 'allergy', 'antihistamin', 'rhinit', 'sytë', 'hundë', 'sezonale'],
    # Digestive
    'stomak': ['stomak', 'stomach', 'gastrit', 'refluks', 'antacid', 'tretje', 'dispepsi'],
    'konstipacion': ['konstipacion', 'constipation', 'laksativ', 'fibra', 'zorrë'],
    'diare': ['diare', 'diarrhea', 'probiotik', 'elektrolitë', 'zorrë'],
    # Sleep & stress
    'gjumë': ['gjumë', 'sleep', 'insomni', 'melatonin', 'relaksim', 'ankth'],
    'stres': ['stres', 'stress', 'ankth', 'anxiety', 'magnez', 'ashwagandha', 'relaksim'],
    # Other
    'sy': ['sy', 'eye', 'pika sysh', 'konjunktivit', 'lodhje sysh'],
    'vesh': ['vesh', 'ear', 'pika veshësh', 'otit'],
    'dhëmbë': ['dhëmbë', 'dheмbe', 'gojë', 'oral', 'pasta dhëmbësh', 'gingival'],
    'plagë': ['plagë', 'wound', 'plaga', 'antiseptik', 'bandazh', 'dezinfektim'],
    'presion': ['presion', 'blood pressure', 'hipertension', 'magnez', 'omega'],
    'humbje peshe': ['humbje peshe', 'diete', 'diet', 'slimming', 'metabolism', 'kalorite'],
    'muskulor': ['muskulor', 'muscle', 'kreme muskulore', 'kreatin', 'protein', 'sport', 'artitriti'],
}


def _expand_chatbot_query(query_text):
    normalized = _normalize_chat_query(query_text).lower()
    if not normalized:
        return normalized, []

    expanded_terms = []
    for raw_term in re.split(r'\s+', normalized):
        term = raw_term.strip()
        if term:
            expanded_terms.append(term)

    # Symptom → product ingredient mapping (checked first for longest match)
    for symptom, product_terms in sorted(_SYMPTOM_TO_SEARCH.items(), key=lambda x: -len(x[0])):
        if symptom in normalized:
            expanded_terms.extend(product_terms.split())
            break  # one symptom match is enough to anchor the search

    # General synonym expansion
    for key, values in _CHATBOT_QUERY_EXPANSIONS.items():
        if key in normalized:
            expanded_terms.extend(values)

    seen = set()
    deduped_terms = []
    for term in expanded_terms:
        normalized_term = term.lower().strip()
        if normalized_term and normalized_term not in seen:
            seen.add(normalized_term)
            deduped_terms.append(normalized_term)

    return normalized, deduped_terms


def _chatbot_search_terms(query_text):
    return _expand_chatbot_query(query_text)


def _get_home_payload():
    now = time.time()
    cached_payload = _HOME_CACHE.get('payload')
    expires_at = float(_HOME_CACHE.get('expires_at') or 0.0)
    if cached_payload and now < expires_at:
        return cached_payload

    # Run offer expiry cleanup once before the three product queries below,
    # so each individual method doesn't repeat it (they're all throttled anyway,
    # but an explicit single call avoids three monotonic clock reads).
    Product.revert_expired_offers()

    featured_products = list(mongo.db.products.find({
        "discount_price": {"$ne": None, "$gt": 0},
        "is_deleted": {"$ne": True}
    }).sort([('_id', -1)]).limit(20))
    featured_products = Product._decorate_products(featured_products)

    best_sellers = list(mongo.db.products.find({
        "is_best_seller": True,
        "is_deleted": {"$ne": True}
    }).sort([('_id', -1)]).limit(20))
    best_sellers = Product._decorate_products(best_sellers)

    _regular_rows = list(mongo.db.products.find({
        "$or": [
            {"discount_price": {"$exists": False}},
            {"discount_price": None},
            {"discount_price": 0}
        ],
        "is_deleted": {"$ne": True}
    }).sort([('_id', -1)]).limit(21))
    has_more_regular = len(_regular_rows) > 20
    regular_products = Product._decorate_products(_regular_rows[:20])
    total_pages_regular = 2 if has_more_regular else 1

    offer_banners = Banner.get_active()

    payload = {
        'featured_products': featured_products,
        'best_sellers': best_sellers,
        'regular_products': regular_products,
        'total_pages_regular': total_pages_regular,
        'offer_banners': offer_banners,
    }
    _HOME_CACHE['payload'] = payload
    _HOME_CACHE['expires_at'] = now + max(_HOME_CACHE_TTL_SECONDS, 1)
    return payload


def _load_chatbot_catalog_candidates(limit=120):
    try:
        products = Product.get_all() or []
    except Exception:
        products = []

    if not products:
        return []

    # Keep the candidate pool bounded so ranking stays cheap even if the catalog grows.
    return products[:limit]


def _rank_chatbot_products(products, query_text, prefer_offers=False, limit=5):
    normalized, terms = _chatbot_search_terms(query_text)
    ranked = []

    for product in products or []:
        name = str(product.get('name') or '').lower()
        brand = str(product.get('brand') or '').lower()
        category = str(product.get('category') or '').lower()
        subcategory = str(product.get('subcategory') or '').lower()
        size = str(product.get('size') or '').lower()
        description = str(product.get('description') or '').lower()
        searchable_text = ' '.join([name, brand, category, subcategory, size, description]).strip()

        score = 0
        if normalized and normalized in searchable_text:
            score += 8

        for term in terms:
            if term in name:
                score += 5
            elif term in brand:
                score += 4
            elif term in subcategory:
                score += 4
            elif term in category:
                score += 3
            elif term in description:
                score += 2
            elif term in size:
                score += 1

        if product.get('is_best_seller'):
            score += 2
        if product.get('is_pharmacist_choice'):
            score += 2
        if prefer_offers and product.get('discount_price') not in (None, 0, 0.0):
            score += 3

        ranked.append((score, product))

    ranked.sort(key=lambda item: (
        item[0],
        0 if item[1].get('discount_price') in (None, 0, 0.0) else 1,
        str(item[1].get('_id') or '')
    ), reverse=True)

    return [product for _, product in ranked[:limit]]


def _find_chatbot_products(query_text, limit=5):
    normalized_query, terms = _expand_chatbot_query(query_text)
    if not normalized_query:
        return []

    # Try the built-in search first, then rank against the broader catalog if it is too narrow.
    exact_products, _, _ = Product.get_paginated(
        page=1,
        per_page=limit,
        search_query=normalized_query,
        sort='relevance'
    )
    if exact_products:
        ranked_exact = _rank_chatbot_products(exact_products, normalized_query, limit=limit)
        if ranked_exact:
            return ranked_exact

    broad_candidates = _load_chatbot_catalog_candidates(limit=120)
    if not broad_candidates:
        return []

    return _rank_chatbot_products(broad_candidates, normalized_query, limit=limit)


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


def _call_openai_chat(user_query, products_context, conversation_history=None, selected_category=None, selected_subcategory=None, include_offers=False, offers_context=None):
    api_key = (os.getenv('OPENAI_API_KEY') or os.getenv('GEMINI_API_KEY') or '').strip()
    if not api_key:
        return None

    api_url = os.getenv('OPENAI_API_URL') or os.getenv('GEMINI_API_URL') or 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
    model = os.getenv('OPENAI_MODEL') or os.getenv('GEMINI_MODEL') or 'gemini-2.5-flash'

    context_lines = []
    for product in products_context[:8]:
        context_lines.append(product['summary'])

    pharmacy_location = os.getenv('PHARMACY_LOCATION', 'Rruga Eqrem Çabej 72, Prishtinë, Kosovë')
    
    system_prompt = (
        'You are a professional and knowledgeable pharmacy shopping assistant for Barnatore Meld Pharm. '
        'Answer in Albanian. Your role is to confidently recommend products that match the customer\'s needs. '
        'Be friendly, practical, and helpful. Always respond warmly to greetings. '
        'If asked about location, tell users: "Kami ndodhet në ' + pharmacy_location + '". '
        'When users ask about offers, provide specific examples from available products with discounts. '
        'If no products are on offer, say: "Nuk kemi oferta në dispozicion tani, por oferta të reja do të shtohen shpejt." '
        'IMPORTANT: When you have product recommendations available in the context, focus on recommending those products clearly and confidently. '
        'List products with their key details (brand, size, price) in a well-structured format with line breaks. '
        'Do NOT ask customers to provide more details when products are already available - just present the recommendations. '
        'After showing products, you can ask if they want more specific options or alternatives. '
        'Avoid markdown symbols like ** or ###. Keep text simple and readable. '
        'You are an expert on these products and your recommendations are valuable - trust your expertise and present products confidently.'
    )
    
    if include_offers and offers_context:
        system_prompt += '\n\nActive offers available: ' + offers_context

    user_prompt = f"User request: {user_query}"
    if context_lines:
        user_prompt += "\n\nYou have these products available to recommend:\n- " + "\n- ".join(context_lines)

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
        'max_tokens': 4096,
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
    
    # Clean up markdown formatting (remove ** bold, ## headers, etc)
    full_text = full_text.replace('**', '').replace('##', '').replace('###', '')
    # Clean up excessive numbering and bullets to make it more readable
    import re
    full_text = re.sub(r'\*\s+', '', full_text)  # Remove bullet points
    full_text = re.sub(r'^\d+\.\s+', '', full_text, flags=re.MULTILINE)  # Remove numbered lists
    
    return full_text if full_text else None


def _is_greeting(text):
    """Check if the text is ONLY a greeting (not a greeting + a question)"""
    greetings = ['përshëndetje', 'përshëndetje!', 'hello', 'hi', 'salam', 'hey', 'përshëndetjet', 'përshëndetjeje', 'çka zbarohet', 'si qenka']
    lowered = text.lower().strip()
    
    # Only treat as pure greeting if text is very short and matches exactly
    if len(lowered) > 30:
        return False
    
    # Check for exact or near-exact match
    for greeting in greetings:
        if lowered == greeting or lowered == greeting + '!' or lowered == greeting + '?' or lowered.startswith(greeting + ' '):
            # If it starts with greeting but has more text, only treat as pure greeting if very short
            if len(lowered) <= 20:
                return True
    
    return False


def _is_location_query(text):
    """Check if the text is asking about location"""
    lowered = text.lower().strip()
    location_patterns = [
        r'\bku jeni\b',
        r'\bku ndodhet\b',
        r'\bku mund\b',
        r'\badresa\b',
        r'\blokacioni?\b',
    ]
    return any(re.search(pattern, lowered) for pattern in location_patterns)


def _is_offer_query(text):
    """Check if the text is asking about offers"""
    lowered = text.lower().strip()
    offer_keywords = [
        'ofert', 'oferta', 'ofertë', 'oferte', 'zbrit', 'promoc', 'promo',
        'special', 'me zbritje', 'a keni oferta', 'keni oferta', 'ofertat'
    ]
    return any(keyword in lowered for keyword in offer_keywords)


def _get_active_offers_context():
    """Get context about active offers for the AI"""
    try:
        active_offers = list(mongo.db.products.find({
            'is_deleted': {'$ne': True},
            'offer_status': {'$ne': 'expired'},
            '$or': [
                {'discount_price': {'$exists': True, '$ne': None, '$gt': 0}},
                {'offer_name': {'$exists': True, '$ne': None}},
                {'offer_type': {'$exists': True, '$ne': None}},
            ]
        }).limit(10))
        
        if not active_offers:
            return "No offers available."
        
        offer_list = []
        for product in active_offers:
            price = product.get('price', 0)
            discount_price = product.get('discount_price', 0)
            offer_name = product.get('offer_name') or product.get('offer_type')
            if discount_price and price:
                discount_percent = int(((price - discount_price) / price) * 100)
                label = f"{offer_name}: " if offer_name else ""
                offer_list.append(f"{label}{product.get('name', 'Produkt')} - {discount_percent}% zbritje: €{discount_price:.2f} (zakonisht €{price:.2f})")
            elif offer_name:
                offer_list.append(f"{offer_name}: {product.get('name', 'Produkt')}")
        
        return ' | '.join(offer_list[:5]) if offer_list else "No active offers currently."
    except:
        return "Unable to fetch offer information."


def _get_offer_banner_target(link_value):
    offer_name = str(link_value or '').strip()
    if not offer_name:
        return None
    return url_for('main.products', discount_only='true', offer_name=offer_name)


def _build_chatbot_reply(user_query, conversation_id=None):
    normalized = _normalize_chat_query(user_query)
    lowered = normalized.lower()
    prefer_offers = _is_offer_query(normalized)
    
    # Get conversation history if conversation_id is provided
    conversation_history = None
    if conversation_id:
        user_id = str(current_user.id) if current_user.is_authenticated else None
        conversation_history = Conversation.get_conversation_messages(conversation_id, user_id)

    if not normalized:
        return {
            "reply": "Përshëndetje! Më shkruani çfarë po kërkoni dhe unë do t'ju sugjeroj produktet më të përshtatshme.",
            "products": [],
            "quick_replies": ["Për akne", "Për hidratim", "Vitaminë C", "Më të shiturat"],
            "needs_clarification": False
        }

    # Handle special cases
    if _is_greeting(normalized):
        greeting_replies = [
            "Përshëndetje! Mirëpresim në Barnatore Meld Pharm. Si mund t'ju ndihmoj të gjeni produktin e duhur?",
            "Përshëndetje! Jam këtu për t'ju ndihmuar me rekomandimet e produkteve. Çfarë po kërkoni?",
            "Përshëndetje! Mirë se erdhët. Më tregoni se çfarë produktesh ju interesojnë."
        ]
        import random
        return {
            "reply": random.choice(greeting_replies),
            "products": [],
            "quick_replies": ["Për akne", "Për hidratim", "Vitaminë C", "Më të shiturat", "Oferta"],
            "needs_clarification": False
        }
    
    if _is_location_query(normalized):
        pharmacy_location = os.getenv('PHARMACY_LOCATION', 'Rruga Eqrem Çabej 72, Prishtinë, Kosovë')
        return {
            'reply': f'Kami ndodhet në {pharmacy_location}. A dëshironi më shumë informacion apo kërkoni ndonjë produkt të caktuar?',
            'products': [],
            'quick_replies': ['Për akne', 'Për hidratim', 'Vitaminë C', 'Oferta'],
            'needs_clarification': False
        }
    
    if prefer_offers:
        active_offers = _get_active_offers_context()
        if active_offers.startswith("No offers") or active_offers.startswith("Unable to fetch"):
            return {
                'reply': 'Nuk kemi oferta në dispozicion tani, por oferta të reja do të shtohen shpejt. Ndërkohë, shikoni produktet tona më të shitur dhe të rekomanduara!',
                'products': [],
                'quick_replies': ['Më të shiturat', 'Për akne', 'Për hidratim', 'Suplement'],
                'needs_clarification': False
            }
        else:
            # Get products on offer
            try:
                products = Product.get_paginated(
                    page=1,
                    per_page=5,
                    discount_only=True,
                    sort='relevance'
                )[0]
                product_cards = [_product_summary(product) for product in _rank_chatbot_products(products, normalized, prefer_offers=True, limit=5)]
            except:
                product_cards = []
            
            return {
                'reply': f'Këtu janë disa nga ofertat tona të disponueshme: {active_offers}',
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
                ] if product_cards else [],
                'quick_replies': ['Më shumë oferta', 'Për akne', 'Për hidratim', 'Suplement'],
                'see_more_url': _build_products_url('', category=None, subcategory=None) + '?discount_only=true',
                'needs_clarification': False
            }

    category_hints = [
        # Skin / Dermokozmetikë
        ('akne', 'Dermokozmetikë', 'Kundër Akneve'),
        ('pimple', 'Dermokozmetikë', 'Kundër Akneve'),
        ('anti aging', 'Dermokozmetikë', 'Anti-aging & Rrudhat'),
        ('anti-aging', 'Dermokozmetikë', 'Anti-aging & Rrudhat'),
        ('rrudhat', 'Dermokozmetikë', 'Anti-aging & Rrudhat'),
        ('hidrat', 'Dermokozmetikë', 'Hidratues'),
        ('moistur', 'Dermokozmetikë', 'Hidratues'),
        ('diell', 'Dermokozmetikë', 'Mbrojtje nga Dielli'),
        ('spf', 'Dermokozmetikë', 'Mbrojtje nga Dielli'),
        ('sunscreen', 'Dermokozmetikë', 'Mbrojtje nga Dielli'),
        ('serum', 'Dermokozmetikë', None),
        ('njolla', 'Dermokozmetikë', None),
        ('pigment', 'Dermokozmetikë', None),
        ('sensitive', 'Dermokozmetikë', None),
        ('lëkur', 'Dermokozmetikë', None),
        ('fytyrë', 'Dermokozmetikë', None),
        # Hair
        ('flok', 'Flokët', None),
        ('shampoo', 'Flokët', None),
        ('shampo', 'Flokët', None),
        ('hair', 'Flokët', None),
        # Supplements & vitamins
        ('vitamin', 'Suplementë & Vitamina', None),
        ('suplement', 'Suplementë & Vitamina', None),
        ('omega', 'Suplementë & Vitamina', None),
        ('magnez', 'Suplementë & Vitamina', None),
        ('probiotik', 'Suplementë & Vitamina', None),
        ('imunitet', 'Suplementë & Vitamina', None),
        ('kolesterol', 'Suplementë & Vitamina', None),
        ('hekur', 'Suplementë & Vitamina', None),
        ('energji', 'Suplementë & Vitamina', None),
        # Baby & family
        ('baby', 'Baby & Mami', None),
        ('fëmij', 'Baby & Mami', None),
        ('femij', 'Baby & Mami', None),
        ('foshnjë', 'Baby & Mami', None),
        ('shtatzëni', 'Baby & Mami', None),
        ('shtatzani', 'Baby & Mami', None),
        ('mami', 'Baby & Mami', None),
        # Oral
        ('dhëmbë', 'Higjiena Gojore', None),
        ('dheмbe', 'Higjiena Gojore', None),
        ('pasta dhëmbësh', 'Higjiena Gojore', None),
        ('gojë', 'Higjiena Gojore', None),
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

    if not products and any(keyword in lowered for keyword in ['rekomand', 'sugjero', 'suggest', 'recommend', 'çfarë keni', 'cfare keni', 'show me', 'me trego', 'produkt']):
        return {
            'reply': 'Po ju ndihmoj me zgjedhjen më të saktë. Më tregoni përdorimin, markën ose kategorinë që kërkoni dhe unë do t'"'"'ju sjell produkte të përshtatshme nga katalogu ynë.',
            'products': [],
            'quick_replies': ['Për akne', 'Për hidratim', 'Vitaminë C', 'Mbrojtje nga dielli', 'Për fëmijë'],
            'needs_clarification': True,
            'see_more_url': _build_products_url(normalized, selected_category, selected_subcategory),
        }

    products = _rank_chatbot_products(products, normalized, prefer_offers=prefer_offers, limit=5)

    product_cards = [_product_summary(product) for product in products[:5]]
    offers_context = _get_active_offers_context() if prefer_offers else None
    ai_reply = _call_openai_chat(normalized, product_cards, conversation_history, selected_category, selected_subcategory, include_offers=prefer_offers, offers_context=offers_context)

    if product_cards:
        if ai_reply:
            reply = ai_reply
        else:
            reply = 'Këtu janë disa rekomandime nga koleksioni ynë:'
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
    payload = _get_home_payload()
    
    return render_template('index.html', 
                            featured_products=payload['featured_products'], 
                            best_sellers=payload['best_sellers'],
                            regular_products=payload['regular_products'],
                            total_pages_regular=payload['total_pages_regular'],
                            categories=CATEGORIES,
                            offer_banners=payload['offer_banners'])

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
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', 'all')
    subcategory = request.args.get('subcategory', 'all')
    search_query = request.args.get('search') or request.args.get('q', '')
    offer_name = request.args.get('offer_name', '').strip()
    
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
        no_discount=no_discount, pharmacist_choice=pharmacist_choice,
        offer_name=offer_name or None
    )
    
    # Get all unique brands for the filter sidebar
    filter_query: dict[str, object] = {"is_deleted": {"$ne": True}}
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
                'offer_type': p.get('offer_type'),
                'multi_buy_type': p.get('multi_buy_type'),
                'offer_badge_text': p.get('offer_badge_text'),
                'offer_detail_text': p.get('offer_detail_text'),
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
                         best_sellers=best_sellers,
                         offer_name=offer_name)

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

    return render_template('product_detail.html',
                            product=product,
                            related_products=related_products,
                            favorite_usernames=favorite_usernames)

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
        
    from datetime import datetime as _dt
    user_orders = Order.get_by_user(current_user.id)
    return render_template('orders.html', orders=user_orders, now=_dt.utcnow())


@main.route('/order/<order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    from bson import ObjectId
    from datetime import datetime as _dt, timedelta
    try:
        order = mongo.db.orders.find_one({'_id': ObjectId(order_id)})
    except Exception:
        flash('Porosia nuk u gjet.', 'danger')
        return redirect(url_for('main.orders'))

    if not order:
        flash('Porosia nuk u gjet.', 'danger')
        return redirect(url_for('main.orders'))

    # Only the owner can cancel
    if str(order.get('user_id', '')) != str(current_user.id):
        flash('Nuk keni leje për të anuluar këtë porosi.', 'danger')
        return redirect(url_for('main.orders'))

    # Only cancellable if within 24h and still Pending or Konfirmuar
    cancellable_statuses = ['Pending', 'Në Pritje', 'Konfirmuar']
    if order.get('status') not in cancellable_statuses:
        flash('Kjo porosi nuk mund të anulohet (statusi nuk lejon anulim).', 'warning')
        return redirect(url_for('main.orders'))

    created = order.get('created_at')
    if created and (_dt.utcnow() - created) > timedelta(hours=24):
        flash('Koha e anulimit (24 orë) ka kaluar. Kontaktoni barnatoren direkt.', 'warning')
        return redirect(url_for('main.orders'))

    mongo.db.orders.update_one(
        {'_id': ObjectId(order_id)},
        {'$set': {'status': 'Anuluar', 'cancel_reason': 'Anuluar nga klienti', 'updated_at': _dt.utcnow()}}
    )
    flash('Porosia u anulua me sukses.', 'success')
    return redirect(url_for('main.orders'))


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


def _generate_chat_title(user_query):
    """Generate a meaningful title from the user's first message"""
    query = user_query.strip()
    if not query:
        return 'Biseda e re'
    
    # Remove common filler words and focus on the main topic
    filler_words = ['të lutem', 'më thuaj', 'a mund', 'cila', 'cilat', 'ku', 'kërkoj', 'kërkojë']
    words = query.lower().split()
    
    # Find the first substantive word (not a filler)
    for word in words:
        if not any(filler in word for filler in filler_words):
            # Capitalize and use as title
            title_word = query.split(word)[0] + word + (' ' + ' '.join(query.split(word)[1].split()[:2]) if len(query.split(word)) > 1 else '')
            title = title_word.strip().capitalize()
            if len(title) > 50:
                title = title[:47] + '...'
            return title if title else 'Biseda e re'
    
    # Fallback: use first 40 characters
    title = query[:40] + '...' if len(query) > 40 else query
    return title.capitalize()


@main.route('/api/chatbot', methods=['POST'])
def chatbot_api():
    payload = request.get_json(silent=True) or {}
    user_query = payload.get('message', '').strip()
    conversation_id = payload.get('conversation_id')
    user_id = str(current_user.id) if current_user.is_authenticated else _get_guest_id()
    
    # Create new conversation if no conversation_id provided
    if not conversation_id:
        # Auto-generate title from first message with better logic
        title = _generate_chat_title(user_query)
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
    skin_type = request.args.get('skin_type', '').strip()
    concern   = request.args.get('concern', '').strip()

    # Each concern maps to the exact subcategory name used in the database
    subcategory_map = {
        'Akne':         'Kundër Akneve',
        'Anti-aging':   'Anti-aging & Rrudhat',
        'Hidratim':     'Hidratues',
        'Shkëlqim':     'Pigmentim & Njolla',
        'Diell':        'Kremra Dielli (SPF)',
        'Sensitivitet': 'Lëkurë Sensitive',
    }

    subcategory = subcategory_map.get(concern)
    kwargs = {'category': 'Dermokozmetikë'}
    if subcategory:
        kwargs['subcategory'] = subcategory

    return redirect(url_for('main.products', **kwargs))

@main.route('/banner/<banner_id>')
def click_banner(banner_id):
    from bson.objectid import ObjectId
    banner = Banner.get_by_id(banner_id)
    if not banner:
        return redirect(url_for('main.index'))

    # Record click analytics
    try:
        mongo.db.banners.update_one(
            {'_id': ObjectId(banner_id)},
            {'$inc': {'click_count': 1}}
        )
    except Exception:
        pass

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


@main.route('/newsletter/subscribe', methods=['POST'])
def newsletter_subscribe():
    from flask import jsonify
    email = (request.form.get('email') or request.json and request.json.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'ok': False, 'message': 'Email i pavlefshëm.'}), 400

    if current_user.is_authenticated:
        User.set_newsletter(current_user.id, True)
    else:
        # Store guest subscriber (upsert to avoid duplicates)
        mongo.db.newsletter_subscribers.update_one(
            {'email': email},
            {'$set': {'email': email, 'subscribed_at': __import__('datetime').datetime.utcnow()}},
            upsert=True
        )
    return jsonify({'ok': True, 'message': 'U abonuat me sukses!'}), 200


@main.route('/profile/newsletter', methods=['POST'])
@login_required
def profile_newsletter():
    subscribed = request.form.get('subscribed') == '1'
    User.set_newsletter(current_user.id, subscribed)
    flash('Preferencat e abonimit u ruajtën.', 'success')
    return redirect(url_for('main.profile'))


@main.route('/privacy')
def privacy():
    return render_template('privacy.html')


@main.route('/terms')
def terms():
    return render_template('terms.html')
