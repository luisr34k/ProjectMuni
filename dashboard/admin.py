# admin
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from dashboard.models import Pago
from django.http import HttpResponse
import csv
from dashboard.utils.email_utils import send_receipt_email
from dashboard.models import CuentaServicio, Tarifa, Periodo, Boleta, Pago, AplicacionPago, TransaccionOnline
from django.contrib.auth.admin import UserAdmin
from .models import (
    Usuario, Barrio, Ubicacion, CategoriaDenuncia,
    Denuncia, BitacoraDenuncia,
    TipoPermiso, Permiso, BitacoraPermiso
)

# ---- Usuario ----
class UsuarioAdmin(UserAdmin):
    model = Usuario
    list_display = ('correo', 'nombre', 'apellido', 'tipo_usuario', 'es_activo', 'is_staff', 'creado_en')
    list_filter  = ('tipo_usuario', 'es_activo', 'is_staff')
    readonly_fields = ('creado_en', 'last_login', 'token_activacion', 'token_creado_en')
    fieldsets = (
        (None, {'fields': ('correo', 'password')}),
        ('Información personal', {'fields': ('nombre', 'apellido', 'telefono', 'tipo_usuario')}),
        ('Permisos', {'fields': ('is_staff', 'is_superuser', 'es_activo', 'groups', 'user_permissions')}),
        ('Fechas importantes', {'fields': ('last_login', 'creado_en')}),
        ('Activación', {'fields': ('token_activacion', 'token_creado_en')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',),
                'fields': ('correo', 'nombre', 'apellido', 'telefono', 'tipo_usuario',
                           'password1', 'password2', 'es_activo', 'is_staff')}),
    )
    search_fields = ('correo', 'nombre', 'apellido')
    ordering = ('correo',)

admin.site.register(Usuario, UsuarioAdmin)

# ---- Bitácora Denuncia (Admin y Inline) ----
class BitacoraDenunciaInline(admin.TabularInline):
    model = BitacoraDenuncia
    extra = 0
    readonly_fields = ('usuario', 'accion', 'fecha')
    can_delete = False

@admin.register(BitacoraDenuncia)
class BitacoraDenunciaAdmin(admin.ModelAdmin):
    list_display = ('id', 'denuncia', 'usuario', 'accion', 'fecha')
    list_filter = ('fecha', 'accion')
    search_fields = ('accion', 'denuncia__id', 'usuario__correo')
    date_hierarchy = 'fecha'
    ordering = ('-fecha',)

# ---- Denuncia ----
@admin.register(Denuncia)
class DenunciaAdmin(admin.ModelAdmin):
    list_display = ('id', 'categoria', 'usuario', 'estado', 'creada_en', 'finalizada_en', 'es_anonima')
    list_filter  = ('estado', 'es_anonima', 'categoria', 'creada_en')
    search_fields = ('descripcion', 'ubicacion__direccion', 'usuario__correo')
    date_hierarchy = 'creada_en'
    readonly_fields = ('creada_en', 'finalizada_en')
    fieldsets = (
        ('Datos', {
            'fields': ('usuario', 'categoria', 'descripcion', 'fecha_hecho', 'es_anonima', 'estado')
        }),
        ('Ubicación', {
            'fields': ('ubicacion',)
        }),
        ('Archivos', {
            'fields': ('evidencia',)
        }),
        ('Tiempos', {
            'fields': ('creada_en', 'finalizada_en')
        }),
    )
    inlines = [BitacoraDenunciaInline]

# ---- Catálogos básicos ----
admin.site.register(Barrio)
admin.site.register(Ubicacion)
admin.site.register(CategoriaDenuncia)

# ---- Permisos ----
@admin.register(TipoPermiso)
class TipoPermisoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)

@admin.register(BitacoraPermiso)
class BitacoraPermisoAdmin(admin.ModelAdmin):
    list_display = ('id', 'permiso', 'usuario', 'accion', 'fecha')
    list_filter = ('fecha',)
    search_fields = ('accion', 'permiso__id', 'usuario__correo')

@admin.register(Permiso)
class PermisoAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'tipo_permiso', 'usuario', 'estado',
        'requiere_pmt', 'requiere_conos',
        'creado_en', 'finalizado_en',
    )
    list_filter = ('estado', 'tipo_permiso', 'requiere_pmt', 'requiere_conos', 'visible_en_mapa')
    search_fields = ('descripcion', 'usuario__correo', 'ubicacion__direccion')
    date_hierarchy = 'creado_en'
    readonly_fields = ('creado_en', 'finalizado_en')

@admin.register(CuentaServicio)
class CuentaServicioAdmin(admin.ModelAdmin):
    list_display = ("id", "titular", "usuario", "activa", "codigo_catastral")
    search_fields = ("titular", "codigo_catastral")
    list_filter = ("activa",)

@admin.register(Periodo)
class PeriodoAdmin(admin.ModelAdmin):
    list_display = ("id", "anio", "mes", "vencimiento")
    list_filter = ("anio", "mes")

@admin.register(Tarifa)
class TarifaAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "monto_base", "recargo_mora_porcentaje", "vigente_desde", "vigente_hasta")
    list_filter = ("vigente_desde",)

@admin.register(Boleta)
class BoletaAdmin(admin.ModelAdmin):
    list_display = ("id", "cuenta", "periodo", "estado", "saldo_actual", "total", "creada_en")
    list_filter = ("estado", "periodo__anio", "periodo__mes")
    search_fields = ("cuenta__titular", "cuenta__codigo_catastral")

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("id", "cuenta", "monto", "metodo", "referencia", "fecha")
    actions = ["reenviar_recibo"]

    @admin.action(description="Reenviar recibo al contribuyente")
    def reenviar_recibo(self, request, queryset):
        ok = 0
        for pago in queryset:
            try:
                if send_receipt_email(pago):
                    ok += 1
            except Exception:
                pass
        messages.success(request, f"Recibo reenviado en {ok} pago(s).")

@admin.register(AplicacionPago)
class AplicacionPagoAdmin(admin.ModelAdmin):
    list_display = ("id", "pago", "boleta", "monto_aplicado")

@admin.register(TransaccionOnline)
class TransaccionOnlineAdmin(admin.ModelAdmin):
    list_display = ("id", "gateway", "orden_id", "estado", "creado_en")
    list_filter = ("estado",)
    search_fields = ("orden_id",)


@staff_member_required
def export_pagos_admin_csv(request):
    qs = (Pago.objects
          .select_related("cuenta", "cuenta__usuario")
          .order_by("-id"))

    # filtros admin (usuario, cuenta, estado, fechas… según tu modelo)
    # eje: ?usuario=mail&cuenta_id=1&fecha_ini=...&fecha_fin=...
    # Aplica similar a mis_pagos_csv

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="pagos_admin.csv"'
    w = csv.writer(resp)
    w.writerow(["ID","Fecha","Cuenta","Titular","Usuario","Método","Referencia","Monto (Q)"])
    for p in qs:
        cuenta = getattr(p, "cuenta", None)
        titular = getattr(cuenta, "titular", "") if cuenta else ""
        usuario = getattr(getattr(cuenta, "usuario", None), "email", "")
        fecha_val = getattr(p, "fecha", None) or getattr(p, "creado_en", "")
        w.writerow([p.id, fecha_val, cuenta, titular, usuario, p.metodo, p.referencia, p.monto])
    return resp