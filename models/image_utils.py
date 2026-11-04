import re
import os

_CLOUDINARY_UPLOAD_RE = re.compile(r"(res\.cloudinary\.com/[^/]+/image/upload/)(?!.*\bf_auto\b)")


def cld(url, width=None):
    """Pass R2 URLs through unchanged; inject Cloudinary transforms for legacy Cloudinary URLs."""
    if not url:
        return url

    # R2 / any non-Cloudinary URL — already a processed JPEG, serve as-is
    if "res.cloudinary.com" not in url:
        return url

    # Legacy Cloudinary URL — inject auto-format/quality transforms
    transform = "f_auto,q_auto"
    if width:
        transform += f",w_{width}"

    match = _CLOUDINARY_UPLOAD_RE.search(url)
    if not match:
        return url

    insert_at = match.end()
    return url[:insert_at] + transform + "/" + url[insert_at:]
