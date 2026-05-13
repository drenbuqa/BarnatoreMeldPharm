from flask_pymongo import PyMongo
from typing import Any
import certifi
import ssl

# Typing as Any to avoid static analysis errors where the DB attribute
# may not be recognized by type checkers before app initialization.
mongo: Any = PyMongo()

def init_db(app):
    uri = app.config.get('MONGO_URI', '')
    
    is_cloud = 'mongodb+srv' in uri
    is_explicit_tls = 'tls=true' in uri.lower() or 'ssl=true' in uri.lower()
    
    if is_cloud or is_explicit_tls:
        mongo.init_app(app, tlsCAFile=certifi.where())
    else:
        # Explicitly pass tls=False to ensure no SSL handshake is attempted on localhost
        mongo.init_app(app, tls=False)
