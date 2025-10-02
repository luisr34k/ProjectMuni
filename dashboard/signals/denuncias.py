# dashboard/signals/denuncias.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils import timezone
from datetime import date, datetime
from decimal import Decimal
import uuid
from dashboard.models import Denuncia
from dashboard.utils.audit import log_denuncia
from dashboard.middleware.current_user import get_current_user


def _to_jsonable(v):
    if isinstance(v, (date, datetime)): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, uuid.UUID): return str(v)
    return v

def _file_marker(f):
    if not f:
        return ""
    # puedes devolver solo nombre o "presente"
    return getattr(f, "name", "presente")

def _ubi_snapshot(u):
    if not u:
        return {
            "ubicacion_direccion": "",
            "ubicacion_barrio_id": None,
            "ubicacion_lat": None,
            "ubicacion_lng": None,
        }
    return {
        "ubicacion_direccion": u.direccion or "",
        "ubicacion_barrio_id": u.barrio_id if u.barrio_id else None,
        "ubicacion_lat": _to_jsonable(u.latitud) if u.latitud is not None else None,
        "ubicacion_lng": _to_jsonable(u.longitud) if u.longitud is not None else None,
    }

# ❗️Actualiza los campos que trackeamos
FIELDS_TO_TRACK = [
    "categoria",          # ← antes tenías categoria_id
    "descripcion",
    "fecha_hecho",
    "es_anonima",
    "estado",
    "rechazo_motivo",
    "resolucion_nota",
    "resolucion_evidencia",
    "evidencia",
    "resuelto_por",       # ← si antes tenías resuelto_por_id
]

def _snapshot(instance):
    data = model_to_dict(instance, fields=[
        "categoria", "descripcion", "fecha_hecho", "es_anonima",
        "estado", "rechazo_motivo", "resolucion_nota",
        "resolucion_evidencia", "evidencia", "resuelto_por",
    ])

    # ---- archivos a marcador legible ----
    data["evidencia"] = _file_marker(getattr(instance, "evidencia", None))
    data["resolucion_evidencia"] = _file_marker(getattr(instance, "resolucion_evidencia", None))

    # ---- categoría como NOMBRE (no ID) ----
    data["categoria"] = instance.categoria.nombre if instance.categoria_id else ""

    # ---- aplanar ubicación (igual que ya lo tienes) ----
    data.update(_ubi_snapshot(instance.ubicacion))

    # ---- JSON-safe ----
    for k, v in list(data.items()):
        data[k] = _to_jsonable(v)
    return data

@receiver(pre_save, sender=Denuncia)
def pre_save_denuncia(sender, instance, **kwargs):
    """
    1) Guarda un snapshot previo para comparar en post_save.
    2) Si cambia a 'resuelta' y no tiene finalizada_en, la fija (tu lógica original).
    """
    if instance.pk:
        prev = sender.objects.filter(pk=instance.pk).only("estado", "finalizada_en").first()
        if prev:
            instance.__audit_prev__ = _snapshot(prev)
            if prev.estado != instance.estado:
                if instance.estado == "resuelta" and not instance.finalizada_en:
                    instance.finalizada_en = timezone.now()
    else:
        instance.__audit_prev__ = None

@receiver(post_save, sender=Denuncia)
def post_save_denuncia(sender, instance, created, **kwargs):
    """
    1) Si es creación, registra bitácora 'Creación' enriquecida.
    2) Si es actualización, calcula diff y lo registra (si hay cambios).
    """
    usuario = get_current_user()

    if created:
        log_denuncia(
            denuncia=instance,
            usuario=usuario if usuario else instance.usuario,  # tu lógica original: asociar al creador si hay
            accion="Creación",
            estado_anterior="",
            estado_nuevo=instance.estado,
            cambios=_snapshot(instance),  # si prefieres, pásalo vacío {}
            request=None,  # señales no tienen request
        )
        return

    prev = getattr(instance, "__audit_prev__", None)
    if prev is None:
        return

    now_data = _snapshot(instance)
    diff = {}
    for k, old_val in prev.items():
        new_val = now_data.get(k)
        if old_val != new_val:
            diff[k] = [old_val, new_val]

    if not diff:
        return

    log_denuncia(
        denuncia=instance,
        usuario=usuario,
        accion="Actualización",
        estado_anterior=prev.get("estado", ""),
        estado_nuevo=now_data.get("estado", ""),
        cambios=diff,
        request=None,
    )
