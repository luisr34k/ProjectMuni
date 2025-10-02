# dashboard/signals/ubicaciones.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.forms.models import model_to_dict
from decimal import Decimal
from datetime import date, datetime
import uuid

from dashboard.models import Ubicacion, Denuncia, Permiso
from dashboard.utils.audit import log_denuncia, log_permiso
from dashboard.middleware.current_user import get_current_user

FIELDS = ["direccion", "barrio", "latitud", "longitud"]

def _to_jsonable(v):
    if isinstance(v, (date, datetime)): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, uuid.UUID): return str(v)
    return v

def _snap(u: Ubicacion):
    # tomamos 'barrio' pero devolvemos ambos: id y nombre
    return {
        "ubicacion_direccion": u.direccion or "",
        #"ubicacion_barrio_id": u.barrio_id if u.barrio_id else None,
        "ubicacion_barrio": (u.barrio.nombre if u.barrio_id else ""),
        "ubicacion_lat": _to_jsonable(u.latitud) if u.latitud is not None else None,
        "ubicacion_lng": _to_jsonable(u.longitud) if u.longitud is not None else None,
    }

@receiver(pre_save, sender=Ubicacion)
def ubicacion_pre(sender, instance: Ubicacion, **kwargs):
    if not instance.pk:
        instance.__prev__ = None
        return
    try:
        prev = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance.__prev__ = None
        return
    instance.__prev__ = _snap(prev)

@receiver(post_save, sender=Ubicacion)
def ubicacion_post(sender, instance: Ubicacion, created, **kwargs):
    prev = getattr(instance, "__prev__", None)
    if prev is None:
        return

    now = _snap(instance)
    diff = {}
    for k, old in prev.items():
        new = now.get(k)
        if old != new:
            diff[f"ubicacion_{k}"] = [old, new]

    if not diff:
        return

    user = get_current_user()

    for d in Denuncia.objects.filter(ubicacion=instance).only("id", "estado"):
        log_denuncia(
            denuncia=d,
            usuario=user,
            accion="Actualización",
            estado_anterior=d.estado,
            estado_nuevo=d.estado,
            cambios=diff,
            request=None,
        )

    for p in Permiso.objects.filter(ubicacion=instance).only("id", "estado"):
        log_permiso(
            permiso=p,
            usuario=user,
            accion="Actualización",
            estado_anterior=p.estado,
            estado_nuevo=p.estado,
            cambios=diff,
            request=None,
        )
