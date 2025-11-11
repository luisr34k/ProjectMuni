# dashboard/urls.py
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from dashboard.views import payments as pay_views
from dashboard.views import auth, user, admin_panel
from dashboard.views import payments as pay_views

urlpatterns = [
    path('', auth.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('register/', auth.register, name='register'),
    path('activar/<uuid:token>/', auth.activar_cuenta, name='activar_cuenta'),

    # Home usuario
    path('index/', user.index, name='index'),
    path('mapa/', user.mapa_publico, name='mapa_publico'),

    # --- Admin panel denuncias ---
    path('admin-panel/', admin_panel.index, name='admin_panel'),
    path('admin-panel/denuncias/', admin_panel.denuncias, name='admin_denuncias'),
    path('admin-panel/denuncias/<int:pk>/', admin_panel.denuncia_detalle, name='admin_denuncia_detalle'),
    path('admin-panel/denuncias/<int:pk>/estado/', admin_panel.cambiar_estado, name='admin_cambiar_estado'),
    # --- Admin panel permisos ---
    path('admin-panel/permisos/', admin_panel.permisos, name='admin_permisos'),
    path('admin-panel/permisos/<int:pk>/', admin_panel.permiso_detalle, name='admin_permiso_detalle'),
    path('admin-panel/permisos/<int:pk>/estado/', admin_panel.permiso_cambiar_estado, name='admin_permiso_cambiar_estado'),
    

    # Denuncias (lado usuario)
    path('denuncias/form-denuncias/', user.denuncias_view, name='form_denuncias'),
    path('denuncias/<int:pk>/editar/', user.editar_denuncia, name='editar_denuncia'),
    path('denuncias/crear/', user.crear_denuncia, name='crear_denuncia'),
    path('denuncias/mias/', user.mis_denuncias, name='mis_denuncias'),
    path('denuncias/<int:pk>/', user.detalle_denuncia, name='detalle_denuncia'),

    # API pública
    path('api/denuncias-publicas/', user.denuncias_publicas_json, name='api_denuncias_publicas'),
    
    # Permisos (lado usuario)
    path('permisos/form-permisos/', user.permisos_view, name='form_permisos'),  # GET
    path("permisos/<int:pk>/editar/", user.editar_permiso, name="permiso_editar"),
    path("permisos/crear/", user.crear_permiso, name="permiso_crear"),          # POST
    path('permisos/mios/', user.mis_permisos, name='mis_permisos'),
    path("permisos/<int:pk>/", user.permiso_detalle, name="permiso_detalle"),
    
        # Recurrente
    path('pagos/', pay_views.pagos_home, name='pagos_home'),
    path("pagos/vincular/", pay_views.vincular_cuenta, name="vincular_cuenta"),
    path('pagos/online/<int:cuenta_id>/crear/', pay_views.crear_pago_online, name='crear_pago_online'),
    path('pagos/recurrente/webhook/', pay_views.recurrente_webhook, name='rec_webhook'),
    path('pagos/recurrente/success/', pay_views.recurrente_success, name='rec_success'),
    path('pagos/recurrente/cancel/', pay_views.recurrente_cancel, name='rec_cancel'),
    path("pagos/<int:pago_id>/recibo/", pay_views.recibo_pago_view, name="recibo_pago"),
    path("pagos/<int:pago_id>/recibo.pdf", pay_views.recibo_pago_pdf, name="recibo_pago_pdf"),
    path("mis-pagos/", pay_views.mis_pagos, name="mis_pagos"),
    path("mis-pagos/export.csv", pay_views.mis_pagos_csv, name="mis_pagos_csv"),
    path("admin-panel/pagos/", pay_views.admin_pagos, name="admin_pagos"),
    path("admin-panel/pagos/export.csv", pay_views.admin_pagos_export_csv, name="admin_pagos_export_csv"),
    path("admin-panel/pagos/<int:pk>/", pay_views.admin_pago_detalle, name="admin_pago_detalle"),
    path("admin-panel/pagos/<int:pk>/reenviar-recibo/", pay_views.admin_pago_reenviar_recibo, name="admin_pago_reenviar_recibo"),
    path('admin-panel/cartera/', pay_views.admin_cartera, name='admin_cartera'),
    path('admin-panel/cartera/enviar/', pay_views.admin_cartera_enviar, name='admin_cartera_enviar'),
    path("admin-panel/pagos/auditoria/", admin_panel.admin_pagos_auditoria, name="admin_pagos_auditoria"),
    path("admin-panel/denuncias/analitica/", admin_panel.admin_denuncias_analitica, name="admin_denuncias_analitica"),

    
    # dashboard/urls.py
    path('pagos/recurrente/dev-simular-success/',     pay_views.recurrente_dev_simular_success,     name='rec_dev_simular_success'),
    path('pagos/recurrente/dev-simular-success-get/', pay_views.recurrente_dev_simular_success_get, name='rec_dev_simular_success_get'),

]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

