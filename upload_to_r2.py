"""
Upload a local image file to R2 and print the public URL.
Usage: python3 upload_to_r2.py /path/to/image.jpg [optional-name]
"""
import io, os, sys
from dotenv import load_dotenv
load_dotenv(override=True)

import boto3
from botocore.config import Config as BotoConfig
from PIL import Image, ImageOps

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

def upload(file_path: str, name: str = "") -> str:
    with Image.open(file_path) as img:
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        img = img.convert("RGB")
        # Resize so longest side is max 1600px, preserve aspect ratio
        img.thumbnail((1600, 1600), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        data = buf.getvalue()

    slug = name or os.path.splitext(os.path.basename(file_path))[0]
    slug = slug.replace(" ", "_").lower()[:60]
    key = f"banners/{slug}.jpg"

    _s3.upload_fileobj(
        io.BytesIO(data), R2_BUCKET, key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )
    url = f"{R2_PUBLIC_URL}/{key}"
    print(f"\nUploaded successfully!")
    print(f"URL: {url}\n")
    return url

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 upload_to_r2.py /path/to/image.jpg [optional-name]")
        sys.exit(1)
    file_path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    upload(file_path, name)
