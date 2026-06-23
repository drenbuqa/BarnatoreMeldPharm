"""
Migration: merge products sharing a variant_group into a single product
with a variants[] array. Run once, safe to re-run (skips already-migrated groups).

Usage:
    python -m scripts.migrate_to_variants
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app
from models.db import mongo
from bson import ObjectId
import uuid, re


def numeric_size_key(size_str):
    if not size_str:
        return (1, float('inf'), '')
    m = re.search(r'\d+(?:[.,]\d+)?', size_str)
    if m:
        try:
            return (0, float(m.group(0).replace(',', '.')), size_str.lower())
        except ValueError:
            pass
    return (0, float('inf'), size_str.lower())


def migrate():
    with app.app_context():
        # Find all non-deleted products that still have a variant_group
        grouped = list(mongo.db.products.find({
            'variant_group': {'$exists': True, '$ne': None, '$ne': ''},
            'is_deleted': {'$ne': True}
        }))

        if not grouped:
            print('No products with variant_group found. Nothing to do.')
            return

        # Group by variant_group value — skip sentinel/null-like strings
        SKIP_KEYS = {'none', 'null', 'nil', '', 'n/a', 'na'}
        groups = {}
        for p in grouped:
            key = str(p.get('variant_group', '')).strip()
            if key and key.lower() not in SKIP_KEYS:
                groups.setdefault(key, []).append(p)

        print(f'Found {len(groups)} variant groups across {len(grouped)} products.\n')

        for group_key, members in groups.items():
            if len(members) < 2:
                # Single product in group — just clear its variant_group, nothing to merge
                print(f'Group "{group_key}": only 1 product, skipping merge.')
                continue

            # Sort by numeric size so smallest is "main"
            members.sort(key=lambda p: numeric_size_key(p.get('size')))
            main = members[0]
            others = members[1:]

            main_id = main['_id']

            # Check if main already has variants (re-run guard)
            if main.get('variants'):
                print(f'Group "{group_key}": main product already has variants, skipping.')
                continue

            print(f'Group "{group_key}": merging {len(members)} products into {main.get("name")} [{main_id}]')

            # Build variants list — one entry per member (including the main itself)
            variants = []
            for p in members:
                size_val = (p.get('size') or '').strip()
                attr = {'Madhësia': size_val} if size_val else {}
                variant = {
                    'id': str(uuid.uuid4()),
                    'attributes': attr,
                    'price': float(p.get('price') or 0),
                    'discount_price': float(p['discount_price']) if p.get('discount_price') else None,
                    'image_url': p.get('image_url') or None,
                    'in_stock': p.get('in_stock', True),
                }
                variants.append(variant)
                print(f'  variant: {attr} → €{variant["price"]}')

            # Update main product: add variants, keep its own fields intact
            mongo.db.products.update_one(
                {'_id': main_id},
                {'$set': {'variants': variants, 'variant_group': None}}
            )

            # Soft-delete the other (now-redundant) products
            other_ids = [p['_id'] for p in others]
            mongo.db.products.update_many(
                {'_id': {'$in': other_ids}},
                {'$set': {'is_deleted': True, 'variant_group': None}}
            )
            print(f'  → soft-deleted {len(other_ids)} redundant product(s).\n')

        print('Migration complete.')


if __name__ == '__main__':
    migrate()
