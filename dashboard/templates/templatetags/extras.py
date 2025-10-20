# dashboard/templatetags/extras.py
from django import template
register = template.Library()

@register.filter
def attr(obj, name):
    try:
        return getattr(obj, name, "")
    except Exception:
        return ""

@register.filter
def get_item(d, key):
    try:
        return d.get(key, "")
    except Exception:
        return ""