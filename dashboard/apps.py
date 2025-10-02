from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'

    def ready(self):
        from .signals import denuncias  # ya lo tienes
        from .signals import permisos   # <-- agrega esta línea   
        