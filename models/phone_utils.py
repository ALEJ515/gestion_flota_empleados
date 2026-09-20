import re


def whatsapp_url(phone):
    """Build a wa.me URL using a phone number in local or international format."""
    digits = re.sub(r'\D', '', str(phone or ''))
    if len(digits) == 10:
        digits = '1' + digits
    return f'https://wa.me/{digits}' if len(digits) >= 7 else False
