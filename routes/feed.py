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

# Subcategory → custom_label_0 mapping for Meta product sets
_LABEL_MAP = [
    (re.compile(r'k.?beauty', re.I),          'K-Beauty'),
    (re.compile(r'akn|acne', re.I),            'Acne'),
    (re.compile(r'anti.?ag|rrudh|mosh', re.I), 'Anti-Age'),
    (re.compile(r'diell|spf|sun', re.I),       'Sunscreens'),
]

def _subcategory_label(subcategory):
    sub = subcategory or ''
    for pattern, label in _LABEL_MAP:
        if pattern.search(sub):
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
    }))

    base_url = _site_base_url()
    rss = Element('rss', {'xmlns:g': 'http://base.google.com/ns/1.0', 'version': '2.0'})
    channel = SubElement(rss, 'channel')
    SubElement(channel, 'title').text = 'Barnatore MeldPharm'
    SubElement(channel, 'link').text = base_url
    SubElement(channel, 'description').text = 'Produkte nga Barnatorja MeldPharm'

    for p in products:
        pid = str(p['_id'])
        base_price = float(p.get('price') or 0)
        base_disc = float(p['discount_price']) if p.get('discount_price') else None
        _, sale_price = effective_price_with_promo(p, base_price, base_disc)

        item = SubElement(channel, 'item')
        SubElement(item, 'g:id').text = pid
        SubElement(item, 'g:title').text = _esc(p.get('name'))
        SubElement(item, 'g:description').text = _esc(p.get('description')) or _esc(p.get('name'))
        SubElement(item, 'g:link').text = f'{base_url}/product/{pid}'
        SubElement(item, 'g:image_link').text = _esc(p.get('image_url'))
        SubElement(item, 'g:availability').text = 'in stock'
        SubElement(item, 'g:condition').text = 'new'
        SubElement(item, 'g:price').text = f'{base_price:.2f} {CURRENCY}'
        if sale_price is not None:
            SubElement(item, 'g:sale_price').text = f'{sale_price:.2f} {CURRENCY}'
        SubElement(item, 'g:brand').text = _esc(p.get('brand'))
        SubElement(item, 'g:google_product_category').text = 'Health & Beauty'

        # custom_label_0: subcategory-based set (K-Beauty, Acne, Anti-Age, Sunscreens)
        label0 = _subcategory_label(p.get('subcategory', ''))
        if label0:
            SubElement(item, 'g:custom_label_0').text = label0

        # custom_label_1: best seller flag
        if p.get('is_best_seller'):
            SubElement(item, 'g:custom_label_1').text = 'Best Seller'

    xml_str = parseString(tostring(rss, encoding='unicode')).toprettyxml(indent='  ', encoding='UTF-8')
    return Response(xml_str, mimetype='application/xml; charset=UTF-8')
