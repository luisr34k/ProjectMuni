# dashboard/utils/email_utils.py
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string

def _user_email(u):
    if not u:
        return ""
    # Soporta ambos campos
    return getattr(u, "email", "") or getattr(u, "correo", "")

def _send(to_email: str, subject: str, template_name: str, ctx: dict):
    body = render_to_string(template_name, ctx)  # templates/emails/*.txt
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
        fail_silently=False,
    )

def notify_denuncia_creada(denuncia):
    to = _user_email(getattr(denuncia, "usuario", None))
    if not to:
        return
    ctx = {
        "nombre": getattr(denuncia.usuario, "nombre", "") or denuncia.usuario.get_username(),
        "id": denuncia.id,
        "categoria": getattr(getattr(denuncia, "categoria", None), "nombre", ""),
        "fecha": getattr(denuncia, "creada_en", ""),
        "estado": getattr(denuncia, "estado", ""),
        "descripcion": (getattr(denuncia, "descripcion", "") or "")[:200],
    }
    _send(
        to_email=to,
        subject=f"Tu denuncia #{denuncia.id} fue recibida",
        template_name="emails/denuncia_creada.txt",
        ctx=ctx,
    )

def notify_estado_cambio(denuncia, estado_anterior: str, estado_nuevo: str):
    to = _user_email(getattr(denuncia, "usuario", None))
    if not to:
        return
    ctx = {
        "nombre": getattr(denuncia.usuario, "nombre", "") or denuncia.usuario.get_username(),
        "id": denuncia.id,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "categoria": getattr(getattr(denuncia, "categoria", None), "nombre", ""),
        "rechazo_motivo": (getattr(denuncia, "rechazo_motivo", "") or "").strip(),
    }
    _send(
        to_email=to,
        subject=f"Actualización de denuncia #{denuncia.id}: {estado_nuevo}",
        template_name="emails/denuncia_estado.txt",
        ctx=ctx,
    )

def notify_permiso_estado(permiso, estado_anterior: str, estado_nuevo: str):
    to = _user_email(getattr(permiso, "usuario", None))
    if not to:
        return

    adjunto_url = ""
    f = getattr(permiso, "permiso_adjunto", None)
    if f and getattr(f, "name", ""):
        try:
            adjunto_url = f.url
        except Exception:
            adjunto_url = ""

    ctx = {
        "nombre": getattr(permiso.usuario, "nombre", "") or permiso.usuario.get_username(),
        "id": permiso.id,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "tipo": getattr(getattr(permiso, "tipo_permiso", None), "nombre", ""),
        "nota": (getattr(permiso, "aceptacion_nota", "") or "").strip(),
        "observaciones": (getattr(permiso, "observaciones", "") or "").strip(),
        "adjunto_url": adjunto_url,
    }
    _send(
        to_email=to,
        subject=f"Actualización de permiso #{permiso.id}: {estado_nuevo}",
        template_name="emails/permiso_estado.txt",
        ctx=ctx,
    )

def send_receipt_email(pago) -> bool:
    user = getattr(getattr(pago, "cuenta", None), "usuario", None)
    to = _user_email(user)
    if not to:
        return False

    cuenta = pago.cuenta
    ctx = {
        "pago": pago,
        "cuenta": cuenta,
        "municipalidad": "Municipalidad de San Luis",
        "from_email": settings.DEFAULT_FROM_EMAIL,
        "nit": getattr(cuenta, "nit", ""),
        "titular": getattr(cuenta, "titular", ""),
        "codigo_catastral": getattr(cuenta, "codigo_catastral", ""),
        "referencia": getattr(pago, "referencia", f"pa_{pago.pk}"),
    }

    subject = f"Recibo de pago #{pago.pk} — Tren de Aseo"
    text_body = render_to_string("emails/recibo_pago.txt", ctx)
    html_body = render_to_string("emails/recibo_pago.html", ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        headers={"Reply-To": settings.DEFAULT_FROM_EMAIL},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)
    return True
