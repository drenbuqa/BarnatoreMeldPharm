"""
Secure image importer: downloads an external image URL, converts it to a
1000×1000 JPG with white background, and uploads it to Cloudflare R2.

Returns (r2_public_url, object_key) on success, raises ImportError on failure.
"""

import io
import ipaddress
import logging
import os
import socket
import urllib.parse
import urllib.request
import ssl
import certifi

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # 20 MB
_CONNECT_TIMEOUT = 10                     # seconds
_READ_TIMEOUT = 20                        # seconds
_MIN_DIMENSION = 500                      # warn if either axis is below this
_TARGET_SIZE = 1000
_JPEG_QUALITY = 83
_FOLDER = "products"

# Headers that mimic a real browser so fewer sites block the download
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Private network ranges blocked for SSRF protection ───────────────────────

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),      # multicast
    ipaddress.ip_network("240.0.0.0/4"),      # reserved
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return True   # unparseable → treat as unsafe


def _validate_url(url: str) -> str:
    """Raise ValueError for obviously unsafe URLs; return normalised URL."""
    if not url or not isinstance(url, str):
        raise ValueError("URL e zbrazët ose e pavlefshme.")

    url = url.strip()
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Vetëm URL-të HTTPS pranohen.")

    host = parsed.hostname
    if not host:
        raise ValueError("URL nuk ka host të vlefshëm.")

    try:
        ipaddress.ip_address(host)
        if _is_private_ip(host):
            raise ValueError(f"URL me adresë IP private nuk lejohet: {host}")
    except ValueError as e:
        if "private" in str(e):
            raise

    return url


def _resolve_to_safe_ip(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Nuk u zgjidh DNS për hostin '{host}': {e}")

    if not infos:
        raise ValueError(f"DNS nuk ktheu asnjë adresë për '{host}'.")

    for info in infos:
        ip = info[4][0]
        if not _is_private_ip(ip):
            return ip

    private_ips = [info[4][0] for info in infos]
    raise ValueError(
        f"Hosti '{host}' zgjidhet vetëm në adresa private ({', '.join(private_ips)}). "
        "Nuk lejohet."
    )


def _download_image(url: str) -> bytes:
    import http.client as _http

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443

    safe_ip = _resolve_to_safe_ip(host)

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    class _PinnedHTTPSConnection(_http.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection(
                (safe_ip, self.port or 443),
                timeout=self.timeout,
            )
            self.sock = ssl_ctx.wrap_socket(raw, server_hostname=self.host)

    class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_PinnedHTTPSConnection, req)

    class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            rp = urllib.parse.urlparse(newurl)
            if rp.scheme != "https":
                raise ValueError(f"Ridrejtim në URL jo-HTTPS: {newurl}")
            _resolve_to_safe_ip(rp.hostname)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    req = urllib.request.Request(url, headers=_HEADERS)
    opener = urllib.request.build_opener(_PinnedHTTPSHandler(), _SafeRedirectHandler())

    try:
        with opener.open(req, timeout=(_CONNECT_TIMEOUT + _READ_TIMEOUT)) as resp:
            chunks = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"Imazhi është shumë i madh (>{_MAX_DOWNLOAD_BYTES // (1024*1024)} MB)."
                    )
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as e:
        raise ValueError(f"Serveri ktheu gabim HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise ValueError(f"Nuk u lidh me hostin: {e.reason}")


def _process_image(data: bytes) -> io.BytesIO:
    """Decode, validate, orient, pad to 1000×1000 white JPG."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise RuntimeError("Pillow nuk është instaluar. Shto 'Pillow' te requirements.txt.")

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception as e:
        raise ValueError(f"Skedari nuk është imazh i vlefshëm: {e}")

    img = Image.open(io.BytesIO(data))

    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    w, h = img.size
    if w < _MIN_DIMENSION or h < _MIN_DIMENSION:
        log.warning(
            "Imazhi burimor është i vogël (%dx%d). "
            "Rekomandohet imazh ≥%dx%d.",
            w, h, _MIN_DIMENSION, _MIN_DIMENSION,
        )

    if img.mode in ("P", "LA"):
        img = img.convert("RGBA")
    elif img.mode != "RGBA":
        img = img.convert("RGBA")

    img.thumbnail((_TARGET_SIZE, _TARGET_SIZE), Image.LANCZOS)
    canvas = Image.new("RGB", (_TARGET_SIZE, _TARGET_SIZE), (255, 255, 255))
    offset_x = (_TARGET_SIZE - img.width) // 2
    offset_y = (_TARGET_SIZE - img.height) // 2
    mask = img.split()[3] if img.mode == "RGBA" else None
    canvas.paste(img.convert("RGB"), (offset_x, offset_y), mask)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    buf.seek(0)
    return buf


def _upload_to_r2(buf: io.BytesIO, object_key: str) -> str:
    """Upload a JPEG buffer to Cloudflare R2. Returns the public URL."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError("boto3 nuk është instaluar. Shto 'boto3' te requirements.txt.")

    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    endpoint = os.environ.get("R2_ENDPOINT", "")
    bucket = os.environ.get("R2_BUCKET", "meldpharm-images")
    public_url_base = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

    if not (access_key and secret_key and endpoint):
        raise RuntimeError(
            "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY dhe R2_ENDPOINT "
            "duhet të konfigurohen te variablat e mjedisit."
        )

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    buf.seek(0)
    s3.upload_fileobj(
        buf,
        bucket,
        object_key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )

    return f"{public_url_base}/{object_key}"


# ── Public API ────────────────────────────────────────────────────────────────

def is_cloudinary_url(url: str) -> bool:
    """Return True if the URL is hosted on Cloudinary."""
    if not url:
        return False
    return "res.cloudinary.com" in url


def is_r2_url(url: str) -> bool:
    """Return True if the URL is already hosted on our R2 bucket."""
    if not url:
        return False
    public_url_base = os.environ.get("R2_PUBLIC_URL", "images.barnatoremeldpharm.com")
    return public_url_base.replace("https://", "") in url


def import_product_image(image_url: str, public_id_hint: str = "") -> tuple[str, str]:
    """
    Download *image_url*, process it into a 1000×1000 JPG, upload to R2.

    Returns (public_url, object_key).
    Raises ValueError for user-facing errors.
    Raises RuntimeError for configuration errors.
    """
    if is_r2_url(image_url):
        # Already on our R2 — extract key and return as-is
        public_url_base = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
        key = image_url.replace(public_url_base + "/", "")
        return image_url, key

    # 1. Validate URL structure
    url = _validate_url(image_url)

    # 2. Download
    log.info("Shkarkimi i imazhit: %s", url)
    data = _download_image(url)

    # 3. Process: decode → orient → pad → JPG
    log.info("Përpunimi i imazhit (%d bytes)…", len(data))
    buf = _process_image(data)

    # 4. Derive a stable object key
    if not public_id_hint:
        path = urllib.parse.urlparse(url).path
        basename = path.rstrip("/").rsplit("/", 1)[-1]
        name = basename.rsplit(".", 1)[0] if "." in basename else basename
        import re
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:60] or "product"
        import uuid
        public_id_hint = f"{name}_{uuid.uuid4().hex[:8]}"

    object_key = f"{_FOLDER}/{public_id_hint}.jpg"

    # 5. Upload
    log.info("Ngarkimi te R2: %s", object_key)
    public_url = _upload_to_r2(buf, object_key)
    log.info("Ngarkimi u krye: %s", public_url)
    return public_url, object_key
