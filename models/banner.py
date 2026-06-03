from .db import mongo
from bson import ObjectId
from datetime import datetime


def _banner_sort_key(banner):
    sort_order = banner.get('sort_order')
    try:
        sort_value = int(sort_order)
    except (TypeError, ValueError):
        sort_value = 9999
    return (sort_value, str(banner.get('_id') or ''))


def _banner_expiry_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
        return value
    if isinstance(value, str):
        for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None

class Banner:
    @staticmethod
    def get_all():
        banners = list(mongo.db.banners.find())
        return sorted(banners, key=_banner_sort_key)

    @staticmethod
    def get_active():
        today = datetime.now().date()
        active_banners = []
        for banner in Banner.get_all():
            if not banner.get('is_active'):
                continue
            expiry_date = _banner_expiry_date(banner.get('expires_at'))
            if expiry_date and expiry_date < today:
                continue
            active_banners.append(banner)
        return active_banners

    @staticmethod
    def normalize_sort_order():
        banners = Banner.get_all()
        updated = 0
        for index, banner in enumerate(banners, start=1):
            try:
                current_order = int(banner.get('sort_order'))
            except (TypeError, ValueError):
                current_order = None
            if current_order != index:
                mongo.db.banners.update_one({"_id": banner["_id"]}, {"$set": {"sort_order": index}})
                updated += 1
        return updated

    @staticmethod
    def get_by_id(banner_id):
        try:
            return mongo.db.banners.find_one({"_id": ObjectId(banner_id)})
        except:
            return None

    @staticmethod
    def create(data):
        return mongo.db.banners.insert_one(data)

    @staticmethod
    def update(banner_id, data):
        return mongo.db.banners.update_one(
            {"_id": ObjectId(banner_id)},
            {"$set": data}
        )

    @staticmethod
    def delete(banner_id):
        return mongo.db.banners.delete_one({"_id": ObjectId(banner_id)})
