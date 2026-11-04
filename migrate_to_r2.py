"""
Migration script: Cloudinary → Cloudflare R2

Migrates all Cloudinary image URLs stored in MongoDB (products + banners)
to R2. Runs safely: skips already-migrated images, never deletes from
Cloudinary, logs every action, and can be re-run if interrupted.

Usage:
    python migrate_to_r2.py           # migrate all
    python migrate_to_r2.py --dry-run # show what would be done, no changes
    python migrate_to_r2.py --test 3  # migrate only 3 products as a test
"""

import argparse
import io
import logging
import os
import sys
import time
import urllib.request
import uuid

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Validate environment ──────────────────────────────────────────────────────

REQUIRED = ["MONGO_URI", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET", "R2_PUBLIC_URL"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    log.error("Missing environment variables: %s", ", ".join(missing))
    sys.exit(1)

R2_PUBLIC_URL = os.environ["R2_PUBLIC_URL"].rstrip("/")
R2_BUCKET     = os.environ["R2_BUCKET"]
R2_ENDPOINT   = os.environ["R2_ENDPOINT"]
FOLDER        = "products"

# ── R2 client ─────────────────────────────────────────────────────────────────

import boto3
from botocore.config import Config as BotoConfig

_s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    config=BotoConfig(signature_version="s3v4"),
    region_name="auto",
)


def _upload_bytes(data: bytes, key: str) -> str:
    _s3.upload_fileobj(
        io.BytesIO(data),
        R2_BUCKET,
        key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )
    return f"{R2_PUBLIC_URL}/{key}"


# ── Image download + process ──────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

def _download(url: str) -> bytes:
    import ssl
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers=_HEADERS)
    https_handler = urllib.request.HTTPSHandler(context=ssl_ctx)
    opener = urllib.request.build_opener(https_handler)
    with opener.open(req, timeout=30) as r:
        return r.read()


def _process(data: bytes) -> bytes:
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(data))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    img.thumbnail((1000, 1000), Image.LANCZOS)
    canvas = Image.new("RGB", (1000, 1000), (255, 255, 255))
    ox = (1000 - img.width) // 2
    oy = (1000 - img.height) // 2
    mask = img.split()[3] if img.mode == "RGBA" else None
    canvas.paste(img.convert("RGB"), (ox, oy), mask)
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=83, optimize=True)
    return buf.getvalue()


def migrate_url(url: str, hint: str = "") -> str | None:
    """Download url, process, upload to R2. Returns new R2 url or None on failure."""
    if not url:
        return None
    if R2_PUBLIC_URL.replace("https://", "") in url:
        return url  # already on R2
    if "res.cloudinary.com" not in url:
        return url  # not a Cloudinary URL, leave as-is

    slug = hint or uuid.uuid4().hex[:12]
    key = f"{FOLDER}/{slug}.jpg"

    try:
        data = _download(url)
        processed = _process(data)
        new_url = _upload_bytes(processed, key)
        return new_url
    except Exception as e:
        log.error("  FAILED %s — %s", url[:80], e)
        return None


# ── MongoDB ───────────────────────────────────────────────────────────────────

import certifi
from pymongo import MongoClient
from bson import ObjectId

_client = MongoClient(os.environ["MONGO_URI"], tlsCAFile=certifi.where())
_db     = _client.get_default_database()


# ── Migration logic ───────────────────────────────────────────────────────────

def migrate_products(dry_run: bool, limit: int | None):
    query = {"is_deleted": {"$ne": True}}
    products = list(_db.products.find(query))
    if limit:
        products = products[:limit]

    total   = len(products)
    updated = 0
    skipped = 0
    failed  = 0

    log.info("── Products: %d to process ──", total)

    for i, product in enumerate(products, 1):
        pid   = str(product["_id"])
        name  = product.get("name", pid)[:50]
        log.info("[%d/%d] %s", i, total, name)

        changes = {}

        # Main image
        main = product.get("image_url", "")
        if main and "res.cloudinary.com" in main:
            hint = f"prod_{pid}_main"
            new = migrate_url(main, hint)
            if new and new != main:
                changes["image_url"] = new
                log.info("  main ✓")
            elif new is None:
                failed += 1
        elif main:
            log.info("  main already OK")

        # Extra images array
        extras = product.get("images", [])
        new_extras = []
        extras_changed = False
        for j, img_url in enumerate(extras):
            if img_url and "res.cloudinary.com" in img_url:
                hint = f"prod_{pid}_img{j}"
                new = migrate_url(img_url, hint)
                if new and new != img_url:
                    new_extras.append(new)
                    extras_changed = True
                    log.info("  image[%d] ✓", j)
                else:
                    new_extras.append(img_url)  # keep original on failure
                    if new is None:
                        failed += 1
            else:
                new_extras.append(img_url)

        if extras_changed:
            changes["images"] = new_extras

        if changes:
            if not dry_run:
                _db.products.update_one({"_id": product["_id"]}, {"$set": changes})
            updated += 1
            log.info("  → %s", "DRY RUN (not saved)" if dry_run else "saved")
        else:
            skipped += 1

        # Small delay to be respectful to Cloudinary's servers
        time.sleep(0.3)

    log.info("Products done — updated: %d, skipped: %d, failed: %d", updated, skipped, failed)
    return failed


def migrate_banners(dry_run: bool):
    banners = list(_db.banners.find())
    total   = len(banners)
    updated = 0
    failed  = 0

    log.info("── Banners: %d to process ──", total)

    for i, banner in enumerate(banners, 1):
        bid  = str(banner["_id"])
        log.info("[%d/%d] Banner %s", i, total, bid)

        changes = {}

        for field in ("image_url", "mobile_image_url"):
            url = banner.get(field, "")
            if url and "res.cloudinary.com" in url:
                hint = f"banner_{bid}_{field}"
                new = migrate_url(url, hint)
                if new and new != url:
                    changes[field] = new
                    log.info("  %s ✓", field)
                elif new is None:
                    failed += 1

        if changes:
            if not dry_run:
                _db.banners.update_one({"_id": banner["_id"]}, {"$set": changes})
            updated += 1
            log.info("  → %s", "DRY RUN (not saved)" if dry_run else "saved")

        time.sleep(0.3)

    log.info("Banners done — updated: %d, failed: %d", updated, failed)
    return failed


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, make no changes")
    parser.add_argument("--test", type=int, metavar="N", help="Migrate only N products as a test")
    args = parser.parse_args()

    if args.dry_run:
        log.info("=== DRY RUN MODE — no changes will be saved ===")

    total_failures = 0
    total_failures += migrate_products(dry_run=args.dry_run, limit=args.test)

    if not args.test:
        total_failures += migrate_banners(dry_run=args.dry_run)

    if total_failures:
        log.warning("Finished with %d failure(s). Re-run to retry failed images.", total_failures)
    else:
        log.info("Migration complete — no failures.")


if __name__ == "__main__":
    main()
