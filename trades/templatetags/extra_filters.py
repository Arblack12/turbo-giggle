# trades/templatetags/extra_filters.py
from django import template

register = template.Library()

@register.filter
def blank_zero(value):
    """
    Returns an empty string if the numeric value is 0.0; otherwise returns the original value.
    """
    try:
        if float(value) == 0.0:
            return ""
    except (ValueError, TypeError):
        pass
    return value
