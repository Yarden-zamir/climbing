"""Image shrinking for stored faces and avatars."""

import io

from PIL import Image, ImageOps

FACE_MAX_SIDE = 256
FACE_QUALITY = 82
WEBP = "image/webp"


def shrink_image(data: bytes, max_side: int = FACE_MAX_SIDE, quality: int = FACE_QUALITY) -> tuple[bytes, str]:
    """Return the image re-encoded as WebP, no larger than max_side on either edge.

    Anything Pillow cannot read is returned unchanged with a generic content type,
    so a bad upload fails at validation rather than here.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
    except Exception:
        return data, "application/octet-stream"
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((max_side, max_side))
    out = io.BytesIO()
    image.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue(), WEBP
