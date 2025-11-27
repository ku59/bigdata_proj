import html
import re
import hashlib
from datetime import datetime, timezone, timedelta

TAG_RE = re.compile(r"<[^>]+>")

def clean_html(text: str) -> str:
    text = html.unescape(text)
    text = TAG_RE.sub("", text)
    return text.strip()

def make_doc_id(link: str, pubdate: str) -> str:
    key = f"{link}|{pubdate}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def parse_pubdate(raw: str):
    try:
        dt = datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %z")
        return dt.astimezone(timezone(timedelta(hours=9))).isoformat()
    except Exception:
        return None
