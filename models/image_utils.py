import re

_CLOUDINARY_UPLOAD_RE = re.compile(r"(res\.cloudinary\.com/[^/]+/image/upload/)(?!.*\bf_auto\b)")


def cld(url, width=None):
    """Inject Cloudinary auto-format/auto-quality (and optional width) transforms
    into a raw Cloudinary upload URL, so images are served resized/compressed
    instead of at full original resolution. Non-Cloudinary URLs pass through untouched."""
    if not url or "res.cloudinary.com" not in url:
        return url

    transform = "f_auto,q_auto"
    if width:
        transform += f",w_{width}"

    match = _CLOUDINARY_UPLOAD_RE.search(url)
    if not match:
        return url

    insert_at = match.end()
    return url[:insert_at] + transform + "/" + url[insert_at:]
