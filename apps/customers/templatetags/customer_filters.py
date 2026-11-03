from decimal import Decimal, ROUND_HALF_UP
from django import template

register = template.Library()


def _to_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    return Decimal(str(value))


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a key"""
    if dictionary is None:
        return 0
    return dictionary.get(key, 0)


@register.filter
def compact_money(value):
    """Show only 2 decimal places while keeping the full value for the tooltip."""
    try:
        d = _to_decimal(value)
        return format(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')
    except Exception:
        return '0.00'


@register.filter
def exact_money(value):
    """Return the exact value without trimming trailing zeros."""
    try:
        d = _to_decimal(value)
        text = format(d, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return text or '0'
    except Exception:
        return '0'


@register.simple_tag
def money(value):
    """Render a 2-decimal amount with a tooltip containing the exact value."""
    exact = exact_money(value)
    compact = compact_money(value)
    return (
        '<span class="money-display" tabindex="0" role="button" '
        'data-full-value="PKR {}" data-bs-toggle="popover" data-bs-trigger="hover focus click" '
        'data-bs-placement="top" data-bs-content="Full value: PKR {}">'
        'PKR {}</span>'
    ).format(exact, exact, compact)
