"""
Fix banner images: they were squarified (1000x1000) during migration.
This script downloads each banner from R2, crops the white padding to restore
the original landscape shape, and re-uploads it to the same key.
"""
import io, os, sys, logging
import urllib.request

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger(__name__)

REQUIRED = ["MONGO_URI", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET", "R2_PUBLIC_URL"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    log.error("Missing env vars: %s", ", ".join(missing)); sys.exit(1)

import boto3, certifi
from botocore.config import Config as BotoConfig
from pymongo import MongoClient
from PIL import Image
import numpy as np

R2_PUBLIC_URL = os.environ["R2_PUBLIC_URL"].rstrip("/")
R2_BUCKET     = os.environ["R2_BUCKET"]

_s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    config=BotoConfig(signature_version="s3v4"),
    region_name="auto",
)

_client = MongoClient(os.environ["MONGO_URI"], tlsCAFile=certifi.where())
_db = _client.get_default_database()


def _object_key(r2_url: str) -> str:
    """Extract the object key from a full R2 public URL (strips query params)."""
    return r2_url.split("?")[0].replace(R2_PUBLIC_URL + "/", "")


def _download_r2(key: str) -> bytes:
    buf = io.BytesIO()
    _s3.download_fileobj(R2_BUCKET, key, buf)
    return buf.getvalue()


def _crop_white_padding(data: bytes) -> bytes:
    """Remove white/near-white borders from the image, preserving aspect ratio."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.array(img)

    # Mask of pixels that are NOT near-white/cream (threshold: any channel < 220)
    non_white = np.any(arr < 220, axis=2)

    rows = np.any(non_white, axis=1)

    if not rows.any():
        log.warning("  Image appears entirely white — skipping crop")
        return data

    rmin, rmax = np.where(rows)[0][[0, -1]]

    # Only trim top and bottom — never the sides, so full banner width is kept
    rmin = max(0, rmin - 2)
    rmax = min(img.height - 1, rmax + 2)

    cropped = img.crop((0, rmin, img.width, rmax + 1))

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90, optimize=True)
    log.info("  Cropped: %dx%d → %dx%d", img.width, img.height, cropped.width, cropped.height)
    return buf.getvalue()


def fix_banners(dry_run: bool = False):
    banners = list(_db.banners.find())
    log.info("Found %d banners", len(banners))

    for i, banner in enumerate(banners, 1):
        bid = str(banner["_id"])
        log.info("[%d/%d] Banner %s", i, len(banners), bid)

        for field in ("image_url", "mobile_image_url"):
            url = banner.get(field, "")
            if not url or R2_PUBLIC_URL not in url:
                continue

            key = _object_key(url)
            try:
                data = _download_r2(key)
                fixed = _crop_white_padding(data)

                if len(fixed) == len(data) and fixed == data:
                    log.info("  %s — no change needed", field)
                    continue

                if dry_run:
                    log.info("  %s — DRY RUN (would re-upload %s)", field, key)
                else:
                    _s3.upload_fileobj(
                        io.BytesIO(fixed), R2_BUCKET, key,
                        ExtraArgs={"ContentType": "image/jpeg"},
                    )
                    log.info("  %s — re-uploaded ✓", field)
            except Exception as e:
                log.error("  %s FAILED: %s", field, e)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        log.info("=== DRY RUN ===")
    fix_banners(dry_run=dry_run)
    log.info("Done.")
