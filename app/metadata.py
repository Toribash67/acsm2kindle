import os
import zipfile
import xml.etree.ElementTree as ET

CONTAINER = "META-INF/container.xml"
DC = "http://purl.org/dc/elements/1.1/"
CN = "urn:oasis:names:tc:opendocument:xmlns:container"


def extract_metadata(epub_path: str) -> dict:
    stem = os.path.splitext(os.path.basename(epub_path))[0]
    try:
        with zipfile.ZipFile(epub_path) as z:
            container = ET.fromstring(z.read(CONTAINER))
            rootfile = container.find(f".//{{{CN}}}rootfile")
            opf_path = rootfile.get("full-path")
            opf = ET.fromstring(z.read(opf_path))
            title = opf.findtext(f".//{{{DC}}}title") or stem
            author = opf.findtext(f".//{{{DC}}}creator") or ""
            return {"title": title.strip(), "author": author.strip()}
    except Exception:
        return {"title": stem, "author": ""}
