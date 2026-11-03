from django import template

register = template.Library()

@register.filter
def sum_attribute(queryset, attribute):
    """
    Sum a specific attribute across a queryset or list of dictionaries.
    Usage: {{ product_summary|sum_attribute:'total_kg' }}
    """
    total = 0
    try:
        for item in queryset:
            # Handle both dictionary and object access
            if isinstance(item, dict):
                value = item.get(attribute, 0)
            else:
                value = getattr(item, attribute, 0)
            
            # Convert to float if possible
            try:
                total += float(value)
            except (ValueError, TypeError):
                pass
    except (TypeError, AttributeError):
        pass
    
    return total