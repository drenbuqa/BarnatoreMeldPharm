from .db import mongo
from datetime import datetime
from bson import ObjectId

class Order:
    @staticmethod
    def get_by_id(order_id):
        if not order_id:
            return None
        try:
            return mongo.db.orders.find_one({"_id": ObjectId(order_id)})
        except Exception:
            return None

    @staticmethod
    def create(order_data):
        order = {
            "fullname": order_data.get('fullname'),
            "email": order_data.get('email'),
            "address": order_data.get('address'),
            "city": order_data.get('city'),
            "country": order_data.get('country'),
            "phone": order_data.get('phone'),
            "payment_method": order_data.get('payment_method'),
            "shipping_method": order_data.get('shipping_method'),
            "items": order_data.get('items'),
            "total_price": order_data.get('total_price'),
            "shipping_cost": order_data.get('shipping_cost'),
            "grand_total": order_data.get('grand_total'),
            "user_id": order_data.get('user_id'), # Optional, if logged in
            "status": order_data.get('status', 'Pending'),
            "confirmation_email_sent": order_data.get('confirmation_email_sent', False),
            "confirmation_email_sent_at": order_data.get('confirmation_email_sent_at'),
            "created_at": datetime.utcnow()
        }
        
        result = mongo.db.orders.insert_one(order)
        return str(result.inserted_id)

    @staticmethod
    def update_status(order_id, status):
        update_data = {"status": status}
        if status != 'Confirmed':
            update_data["confirmation_email_sent"] = False
            update_data["confirmation_email_sent_at"] = None

        mongo.db.orders.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": update_data}
        )

    @staticmethod
    def get_by_user(user_id):
        return list(mongo.db.orders.find({"user_id": user_id}).sort("created_at", -1))
    
    @staticmethod
    def get_all():
        return list(mongo.db.orders.find().sort("created_at", -1))
