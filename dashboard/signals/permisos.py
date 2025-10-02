# dashboard/signals/permisos.py
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils import timezone
from datetime import date, datetime
from decimal import Decimal
import uuid
from dashboard.models import Permiso
from dashboard.utils.audit import log_permiso
from dashboard.middleware.current_user import get_current_user

def _to_jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    return v

def _snapshot(instance):
    data = model_to_dict(instance, fields=FIELDS_TO_TRACK)
    for k, v in list(data.items()):
        data[k] = _to_jsonable(v)
    return data

FIELDS_TO_TRACK = [
    "descripcion", "observaciones",
    "requiere_pmt", "requiere_conos",
    "estado", "visible_en_mapa",
    "tipo_permiso_id", "ubicacion_id", "usuario_id",
]

def _snapshot(instance):
    return model_to_dict(instance, fields=FIELDS_TO_TRACK)

@receiver(pre_save, sender=Permiso)
def pre_save_permiso(sender, instance, **kwargs):
    """
    1) Guarda snapshot previo.
    2) Si cambia a 'finalizada' y no tiene finalizado_en, lo fija (tu lógica original).
    """
    if instance.pk:
        prev = sender.objects.filter(pk=instance.pk).only("estado", "finalizado_en").first()
        if prev:
            instance.__audit_prev__ = _snapshot(prev)
            if prev.estado != instance.estado:
                if instance.estado == "finalizada" and not instance.finalizado_en:
                    instance.finalizado_en = timezone.now()
    else:
        instance.__audit_prev__ = None

@receiver(post_save, sender=Permiso)
def post_save_permiso(sender, instance, created, **kwargs):
    """
    1) Si es creación, registra bitácora 'Creación'.
    2) Si es actualización, calcula diff y lo registra.
    """
    usuario = get_current_user()

    if created:
        log_permiso(
            permiso=instance,
            usuario=usuario if usuario else instance.usuario,
            accion="Creación",
            estado_anterior="",
            estado_nuevo=instance.estado,
            cambios=_snapshot(instance),
            request=None,
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

    log_permiso(
        permiso=instance,
        usuario=usuario,
        accion="Actualización",
        estado_anterior=prev.get("estado", ""),
        estado_nuevo=now_data.get("estado", ""),
        cambios=diff,
        request=None,
    )
