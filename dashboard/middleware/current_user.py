# dashboard/middleware/current_user.py
import threading
_local = threading.local()

def set_current_user(user):
    _local.user = user

def get_current_user():
    return getattr(_local, "user", None)

class CurrentUserMiddleware:
    """
    Captura request.user en un threadlocal para usarlo en señales.
    Añade 'dashboard.middleware.current_user.CurrentUserMiddleware' al MIDDLEWARE.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_user(getattr(request, "user", None))
        try:
            response = self.get_response(request)
        finally:
            set_current_user(None)
        return response
