"""Meta product catalog feed — /meta-product-feed.xml"""
import os, re
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString
from flask import Blueprint, Response
from models.db import mongo
from routes.promo import effective_price_with_promo

feed_bp = Blueprint('feed', __name__)

def _site_base_url():
    return os.getenv('SITE_BASE_URL', 'https://barnatoremeldpharm.com').rstrip('/')
CURRENCY = 'EUR'

# ── Google Product Taxonomy mapping ──────────────────────────────────────────
# Maps your Albanian store category → official Google taxonomy path.
# Meta Commerce Manager uses these for automatic categorisation and eligibility.
# Full taxonomy: https://www.google.com/basepages/producttype/taxonomy-with-ids.en-US.txt
_GOOGLE_CATEGORY = {
    'Dermokozmetikë':              'Health & Beauty > Personal Care > Skin Care',
    'Suplemente & Vitamina':       'Health & Beauty > Health Care > Vitamins & Supplements',
    'Kujdes Personal & Higjienë':  'Health & Beauty > Personal Care',
    'Pajisje Mjekësore':           'Health & Beauty > Health Care > Medical Equipment & Supplies',
    'Nënë & Fëmijë':              'Baby & Toddler',
    'Pajisje Ortopedike':          'Health & Beauty > Health Care > Braces & Supports',
    'Produkte Natyrale & Bimore':  'Health & Beauty > Health Care > Nutritional Supplements',
}
_GOOGLE_CATEGORY_DEFAULT = 'Health & Beauty'

# ── product_type: your store's own category path (used by Meta for product sets) ─
# Format: Top-level category > Subcategory
# Meta lets you filter and build product sets on this field directly.
def _product_type(category: str, subcategory: str) -> str:
    cat = (category or '').strip()
    sub = (subcategory or '').strip()
    if cat and sub:
        return f'{cat} > {sub}'
    return cat or sub


# ── custom_label_0: fine-grained skin/beauty theme for targeted ad sets ───────
# Covers your most common subcategory themes. Products without a match get no label.
_THEME_MAP = [
    (re.compile(r'k.?beauty',              re.I), 'K-Beauty'),
    (re.compile(r'akn[eë]|acne',           re.I), 'Acne'),
    (re.compile(r'anti.?ag|rrudh|mosh',    re.I), 'Anti-Age'),
    (re.compile(r'diell|spf|sun',          re.I), 'Sunscreen'),
    (re.compile(r'hidrat|moistur|lagësht', re.I), 'Moisturiser'),
    (re.compile(r'ser[uë]m|serum',         re.I), 'Serum'),
    (re.compile(r'pastrues|cleanser|tonic',re.I), 'Cleanser'),
    (re.compile(r'fytyr|facial|face',      re.I), 'Face Care'),
    (re.compile(r'trup|body|derm',         re.I), 'Body Care'),
    (re.compile(r'flok|hair',              re.I), 'Hair Care'),
    (re.compile(r'\bsy\b|eye\s*care|kujdes.*sy|sy.*kujdes', re.I), 'Eye Care'),
    (re.compile(r'vitaminë|vitamin',       re.I), 'Vitamins'),
    (re.compile(r'probio|prebio',          re.I), 'Probiotics'),
    (re.compile(r'omega|fish.?oil',        re.I), 'Omega'),
    (re.compile(r'fëmijë|femij|baby|bebë', re.I), 'Baby'),
    (re.compile(r'shtatzën|shtatzani|mama|nën[ëe]', re.I), 'Maternity'),
    (re.compile(r'ortoped|brez|mbështet', re.I),  'Orthopaedic'),
    (re.compile(r'bimor|herbal|natyral',   re.I), 'Natural & Herbal'),
]

# ── custom_label_2: stable English key per category ──────────────────────────
# ASCII-safe so product sets survive Albanian character rendering issues in Meta.
_CAT_KEY = {
    'Dermokozmetikë':             'Dermocosmetics',
    'Suplemente & Vitamina':      'Supplements',
    'Kujdes Personal & Higjienë': 'Personal Care',
    'Pajisje Mjekësore':          'Medical Devices',
    'Nënë & Fëmijë':             'Mother & Baby',
    'Pajisje Ortopedike':         'Orthopaedic',
    'Produkte Natyrale & Bimore': 'Natural Products',
}


def _theme_label(category: str, subcategory: str) -> str:
    text = f'{category or ""} {subcategory or ""}'
    for pattern, label in _THEME_MAP:
        if pattern.search(text):
            return label
    return ''


def _esc(val):
    return str(val or '').strip()


@feed_bp.route('/meta-product-feed.xml')
def meta_product_feed():
    products = list(mongo.db.products.find({
        'is_deleted': {'$ne': True},
        'in_stock': True,
    }, {
        '_id': 1, 'name': 1, 'description': 1, 'price': 1,
        'discount_price': 1, 'image_url': 1, 'brand': 1,
        'category': 1, 'subcategory': 1, 'is_best_seller': 1,
        'offer_status': 1, 'discount_from': 1, 'offer_name': 1,
    }))

    base_url = _site_base_url()
    rss = Element('rss', {'xmlns:g': 'http://base.google.com/ns/1.0', 'version': '2.0'})
    channel = SubElement(rss, 'channel')
    SubElement(channel, 'title').text = 'Barnatore MeldPharm'
    SubElement(channel, 'link').text = base_url
    SubElement(channel, 'description').text = 'Produkte nga Barnatorja MeldPharm'

    for p in products:
        pid = str(p['_id'])
        category   = _esc(p.get('category', ''))
        subcategory = _esc(p.get('subcategory', ''))
        base_price = float(p.get('price') or 0)
        base_disc  = float(p['discount_price']) if p.get('discount_price') else None
        _, sale_price = effective_price_with_promo(p, base_price, base_disc)

        # ── Required fields ─────────────────────────────────────────────────
        item = SubElement(channel, 'item')
        SubElement(item, 'g:id').text        = pid
        SubElement(item, 'g:title').text     = _esc(p.get('name'))
        # description must never be empty — fall back to title if needed
        desc = _esc(p.get('description')) or _esc(p.get('name'))
        SubElement(item, 'g:description').text = desc
        SubElement(item, 'g:link').text      = f'{base_url}/product/{pid}'
        SubElement(item, 'g:image_link').text = _esc(p.get('image_url'))
        SubElement(item, 'g:availability').text = 'in stock'
        SubElement(item, 'g:condition').text = 'new'
        SubElement(item, 'g:price').text     = f'{base_price:.2f} {CURRENCY}'
        if sale_price is not None:
            SubElement(item, 'g:sale_price').text = f'{sale_price:.2f} {CURRENCY}'
        SubElement(item, 'g:brand').text     = _esc(p.get('brand'))

        # ── google_product_category: proper taxonomy per category ────────────
        # Meta uses this for eligibility checks and automatic classification.
        google_cat = _GOOGLE_CATEGORY.get(category, _GOOGLE_CATEGORY_DEFAULT)
        SubElement(item, 'g:google_product_category').text = google_cat

        # ── product_type: your store's own hierarchy ─────────────────────────
        # Meta Commerce Manager uses this field to build product sets.
        # Format: "Main Category > Subcategory"  e.g. "Dermokozmetikë > Serum"
        pt = _product_type(category, subcategory)
        if pt:
            SubElement(item, 'g:product_type').text = pt

        # ── custom_label_0: fine-grained theme for ad-set targeting ──────────
        theme = _theme_label(category, subcategory)
        if theme:
            SubElement(item, 'g:custom_label_0').text = theme

        # ── custom_label_1: promotional status ───────────────────────────────
        # Lets you build separate ad sets for on-sale vs full-price products.
        if sale_price is not None:
            SubElement(item, 'g:custom_label_1').text = 'On Sale'
        else:
            SubElement(item, 'g:custom_label_1').text = 'Full Price'

        # ── custom_label_2: main store category (English-safe short key) ─────
        cat_key = _CAT_KEY.get(category, category)
        if cat_key:
            SubElement(item, 'g:custom_label_2').text = cat_key

        # ── custom_label_3: best seller flag ─────────────────────────────────
        if p.get('is_best_seller'):
            SubElement(item, 'g:custom_label_3').text = 'Best Seller'

    xml_str = parseString(tostring(rss, encoding='unicode')).toprettyxml(indent='  ', encoding='UTF-8')
    return Response(xml_str, mimetype='application/xml; charset=UTF-8')
