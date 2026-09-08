"""Small input/output sanitizers shared by views, forms and the inline editor.

Kept deliberately dependency-free so they can run in migrations too.
"""


def safe_url(value):
    """Return ``value`` only if it is a plain ``http(s)`` link, else ``""``.

    A scheme-less value that looks like a host keeps working: ``https://`` is
    prepended. Anything with another scheme (``javascript:``, ``data:``,
    ``vbscript:``, ``file:`` …), a protocol-relative ``//`` prefix or an ASCII
    control character is rejected.
    """
    value = (value or "").strip()
    if not value or any(ch < " " or ch == "\x7f" for ch in value):
        return ""
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        return value
    head = value.split("/", 1)[0]
    if ":" in head or value.startswith("//"):
        return ""
    return "https://" + value


_CSV_INJECTION_LEADERS = ("=", "+", "-", "@", "\t", "\r", " ")


def csv_safe(value):
    """Neutralise spreadsheet formula injection: prefix a leading ``=+-@`` (or
    whitespace) with an apostrophe so the cell is read as text."""
    text = "" if value is None else str(value)
    if text[:1] in _CSV_INJECTION_LEADERS:
        return "'" + text
    return text
