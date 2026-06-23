from flask_login import UserMixin
from .db import mongo
from bson import ObjectId

class User(UserMixin):
    def __init__(self, user_data):
        self._data = user_data
        self.id = str(user_data.get('_id'))
        self.username = user_data.get('username')
        self.email = user_data.get('email')
        self.password = user_data.get('password')
        self.is_admin = user_data.get('is_admin', False)
        # Add profile fields
        self.first_name = user_data.get('first_name', '')
        self.last_name = user_data.get('last_name', '')
        self.fullname = user_data.get('fullname', '') or f"{self.first_name} {self.last_name}".strip()
        self.address = user_data.get('address', '')
        self.city = user_data.get('city', '')
        self.country = user_data.get('country', '')
        self.phone = user_data.get('phone', '')
        self.specifikat = user_data.get('specifikat', '')
        self.favorites = user_data.get('favorites', [])
        self.newsletter_subscribed = user_data.get('newsletter_subscribed', False)

    @staticmethod
    def create(username, email, password_hash, is_admin=False):
        user_id = mongo.db.users.insert_one({
            "username": username,
            "email": email,
            "password": password_hash,
            "is_admin": is_admin,
            "first_name": "",
            "last_name": "",
            "fullname": "",
            "address": "",
            "city": "",
            "country": "",
            "phone": "",
            "specifikat": ""
        }).inserted_id
        return User.get_by_id(user_id)

    @staticmethod
    def create_google(username, email, google_id, avatar=""):
        user_id = mongo.db.users.insert_one({
            "username": username,
            "email": email,
            "password": None,
            "is_admin": False,
            "google_id": google_id,
            "avatar": avatar,
            "first_name": "",
            "last_name": "",
            "fullname": username,
            "address": "",
            "city": "",
            "country": "",
            "phone": "",
            "specifikat": "",
            "auth_provider": "google",
        }).inserted_id
        return User.get_by_id(user_id)

    @staticmethod
    def link_google(user_id, google_id, avatar=""):
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"google_id": google_id, "avatar": avatar}}
        )

    @staticmethod
    def update_profile(user_id, profile_data):
        update_data = {}
        
        # Only add fields that are provided in profile_data
        fields = ['address', 'city', 'country', 'phone', 'first_name', 'last_name', 'specifikat']
        for field in fields:
            if field in profile_data:
                update_data[field] = profile_data[field]
        
        # Automatically update fullname if first or last name is changed
        # We need the current values if only one is provided
        if 'first_name' in profile_data or 'last_name' in profile_data:
            user = User.get_by_id(user_id)
            fname = profile_data.get('first_name', user.first_name if user else '')
            lname = profile_data.get('last_name', user.last_name if user else '')
            update_data["fullname"] = f"{fname} {lname}".strip()
        
        if not update_data:
            return

        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )

    @staticmethod
    def get_by_id(user_id):
        if not user_id:
            return None
        try:
            user_data = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            if user_data:
                return User(user_data)
        except:
            return None
        return None

    @staticmethod
    def get_by_email(email):
        user_data = mongo.db.users.find_one({"email": email})
        if user_data:
            return User(user_data)
        return None

    @staticmethod
    def set_password(user_id, new_password_hash):
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"password": new_password_hash}}
        )

    @staticmethod
    def update_cart(user_id, cart):
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"cart": cart}}
        )

    @staticmethod
    def get_cart(user_id):
        try:
            user_data = mongo.db.users.find_one({"_id": ObjectId(user_id)}, {"cart": 1})
            return user_data.get('cart', {}) if user_data else {}
        except:
            return {}

    @staticmethod
    def set_newsletter(user_id, subscribed: bool):
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"newsletter_subscribed": subscribed}}
        )

    @staticmethod
    def get_newsletter_subscribers():
        """Return list of (email, username) for all subscribed users."""
        users = list(mongo.db.users.find(
            {"newsletter_subscribed": True},
            {"email": 1, "username": 1}
        ))
        # Also include guest subscribers from the separate collection
        guests = list(mongo.db.newsletter_subscribers.find(
            {}, {"email": 1}
        ))
        seen = {u["email"] for u in users}
        for g in guests:
            if g["email"] not in seen:
                users.append({"email": g["email"], "username": g["email"].split("@")[0]})
        return users
