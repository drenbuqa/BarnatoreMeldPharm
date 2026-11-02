#!/usr/bin/env python3
"""
Backup all products (and orders) from MongoDB to timestamped JSON files.
Usage:
    python backup_products.py
    python backup_products.py --collections products,orders,users

Backups are saved to ./backups/<timestamp>/ and a latest/ symlink is kept.
"""
import os, sys, json, datetime, argparse, shutil
from pathlib import Path
from bson import ObjectId

def json_serial(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serialisable")

def run_backup(collections, out_dir):
    # Load env / Flask app just enough to get mongo
    from dotenv import load_dotenv
    load_dotenv()
    sys.path.insert(0, str(Path(__file__).parent))
    from flask import Flask
    app = Flask(__name__)
    app.config['MONGO_URI'] = os.environ['MONGO_URI']
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'backup')
    from models.db import init_db, mongo
    init_db(app)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        for col_name in collections:
            col = getattr(mongo.db, col_name, None)
            if col is None:
                print(f"  [skip] {col_name} — not found")
                continue
            docs = list(col.find({'is_deleted': {'$ne': True}}))
            dest = out_dir / f"{col_name}.json"
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(docs, f, default=json_serial, ensure_ascii=False, indent=2)
            print(f"  [ok]   {col_name}: {len(docs)} documents → {dest}")

    # Keep a 'latest' symlink
    latest = Path('backups/latest')
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(out_dir.resolve(), target_is_directory=True)
    print(f"\nBackup complete → {out_dir}")
    print(f"Latest symlink  → backups/latest")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backup MongoDB collections to JSON')
    parser.add_argument('--collections', default='products,orders,users,cart',
                        help='Comma-separated list of collections (default: products,orders,users,cart)')
    args = parser.parse_args()

    ts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    out_dir = Path(f'backups/{ts}')
    cols = [c.strip() for c in args.collections.split(',') if c.strip()]

    print(f"Backing up: {', '.join(cols)}")
    print(f"Destination: {out_dir}\n")
    run_backup(cols, out_dir)
