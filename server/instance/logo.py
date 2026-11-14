"""Checks an uploaded logo: PNG, JPEG or SVG, at most 1 MB, square. SVGs are rebuilt from an allowlist of
elements and attributes, so scripts, event handlers, foreign content and external references never survive.

No image library is needed: the type comes from the file's bytes (not its name), and the size from the PNG
header, the JPEG frame header or the SVG viewBox / width and height.
"""

import re
import struct
import xml.etree.ElementTree as ET

MAX_LOGO_BYTES = 1024 * 1024
# Width and height may differ by up to 2% (a 512 x 508 export still counts as square).
SQUARE_TOLERANCE = 0.02

PNG = "image/png"
JPEG = "image/jpeg"
SVG = "image/svg+xml"


class LogoError(ValueError):
    pass


def check_logo(data: bytes) -> tuple[bytes, str]:
    """(bytes to store, content type), or raises LogoError with a message for the user."""
    if not data:
        raise LogoError("The file is empty.")
    if len(data) > MAX_LOGO_BYTES:
        raise LogoError("The logo is too large; the limit is 1 MB.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type, size = PNG, _png_size(data)
    elif data.startswith(b"\xff\xd8\xff"):
        content_type, size = JPEG, _jpeg_size(data)
    else:
        data, size = sanitize_svg(data)
        content_type = SVG
    if size is None:
        raise LogoError("Could not read the image size. Upload a PNG, SVG or JPG.")
    _require_square(*size)
    return data, content_type


def _require_square(width: float, height: float):
    if width <= 0 or height <= 0:
        raise LogoError("Could not read the image size. Upload a PNG, SVG or JPG.")
    if abs(width - height) > max(width, height) * SQUARE_TOLERANCE:
        raise LogoError(f"The logo must be square; this one is {_n(width)} x {_n(height)}.")


def _n(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _png_size(data: bytes):
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


# Start-of-frame markers carry the image size (C4, C8 and CC are other segment types).
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_size(data: bytes):
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if marker in _SOF:
            if i + 9 > len(data):
                return None
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


# ---- SVG ----

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ALLOWED_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "title", "desc", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask", "marker",
    "filter", "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite", "feConvolveMatrix",
    "feDiffuseLighting", "feDisplacementMap", "feDistantLight", "feDropShadow", "feFlood", "feFuncA", "feFuncB",
    "feFuncG", "feFuncR", "feGaussianBlur", "feMerge", "feMergeNode", "feMorphology", "feOffset",
    "fePointLight", "feSpecularLighting", "feSpotLight", "feTile", "feTurbulence",
}

ALLOWED_ATTRIBUTES = {
    "id", "class", "style", "lang", "transform", "viewBox", "preserveAspectRatio", "version", "width", "height",
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr", "d", "points", "pathLength",
    "dx", "dy", "rotate", "textLength", "lengthAdjust", "startOffset", "method", "spacing", "side",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap",
    "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "opacity", "color",
    "clip-path", "clip-rule", "clipPathUnits", "mask", "maskUnits", "maskContentUnits", "filter", "filterUnits",
    "primitiveUnits", "visibility", "display", "overflow", "vector-effect", "paint-order", "shape-rendering",
    "text-rendering", "color-interpolation", "color-interpolation-filters", "flood-color", "flood-opacity",
    "lighting-color", "stop-color", "stop-opacity", "offset", "gradientUnits", "gradientTransform",
    "spreadMethod", "patternUnits", "patternContentUnits", "patternTransform", "markerWidth", "markerHeight",
    "markerUnits", "refX", "refY", "orient", "marker-start", "marker-mid", "marker-end",
    "font-family", "font-size", "font-weight", "font-style", "font-variant", "font-stretch", "letter-spacing",
    "word-spacing", "text-anchor", "dominant-baseline", "alignment-baseline", "baseline-shift",
    "text-decoration", "writing-mode", "direction", "unicode-bidi",
    "in", "in2", "result", "mode", "type", "values", "tableValues", "slope", "intercept", "amplitude",
    "exponent", "k1", "k2", "k3", "k4", "operator", "radius", "stdDeviation", "edgeMode", "kernelMatrix",
    "order", "divisor", "bias", "targetX", "targetY", "preserveAlpha", "kernelUnitLength", "surfaceScale",
    "diffuseConstant", "specularConstant", "specularExponent", "azimuth", "elevation", "pointsAtX",
    "pointsAtY", "pointsAtZ", "limitingConeAngle", "z", "scale", "xChannelSelector", "yChannelSelector",
    "baseFrequency", "numOctaves", "seed", "stitchTiles",
}

# url(...) may only point inside the document (url(#id)); nothing else that loads or runs code.
_BAD_CSS = re.compile(r"@import|expression\s*\(|javascript:|behavior\s*:|-moz-binding", re.I)
_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)


def _safe_css(value: str) -> bool:
    if _BAD_CSS.search(value):
        return False
    return all(m.group(2).strip().startswith("#") for m in _URL.finditer(value))


def _local(name: str) -> tuple[str, str]:
    """('{ns}local' or 'local') → (ns, local)."""
    if name.startswith("{"):
        ns, _, local = name[1:].partition("}")
        return ns, local
    return "", name


def sanitize_svg(data: bytes) -> tuple[bytes, tuple[float, float] | None]:
    """(clean SVG bytes, (width, height) or None). Raises LogoError if it isn't an SVG at all."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    head = data[:2048].lstrip()
    # No DTDs: they're how entity-expansion and external-entity attacks get in, and logos don't need them.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise LogoError("SVG files with a DOCTYPE or entities aren't allowed.")
    if not (head.startswith(b"<") and b"<svg" in data[:4096]):
        raise LogoError("Upload a PNG, SVG or JPG.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise LogoError("This SVG couldn't be read.") from None
    if root.tag != f"{{{SVG_NS}}}svg" and root.tag != "svg":
        raise LogoError("Upload a PNG, SVG or JPG.")

    out = _clean(root)
    out.set("xmlns", SVG_NS)
    if any(k == "xlink:href" for el in out.iter() for k in el.attrib):
        out.set("xmlns:xlink", XLINK_NS)
    body = ET.tostring(out, encoding="unicode", short_empty_elements=True)
    return body.encode("utf-8"), _svg_size(out)


def _clean(el: ET.Element) -> ET.Element:
    """A copy of `el` with only allowed elements and attributes, written without namespace prefixes."""
    _, tag = _local(el.tag)
    out = ET.Element(tag)
    for name, value in el.attrib.items():
        ns, attr = _local(name)
        if ns == XLINK_NS and attr == "href" or (ns == "" and attr == "href"):
            if value.strip().startswith("#"):
                out.set("xlink:href" if ns else "href", value.strip())
            continue
        if ns == XML_NS and attr == "space":
            out.set("xml:space", value)
            continue
        if ns or attr not in ALLOWED_ATTRIBUTES or attr.lower().startswith("on"):
            continue
        if not _safe_css(value):
            continue
        out.set(attr, value)
    if tag == "style":
        css = el.text or ""
        out.text = css if _safe_css(css) else ""
        return out
    out.text = el.text
    for child in el:
        ns, child_tag = _local(child.tag)
        if (ns in ("", SVG_NS)) and child_tag in ALLOWED_ELEMENTS:
            clean = _clean(child)
            clean.tail = child.tail
            out.append(clean)
    return out


_LENGTH = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$")


def _svg_size(svg: ET.Element):
    box = svg.get("viewBox")
    if box:
        parts = re.split(r"[\s,]+", box.strip())
        try:
            if len(parts) == 4:
                return float(parts[2]), float(parts[3])
        except ValueError:
            pass
    w, h = _LENGTH.match(svg.get("width", "")), _LENGTH.match(svg.get("height", ""))
    if w and h:
        return float(w.group(1)), float(h.group(1))
    return None
