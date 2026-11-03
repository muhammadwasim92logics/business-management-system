from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from django import template

register = template.Library()

def _truncate_to_two_places(value):
    """Return a formatted two-place decimal string using standard rounding."""
    if value is None or value == '':
        return '0'
    try:
        d = Decimal(str(value))
        rounded = d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        formatted = format(rounded, 'f')
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted or '0'
    except (ValueError, TypeError, ArithmeticError):
        return str(value)

@register.filter
def compact_decimal(value, places=2):
    """Return a fixed two-place decimal display using standard rounding."""
    if value is None or value == '':
        return '0.00'
    try:
        decimal_places = Decimal(str(10 ** (-int(places))))
        d = Decimal(str(value))
        return format(d.quantize(decimal_places, rounding=ROUND_HALF_UP), 'f')
    except (ValueError, TypeError, ArithmeticError, IndexError):
        return str(value)

@register.filter
def truncate_decimal(value):
    """Return the value with only two fractional digits preserved."""
    return _truncate_to_two_places(value)

@register.filter
def precise_decimal(value):
    """Return the value with only two fractional digits preserved for FBR pages."""
    return _truncate_to_two_places(value)

@register.filter
def multiply(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def add(value, arg):
    """Add the argument to the value"""
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def gst_amount(value, rate=18.0):
    """Calculate GST amount"""
    try:
        return float(value) * (rate / 100)
    except (ValueError, TypeError):
        return 0

@register.filter
def total_with_gst(value, rate=18.0):
    """Calculate total with GST"""
    try:
        ex_value = float(value)
        gst = ex_value * (rate / 100)
        return ex_value + gst
    except (ValueError, TypeError):
        return 0

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key (safe access in templates)"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    return ''