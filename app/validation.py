import xml.etree.ElementTree as ET

ADEPT_NS = "http://ns.adobe.com/adept"


def is_valid_acsm(path: str) -> bool:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return False
    return root.tag == f"{{{ADEPT_NS}}}fulfillmentToken"
