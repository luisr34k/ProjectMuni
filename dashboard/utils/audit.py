# dashboard/utils/audit.py
from typing import Optional, Dict, Any
from datetime import date, datetime
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
import uuid

def _actor_from_user(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return "sistema"
    if getattr(user, "is_staff", False) or getattr(user, "tipo_usuario", "") == "administrador":
        return "administrador"
    return "ciudadano"

def _client_info(request) -> tuple[str, str]:
    if request is None:
        return "", ""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "")
    ua = request.META.get("HTTP_USER_AGENT", "")
    return ip or "", ua or ""

# --- NUEVO: sanitizador JSON-safe, recursivo ---
def _to_jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    # Maneja listas/tuplas/dicts recursivamente
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_jsonable(val) for k, val in v.items()}
    # Como último recurso, fuerza a str si es un tipo raro
    try:
        # Evita romper con objetos Django (Model, QuerySet) o similares
        from django.db.models import Model, QuerySet
        if isinstance(v, Model):
            return getattr(v, "pk", str(v))
        if isinstance(v, QuerySet):
            return [_to_jsonable(x) for x in v]
    except Exception:
        pass
    return v

def _jsonify_changes(cambios: Optional[Dict[str, Any]]):
    """
    Acepta:
      - dict normal
      - dict con pares [antes, despues]
    Devuelve un dict 100% JSON-safe.
    """
    if not cambios:
        return {}
    out = {}
    for k, v in cambios.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            out[str(k)] = [_to_jsonable(v[0]), _to_jsonable(v[1])]
        else:
            out[str(k)] = _to_jsonable(v)
    return out
# --- FIN sanitizador ---

def _merge_cambios(base: dict, extra: dict) -> dict:
    """
    Fusiona dicts de cambios {campo: [antes, después]}.
    Si ya existe el campo en base, intenta encadenar el 'después' con el nuevo 'después'.
    Si no calza, se sobreescribe por simplicidad (último gana).
    """
    if not base:
        base = {}
    base = dict(base)  # copia
    for k, v in (extra or {}).items():
        if k in base:
            try:
                old_before, old_after = base[k]
                new_before, new_after = v
                # Si el 'antes' nuevo coincide con el 'después' viejo, sólo extiende el final.
                if old_after == new_before:
                    base[k] = [old_before, new_after]
                else:
                    # No encadena limpio: quédate con el último (simple y robusto)
                    base[k] = v
            except Exception:
                base[k] = v
        else:
            base[k] = v
    return base

def _find_recent_bitacora_denuncia(denuncia, usuario, accion="Actualización", seconds=5):
    from dashboard.models import BitacoraDenuncia
    cutoff = timezone.now() - timedelta(seconds=seconds)
    qs = BitacoraDenuncia.objects.filter(
        denuncia=denuncia,
        accion=accion,
        fecha__gte=cutoff,
    )
    # Si quieres acotar también por usuario/actor, descomenta:
    if getattr(usuario, "is_authenticated", False):
        qs = qs.filter(usuario=usuario)
    return qs.order_by("-fecha").first()

def log_denuncia(*, denuncia, usuario=None, accion:str,
                 estado_anterior:str="", estado_nuevo:str="",
                 cambios: Optional[Dict[str, Any]] = None,
                 request=None):
    from dashboard.models import BitacoraDenuncia
    actor = _actor_from_user(usuario)
    ip, ua = _client_info(request)
    cambios = _jsonify_changes(cambios)

    # 💡 Intenta fusionar con una bitácora "reciente" del mismo tipo
    merge_target = None
    if accion == "Actualización":
        merge_target = _find_recent_bitacora_denuncia(denuncia, usuario, "Actualización", seconds=5)

    if merge_target:
        # Fusiona cambios y actualiza estado_nuevo (conserva el estado_anterior original)
        merged = _merge_cambios(merge_target.cambios or {}, cambios)
        merge_target.cambios = merged
        merge_target.estado_nuevo = estado_nuevo or merge_target.estado_nuevo
        # opcional: refresca ip/ua por última acción
        if ip: merge_target.ip = ip
        if ua: merge_target.user_agent = ua
        merge_target.save(update_fields=["cambios", "estado_nuevo", "ip", "user_agent"])
        return

    # Si no hay reciente, crea una nueva
    BitacoraDenuncia.objects.create(
        denuncia=denuncia,
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        accion=(accion or "")[:1000],
        estado_anterior=estado_anterior or "",
        estado_nuevo=estado_nuevo or "",
        cambios=cambios,
        actor=actor,
        ip=ip,
        user_agent=ua,
    )

# ===== Lo mismo para permisos =====

def _find_recent_bitacora_permiso(permiso, usuario, accion="Actualización", seconds=5):
    from dashboard.models import BitacoraPermiso
    cutoff = timezone.now() - timedelta(seconds=seconds)
    qs = BitacoraPermiso.objects.filter(
        permiso=permiso,
        accion=accion,
        fecha__gte=cutoff,
    )
    if getattr(usuario, "is_authenticated", False):
        qs = qs.filter(usuario=usuario)
    return qs.order_by("-fecha").first()

def log_permiso(*, permiso, usuario=None, accion:str,
                estado_anterior:str="", estado_nuevo:str="",
                cambios: Optional[Dict[str, Any]] = None,
                request=None):
    from dashboard.models import BitacoraPermiso
    actor = _actor_from_user(usuario)
    ip, ua = _client_info(request)
    cambios = _jsonify_changes(cambios)

    merge_target = None
    if accion == "Actualización":
        merge_target = _find_recent_bitacora_permiso(permiso, usuario, "Actualización", seconds=5)

    if merge_target:
        merged = _merge_cambios(merge_target.cambios or {}, cambios)
        merge_target.cambios = merged
        merge_target.estado_nuevo = estado_nuevo or merge_target.estado_nuevo
        if ip: merge_target.ip = ip
        if ua: merge_target.user_agent = ua
        merge_target.save(update_fields=["cambios", "estado_nuevo", "ip", "user_agent"])
        return

    BitacoraPermiso.objects.create(
        permiso=permiso,
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        accion=(accion or "")[:1000],
        estado_anterior=estado_anterior or "",
        estado_nuevo=estado_nuevo or "",
        cambios=cambios,
        actor=actor,
        ip=ip,
        user_agent=ua,
    )