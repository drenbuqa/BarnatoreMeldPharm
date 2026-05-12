from datetime import datetime
from models.db import mongo
from bson import ObjectId

class Conversation:
    """Model for managing chat conversations with history"""

    @staticmethod
    def _serialize(doc):
        """Convert MongoDB document to JSON-safe dict"""
        if not doc:
            return None
        if '_id' in doc:
            doc['_id'] = str(doc['_id'])
        if 'user_id' in doc and doc['user_id']:
            doc['user_id'] = str(doc['user_id'])
        for key in ('created_at', 'updated_at'):
            if key in doc and isinstance(doc[key], datetime):
                doc[key] = doc[key].isoformat()
        for msg in doc.get('messages', []):
            if '_id' in msg:
                msg['_id'] = str(msg['_id'])
            if 'timestamp' in msg and isinstance(msg['timestamp'], datetime):
                msg['timestamp'] = msg['timestamp'].isoformat()
        return doc

    @staticmethod
    def create_conversation(user_id=None, title=None):
        """Create a new conversation"""
        now = datetime.utcnow()
        conversation = {
            'user_id': str(user_id) if user_id else None,
            'title': title or 'Biseda e re',
            'messages': [],
            'created_at': now,
            'updated_at': now,
            'is_active': True
        }

        result = mongo.db.conversations.insert_one(conversation)
        conversation['_id'] = str(result.inserted_id)
        conversation['created_at'] = now.isoformat()
        conversation['updated_at'] = now.isoformat()
        return conversation

    @staticmethod
    def get_conversation(conversation_id, user_id=None):
        """Get a specific conversation by ID"""
        try:
            query = {'_id': ObjectId(conversation_id)}
            if user_id:
                query['user_id'] = str(user_id)

            conversation = mongo.db.conversations.find_one(query)
            return Conversation._serialize(conversation)
        except:
            return None

    @staticmethod
    def get_user_conversations(user_id=None, limit=10):
        """Get all conversations for a user"""
        try:
            query = {'is_active': True}
            if user_id:
                query['user_id'] = str(user_id)
            else:
                query['user_id'] = {'$exists': False}

            conversations = list(mongo.db.conversations.find(query)
                                .sort('updated_at', -1)
                                .limit(limit))

            for conv in conversations:
                Conversation._serialize(conv)
                conv['message_count'] = len(conv.get('messages', []))
                messages = conv.get('messages', [])
                if messages:
                    last_msg = messages[-1]
                    content = last_msg.get('content', '')
                    conv['last_message'] = content[:50] + '...' if len(content) > 50 else content
                    conv['last_message_time'] = last_msg.get('timestamp')
                else:
                    conv['last_message'] = ''
                    conv['last_message_time'] = conv.get('created_at')

            return conversations
        except:
            return []

    @staticmethod
    def add_message(conversation_id, content, role='user', user_id=None):
        """Add a message to a conversation"""
        try:
            now = datetime.utcnow()
            message = {
                'role': role,
                'content': content,
                'timestamp': now
            }

            result = mongo.db.conversations.update_one(
                {'_id': ObjectId(conversation_id)},
                {
                    '$push': {'messages': message},
                    '$set': {'updated_at': now}
                }
            )

            if result.modified_count:
                message['_id'] = str(ObjectId())
                message['timestamp'] = now.isoformat()
                return message
            return None
        except:
            return None

    @staticmethod
    def get_conversation_messages(conversation_id, user_id=None, limit=50):
        """Get messages for a conversation"""
        try:
            query = {'_id': ObjectId(conversation_id)}
            if user_id:
                query['user_id'] = str(user_id)

            conversation = mongo.db.conversations.find_one(query)
            if conversation:
                messages = conversation.get('messages', [])
                messages.sort(key=lambda x: x.get('timestamp', datetime.utcnow()), reverse=False)
                messages = messages[-limit:]

                for message in messages:
                    if '_id' in message:
                        message['_id'] = str(message['_id'])
                    if 'timestamp' in message and isinstance(message['timestamp'], datetime):
                        message['timestamp'] = message['timestamp'].isoformat()

                return messages
            return []
        except:
            return []

    @staticmethod
    def update_conversation_title(conversation_id, title, user_id=None):
        """Update conversation title"""
        try:
            query = {'_id': ObjectId(conversation_id)}
            if user_id:
                query['user_id'] = str(user_id)

            result = mongo.db.conversations.update_one(
                query,
                {
                    '$set': {
                        'title': title,
                        'updated_at': datetime.utcnow()
                    }
                }
            )
            return result.modified_count > 0
        except:
            return False

    @staticmethod
    def delete_conversation(conversation_id, user_id=None):
        """Soft delete a conversation"""
        try:
            query = {'_id': ObjectId(conversation_id)}
            if user_id:
                query['user_id'] = str(user_id)

            result = mongo.db.conversations.update_one(
                query,
                {'$set': {'is_active': False, 'updated_at': datetime.utcnow()}}
            )
            return result.modified_count > 0
        except:
            return False

    @staticmethod
    def clear_conversation_messages(conversation_id, user_id=None):
        """Clear all messages in a conversation"""
        try:
            query = {'_id': ObjectId(conversation_id)}
            if user_id:
                query['user_id'] = str(user_id)

            result = mongo.db.conversations.update_one(
                query,
                {
                    '$set': {
                        'messages': [],
                        'updated_at': datetime.utcnow()
                    }
                }
            )
            return result.modified_count > 0
        except:
            return False
