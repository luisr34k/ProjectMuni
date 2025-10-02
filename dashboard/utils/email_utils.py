# dashboard/utils/email_utils.py
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings


def _send(to_email: str, subject: str, template_name: str, ctx: dict):
    """
    Renderiza un template de email y lo envía en texto plano.
    Si luego quieres HTML, añade html_message.
    """
    body = render_to_string(template_name, ctx)  # templates/emails/*.txt
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
        fail_silently=False,
    )

def notify_denuncia_creada(denuncia):
    """
    Enviar confirmación al ciudadano cuando crea la denuncia.
    No se envía si es anónima (usuario == None).
    """
    if not denuncia.usuario or not denuncia.usuario.correo:
        return

    ctx = {
        "nombre": denuncia.usuario.nombre or denuncia.usuario.get_username(),
        "id": denuncia.id,
        "categoria": getattr(denuncia.categoria, "nombre", ""),
        "fecha": denuncia.creada_en,
        "estado": denuncia.estado,
        "descripcion": denuncia.descripcion[:200],
    }
    _send(
        to_email=denuncia.usuario.correo,
        subject=f"Tu denuncia #{denuncia.id} fue recibida",
        template_name="emails/denuncia_creada.txt",
        ctx=ctx,
    )

def notify_estado_cambio(denuncia, estado_anterior: str, estado_nuevo: str):
    if not denuncia.usuario or not denuncia.usuario.correo:
        return

    ctx = {
        "nombre": denuncia.usuario.nombre or denuncia.usuario.get_username(),
        "id": denuncia.id,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "categoria": getattr(denuncia.categoria, "nombre", ""),
        "rechazo_motivo": (denuncia.rechazo_motivo or "").strip(),
    }
    _send(
        to_email=denuncia.usuario.correo,
        subject=f"Actualización de denuncia #{denuncia.id}: {estado_nuevo}",
        template_name="emails/denuncia_estado.txt",
        ctx=ctx,
    )
    
def notify_permiso_estado(permiso, estado_anterior: str, estado_nuevo: str):
    if not permiso.usuario or not permiso.usuario.correo:
        return

    # --- obtener URL del adjunto de forma segura ---
    adjunto_url = ""
    f = getattr(permiso, "permiso_adjunto", None)
    # El FileField "es falsy" si no hay archivo; además comprobamos name
    if f and getattr(f, "name", ""):
        try:
            adjunto_url = f.url
        except Exception:
            adjunto_url = ""

    ctx = {
        "nombre": permiso.usuario.nombre or permiso.usuario.get_username(),
        "id": permiso.id,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "tipo": getattr(permiso.tipo_permiso, "nombre", ""),
        "nota": (permiso.aceptacion_nota or "").strip(),
        "observaciones": (permiso.observaciones or "").strip(),
        "adjunto_url": adjunto_url,
    }

    _send(
        to_email=permiso.usuario.correo,
        subject=f"Actualización de permiso #{permiso.id}: {estado_nuevo}",
        template_name="emails/permiso_estado.txt",
        ctx=ctx,
    )
