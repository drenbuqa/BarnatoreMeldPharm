"""
Secure image importer: downloads an external image URL, converts it to a
1000×1000 JPG with white background, and uploads it to Cloudinary.

Returns (cloudinary_url, public_id) on success, raises ImportError on failure.
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

_CLOUDINARY_HOST = "res.cloudinary.com"
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # 20 MB
_CONNECT_TIMEOUT = 10                     # seconds
_READ_TIMEOUT = 20                        # seconds
_MIN_DIMENSION = 500                      # warn if either axis is below this
_TARGET_SIZE = 1000
_JPEG_QUALITY = 83
_FOLDER = "meld-pharm/products"

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

    # Block bare numeric IP addresses immediately (no DNS lookup needed)
    try:
        ipaddress.ip_address(host)
        # If we get here, host IS an IP literal
        if _is_private_ip(host):
            raise ValueError(f"URL me adresë IP private nuk lejohet: {host}")
    except ValueError as e:
        if "private" in str(e):
            raise
        # host is a domain name — DNS validation happens in _resolve_and_check

    return url


def _resolve_to_safe_ip(host: str) -> str:
    """
    DNS-resolve *host* and return one validated public IP string.
    Raises ValueError if all resolved addresses are private/reserved.
    This single resolved IP is used for the actual connection, eliminating
    the DNS-rebinding race between check and connect.
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Nuk u zgjidh DNS për hostin '{host}': {e}")

    if not infos:
        raise ValueError(f"DNS nuk ktheu asnjë adresë për '{host}'.")

    for info in infos:
        ip = info[4][0]
        if not _is_private_ip(ip):
            return ip   # first public IP wins

    # Every resolved address was private
    private_ips = [info[4][0] for info in infos]
    raise ValueError(
        f"Hosti '{host}' zgjidhet vetëm në adresa private ({', '.join(private_ips)}). "
        "Nuk lejohet."
    )


def _download_image(url: str) -> bytes:
    """
    Download bytes from a validated public HTTPS URL.

    DNS rebinding protection: resolve hostname once, validate the IP, then
    connect *directly* to that IP by overriding HTTPSConnection.connect().
    No second DNS lookup is made by the underlying socket layer.
    """
    import http.client as _http

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443

    # Resolve once and validate — this IP is used for the actual connection
    safe_ip = _resolve_to_safe_ip(host)

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    # Subclass HTTPSConnection so connect() dials safe_ip instead of re-resolving host
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

    # Redirect handler: re-validate each hop before following
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
        # Decompression bomb guard (Pillow raises DecompressionBombError by default at 178 MP)
        img.verify()   # closes the file object
    except Exception as e:
        raise ValueError(f"Skedari nuk është imazh i vlefshëm: {e}")

    # Re-open after verify() (it closes the stream)
    img = Image.open(io.BytesIO(data))

    # Apply EXIF orientation
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # Warn on tiny source images
    w, h = img.size
    if w < _MIN_DIMENSION or h < _MIN_DIMENSION:
        log.warning(
            "Imazhi burimor është i vogël (%dx%d). "
            "Rekomandohet imazh ≥%dx%d.",
            w, h, _MIN_DIMENSION, _MIN_DIMENSION,
        )

    # Convert to RGBA so we can composite on a white background
    if img.mode in ("P", "LA"):
        img = img.convert("RGBA")
    elif img.mode != "RGBA":
        img = img.convert("RGBA")

    # Fit inside 1000×1000, then paste on a white square
    img.thumbnail((_TARGET_SIZE, _TARGET_SIZE), Image.LANCZOS)
    canvas = Image.new("RGB", (_TARGET_SIZE, _TARGET_SIZE), (255, 255, 255))
    offset_x = (_TARGET_SIZE - img.width) // 2
    offset_y = (_TARGET_SIZE - img.height) // 2
    # Use alpha channel as mask if present
    mask = img.split()[3] if img.mode == "RGBA" else None
    canvas.paste(img.convert("RGB"), (offset_x, offset_y), mask)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    buf.seek(0)
    return buf


def _upload_to_cloudinary(buf: io.BytesIO, public_id: str) -> tuple[str, str]:
    """Upload a JPEG buffer to Cloudinary. Returns (secure_url, public_id)."""
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError:
        raise RuntimeError("cloudinary nuk është instaluar. Shto 'cloudinary' te requirements.txt.")

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    api_key = os.environ.get("CLOUDINARY_API_KEY", "")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET", "")

    if not (cloud_name and api_key and api_secret):
        raise RuntimeError(
            "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY dhe CLOUDINARY_API_SECRET "
            "duhet të konfigurohen te variablat e mjedisit."
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )

    result = cloudinary.uploader.upload(
        buf,
        public_id=public_id,
        folder=_FOLDER,
        resource_type="image",
        format="jpg",
        overwrite=False,          # never silently overwrite an existing asset
        unique_filename=False,
        use_filename=True,
    )
    return result["secure_url"], result["public_id"]


# ── Public API ────────────────────────────────────────────────────────────────

def is_cloudinary_url(url: str) -> bool:
    """Return True if the URL is already hosted on this Cloudinary account."""
    if not url:
        return False
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "drljgepgy")
    return (
        _CLOUDINARY_HOST in url
        and f"/{cloud_name}/" in url
    )


def import_product_image(image_url: str, public_id_hint: str = "") -> tuple[str, str]:
    """
    Download *image_url*, process it into a 1000×1000 JPG, upload to Cloudinary.

    Returns (cloudinary_secure_url, cloudinary_public_id).
    Raises ValueError for user-facing errors (bad URL, blocked host, invalid image, etc.)
    Raises RuntimeError for configuration errors.
    """
    if is_cloudinary_url(image_url):
        # Already on our Cloudinary — extract existing public_id and return as-is
        # (public_id is the path after /upload/vXXXX/ up to the extension)
        import re
        m = re.search(r"/upload/(?:v\d+/)?(.+?)(?:\.\w+)?$", image_url)
        existing_pid = m.group(1) if m else ""
        return image_url, existing_pid

    # 1. Validate URL structure
    url = _validate_url(image_url)

    # 2. Download (includes SSRF DNS check + redirect validation + size limit)
    log.info("Shkarkimi i imazhit: %s", url)
    data = _download_image(url)

    # 3. Process: decode → orient → pad → JPG
    log.info("Përpunimi i imazhit (%d bytes)…", len(data))
    buf = _process_image(data)

    # 4. Derive a stable public_id from the hint or from the URL path
    if not public_id_hint:
        path = urllib.parse.urlparse(url).path
        basename = path.rstrip("/").rsplit("/", 1)[-1]
        # strip extension and sanitise
        name = basename.rsplit(".", 1)[0] if "." in basename else basename
        import re
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:60] or "product"
        import uuid
        public_id_hint = f"{name}_{uuid.uuid4().hex[:8]}"

    # 5. Upload
    log.info("Ngarkimi te Cloudinary: %s/%s", _FOLDER, public_id_hint)
    cld_url, cld_pid = _upload_to_cloudinary(buf, public_id_hint)
    log.info("Ngarkimi u krye: %s", cld_url)
    return cld_url, cld_pid
