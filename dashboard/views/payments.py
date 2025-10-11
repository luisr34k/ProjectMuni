# dashboard/views/payments.py

# 1. Librerías estándar de Python
import json
import os
import logging
from datetime import date
from decimal import Decimal
from decimal import ROUND_HALF_UP
import csv
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

# 2. Librerías de terceros (Django y otras)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import (
    JsonResponse, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from svix.webhooks import Webhook
from django.template.loader import render_to_string
from django.contrib.admin.views.decorators import staff_member_required

# 3. Módulos de la aplicación
from dashboard.forms import VincularCuentaForm
from dashboard.models import CuentaServicio, Boleta, Pago, TransaccionOnline
from dashboard.utils import recurrente as rec
from dashboard.utils.billing import ensure_boletas_pendientes
from dashboard.utils.email_utils import send_receipt_email
from dashboard.utils.email_utils import _user_email

try:
    # ya lo tienes en admin: /admin/dashboard/aplicacionpago/
    from dashboard.models import AplicacionPago
except Exception:
    AplicacionPago = None

log = logging.getLogger(__name__)
FEE_RATE  = Decimal("0.045")   # 4.5 %
FEE_FIXED = Decimal("2.00")    # Q2 fijo por transacción

def crear_pago_online(request, cuenta_id):
    cuenta = get_object_or_404(CuentaServicio, pk=cuenta_id)

    boletas = Boleta.objects.filter(
        cuenta=cuenta, estado__in=["pendiente", "parcial"]
    ).select_related("periodo")

    total_neto = sum(b.saldo_actual for b in boletas).quantize(Decimal("0.01"))
    if total_neto <= 0:
        return HttpResponseBadRequest("No hay saldo por pagar.")

    # Inflar el total una sola vez
    total_bruto = (total_neto + FEE_FIXED) / (Decimal("1.00") - FEE_RATE)
    total_bruto = total_bruto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cents = int((total_bruto * 100).quantize(Decimal('1')))

    # Un solo ítem en Recurrente
    items = [{
        "name": f"Pago tren de aseo ({len(boletas)} meses)",
        "currency": "GTQ",
        "amount_in_cents": cents,
        "quantity": 1
    }]

    # Crear Pago interno
    pago = Pago.objects.create(
        cuenta=cuenta,
        metodo='online',
        monto=total_neto,
        observaciones='Pago iniciado en checkout Recurrente',
        usuario_registra=request.user if request.user.is_authenticated else None,
    )

    success_url = request.build_absolute_uri(reverse("rec_success"))
    cancel_url  = request.build_absolute_uri(reverse("rec_cancel"))

    chk = rec.create_checkout(
        items=items,
        success_url=success_url,
        cancel_url=cancel_url,
        user_id=str(cuenta.usuario_id) if cuenta.usuario_id else None,
        metadata={"pago_id": pago.pk, "cuenta_id": cuenta.pk}
    )

    return HttpResponseRedirect(chk["checkout_url"])

def recurrente_success(request):
    # Pantalla simple de "gracias" (el cierre real lo hace el webhook)
    return HttpResponse("Gracias. Si el pago fue exitoso, se verá reflejado en unos momentos.")

def recurrente_cancel(request):
    return HttpResponse("Has cancelado el pago. No se realizó ningún cargo.")

@login_required(login_url="login")
def pagos_home(request):
    cuenta = CuentaServicio.objects.filter(usuario=request.user, activa=True).first()
    if not cuenta:
        messages.info(request, "Aún no tienes una cuenta de Tren de Aseo vinculada.")
        return render(request, "pagos/home.html", {"cuenta": None, "boletas": [], "total": 0})

    # genera boletas desde enero del año actual hasta el mes actual
    hoy = date.today()
    desde = date(hoy.year, 1, 1)
    ensure_boletas_pendientes(cuenta, desde, hoy)

    boletas = (Boleta.objects
               .filter(cuenta=cuenta, estado__in=["pendiente", "parcial"])
               .select_related("periodo")
               .order_by("periodo__anio", "periodo__mes"))
    total = sum(b.saldo_actual for b in boletas)

    return render(request, "pagos/home.html", {
        "cuenta": cuenta,
        "boletas": boletas,
        "total": total,
        "checkout_url": reverse("crear_pago_online", args=[cuenta.id]) if total > 0 else None,
    })

@login_required(login_url='login')
def vincular_cuenta(request):
    if request.method == "POST":
        form = VincularCuentaForm(request.POST)
        if form.is_valid():
            nit = form.cleaned_data["nit"].strip()
            cat = form.cleaned_data["codigo_catastral"].strip()
            titular = (form.cleaned_data.get("titular") or "").strip()

            qs = CuentaServicio.objects.filter(nit=nit, codigo_catastral=cat, activa=True)
            if titular:
                qs = qs.filter(titular__iexact=titular)

            cuenta = qs.first()
            if not cuenta:
                messages.error(request, "No encontramos una cuenta con esos datos. Verifica e intenta de nuevo.")
                return redirect("vincular_cuenta")

            if cuenta.usuario and cuenta.usuario != request.user:
                messages.error(request, "Esta cuenta ya está vinculada a otro usuario. Contacta a la muni.")
                return redirect("vincular_cuenta")

            cuenta.usuario = request.user
            cuenta.save(update_fields=["usuario"])
            messages.success(request, "¡Cuenta vinculada correctamente!")
            return redirect("pagos_home")
    else:
        form = VincularCuentaForm()

    return render(request, "pagos/vincular_cuenta.html", {"form": form})

def _apply_dev_success_for_pago(pago_id: int) -> HttpResponse:
    pago = get_object_or_404(Pago, pk=pago_id)

    # Crea/actualiza la transacción “como si” fuera el webhook exitoso
    orden = f"pa_DEV_{pago_id}"
    tx, _ = TransaccionOnline.objects.get_or_create(
        orden_id=orden,
        defaults={"estado": "pending", "payload": {"dev": True, "now": str(now())}}
    )

    if tx.estado != "success":
        # set referencia y distribuir en boletas
        pago.referencia = tx.orden_id
        pago.save(update_fields=["referencia"])
        pago.distribuir_en_boletas()

        tx.estado = "success"
        tx.pago = pago
        tx.save(update_fields=["estado", "pago"])

    return HttpResponse("OK: pago aplicado.")

# --- POST (para cURL/PowerShell). Sin CSRF en modo dev ---
@csrf_exempt
@require_POST
def recurrente_dev_simular_success(request):
    if not settings.DEBUG:
        return HttpResponseBadRequest("Solo disponible en DEBUG.")
    try:
        pago_id = int(request.POST.get("pago_id", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("pago_id inválido.")
    return _apply_dev_success_for_pago(pago_id)

# --- GET (para navegador). Sin CSRF ---
@csrf_exempt
@require_GET
def recurrente_dev_simular_success_get(request):
    if not settings.DEBUG:
        return HttpResponseBadRequest("Solo disponible en DEBUG.")
    pago_id = request.GET.get("pago_id")
    if not (pago_id and pago_id.isdigit()):
        return HttpResponseBadRequest("Incluye ?pago_id=NN")
    return _apply_dev_success_for_pago(int(pago_id))

@csrf_exempt
def recurrente_webhook(request):
    """
    Webhook Recurrente (Svix) con verificación de firma + idempotencia.
    Soporta payloads:
      • {type, data}            (v1)
      • {event_type, ... plano} (v2)
    Eventos manejados:
      • payment_intent.succeeded / failed
      • bank_transfer_intent.succeeded / failed
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    secret = settings.RECURRENTE_WEBHOOK_SECRET
    if not secret:
        log.error("[REC-HOOK] Missing signing secret")
        return HttpResponseBadRequest("Missing signing secret")

    # 1) Verificar firma Svix
    try:
        payload_raw = request.body  # bytes
        headers = {k: v for k, v in request.headers.items()}
        verified = Webhook(secret).verify(payload_raw, headers)  # dict
    except Exception as e:
        log.exception("[REC-HOOK] Invalid signature: %s", e)
        return HttpResponseBadRequest(f"Invalid signature: {e}")

    # 2) Normalizar estructura
    event_type = verified.get("type") or verified.get("event_type")
    data_obj   = verified.get("data") or verified  # si no hay data, usar raíz

    # 2.1) ID externo robusto para idempotencia
    external_id = (
        data_obj.get("id")  # p.ej. pa_xxx
        or (data_obj.get("payment") or {}).get("id")
        or ((data_obj.get("checkout") or {}).get("latest_intent") or {}).get("id")
        or ((data_obj.get("checkout") or {}).get("id"))
        or verified.get("id")  # fallback
    )
    if not external_id:
        log.warning("[REC-HOOK] missing external id. event_type=%s", event_type)
        return JsonResponse({"error": "missing external id"}, status=400)

    # 2.2) Metadata (puede venir en checkout.metadata)
    meta = (
        data_obj.get("metadata")
        or verified.get("metadata")
        or ((data_obj.get("checkout") or {}).get("metadata"))
        or {}
    )
    pago_id = meta.get("pago_id")

    log.info("[REC-HOOK] event_type=%s external_id=%s pago_id=%s", event_type, external_id, pago_id)

    if not pago_id:
        # Registramos la transacción para trazabilidad, pero la dejamos en failed
        with transaction.atomic():
            tx, _ = TransaccionOnline.objects.select_for_update().get_or_create(
                orden_id=external_id,
                defaults={"estado": "pending", "payload": verified}
            )
            tx.estado = "failed"
            tx.payload = verified
            tx.save(update_fields=["estado", "payload", "actualizado_en"])
        return JsonResponse({"error": "missing pago_id in metadata"}, status=400)

    # 3) Idempotencia y actualización de dominio
    with transaction.atomic():
        tx, _ = TransaccionOnline.objects.select_for_update().get_or_create(
            orden_id=external_id,
            defaults={"estado": "pending", "payload": verified}
        )
        if tx.estado in ("success", "failed"):
            # Ya procesado previamente ─ devolvemos 200 para que Svix no reintente
            log.info("[REC-HOOK] already processed external_id=%s estado=%s", external_id, tx.estado)
            return HttpResponse(status=200)

        pago = Pago.objects.select_for_update().get(pk=pago_id)

        # Grupos de eventos
        card_succeeded = {"payment_intent.succeeded", "payment.succeeded"}
        card_failed    = {"payment_intent.failed", "payment.failed"}
        bank_succeeded = {"bank_transfer_intent.succeeded"}
        bank_failed    = {"bank_transfer_intent.failed"}

        if event_type in card_succeeded or event_type in bank_succeeded:
            # Éxito de cobro → set referencia, distribuir y marcar success
            if not pago.referencia:
                pago.referencia = external_id
                pago.save(update_fields=["referencia"])

            pago.distribuir_en_boletas()

            tx.estado = "success"
            tx.pago = pago
            tx.payload = verified
            tx.save(update_fields=["estado", "pago", "payload", "actualizado_en"])

            # Enviar recibo (idempotente: solo aquí cuando cambiamos a success)
            try:
                ok = send_receipt_email(pago)
                log.info("[REC-HOOK] recibo enviado=%s pago_id=%s dest=%s",
                        ok, pago.pk,
                        getattr(getattr(pago.cuenta, "usuario", None), "email", ""))
            except Exception as e:
                log.exception("[REC-HOOK] error enviando recibo pago_id=%s: %s", pago.pk, e)

        elif event_type in card_failed or event_type in bank_failed:
            tx.estado = "failed"
            tx.payload = verified
            tx.save(update_fields=["estado", "payload", "actualizado_en"])
            log.info("[REC-HOOK] marcado failed external_id=%s pago_id=%s", external_id, pago_id)

        else:
            # Otros eventos: conservar payload, responder 200 para no reintentar
            tx.payload = verified
            tx.save(update_fields=["payload", "actualizado_en"])
            log.info("[REC-HOOK] evento ignorado=%s external_id=%s", event_type, external_id)

    return HttpResponse(status=200)


def _get_tx_success(pago):
    """
    Última transacción SUCCESS del pago para extraer datos de tarjeta (si los hay).
    """
    tx = (TransaccionOnline.objects
          .filter(pago=pago, estado="success")
          .order_by("-actualizado_en", "-creado_en")
          .first())
    return tx

def _extract_card_info(tx):
    """
    Extrae red/ultimos 4/expiración desde tx.payload.checkout.payment_method.card
    Maneja ausencia de campos sin romper.
    """
    if not tx or not tx.payload:
        return {}
    pm = (tx.payload.get("checkout") or {}).get("payment_method") or {}
    card = pm.get("card") or {}
    return {
        "network": card.get("network") or "",
        "last4": str(card.get("last4") or ""),
        "issuer_name": card.get("issuer_name") or "",
        "exp_month": card.get("expiration_month") or "",
        "exp_year": card.get("expiration_year") or "",
    }

@login_required(login_url="login")
def recibo_pago_view(request, pago_id):
    """
    Vista HTML imprimible del recibo.
    - El ciudadano sólo puede ver sus propios pagos.
    - El staff puede ver cualquiera.
    """
    qs = Pago.objects.select_related("cuenta", "cuenta__usuario")
    pago = get_object_or_404(qs, pk=pago_id)

    # permiso básico
    if not request.user.is_staff:
        if not getattr(pago.cuenta, "usuario_id", None) or pago.cuenta.usuario_id != request.user.id:
            return HttpResponseBadRequest("No tienes permiso para ver este recibo.")

    # boletas aplicadas
    aplicaciones = []
    if AplicacionPago:
        aplicaciones = (AplicacionPago.objects
                        .filter(pago=pago)
                        .select_related("boleta", "boleta__periodo")
                        .order_by("boleta__periodo__anio", "boleta__periodo__mes"))

    # tarjeta (si fue con tarjeta)
    tx = _get_tx_success(pago)
    card = _extract_card_info(tx)

    total_aplicado = sum((a.monto_aplicado for a in aplicaciones), Decimal("0.00"))
    ctx = {
        "pago": pago,
        "cuenta": pago.cuenta,
        "aplicaciones": aplicaciones,
        "total_aplicado": total_aplicado,
        "municipalidad": "Municipalidad de San Luis",
        "referencia": pago.referencia or f"pa_{pago.pk}",
        "card": card,  # ✅ corrección
    }
    return render(request, "pagos/recibo.html", ctx)


# ---------- PDF opcional con WeasyPrint ----------
# pip install weasyprint==61.0  (o versión estable que uses)
# En Render no necesitas librerías del sistema si usas las imágenes/estilos hosteados (CDN) o inline.

@login_required(login_url="login")
def recibo_pago_pdf(request, pago_id):
    qs = Pago.objects.select_related("cuenta", "cuenta__usuario")
    pago = get_object_or_404(qs, pk=pago_id)

    if not request.user.is_staff:
        if not getattr(pago.cuenta, "usuario_id", None) or pago.cuenta.usuario_id != request.user.id:
            return HttpResponseBadRequest("No tienes permiso para ver este recibo.")

    aplicaciones = (AplicacionPago.objects
                    .filter(pago=pago)
                    .select_related("boleta", "boleta__periodo")
                    .order_by("boleta__periodo__anio", "boleta__periodo__mes"))

    # suma segura en Decimal (cubre lista vacía)
    total_aplicado = sum((a.monto_aplicado for a in aplicaciones), Decimal("0.00"))

    tx = _get_tx_success(pago)
    card = _extract_card_info(tx)

    ctx = {
        "pago": pago,
        "cuenta": pago.cuenta,
        "aplicaciones": aplicaciones,
        "total_aplicado": total_aplicado,   # 👈 aquí la clave
        "card": card,
        "municipalidad": "Municipalidad de San Luis",
        "referencia": getattr(pago, "referencia", f"pa_{pago.pk}"),
        "is_pdf": True,
    }

    html = render_to_string("pagos/recibo.html", ctx, request=request)
    from weasyprint import HTML
    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="recibo-{pago.pk}.pdf"'
    return resp

@login_required(login_url="login")
def mis_pagos(request):
    """
    Listado de pagos del ciudadano con filtros (rango de fechas, método, referencia)
    y paginación. Muestra links a recibo HTML y PDF.
    """
    usuario = request.user
    qs = (Pago.objects
          .select_related("cuenta")
          .filter(cuenta__usuario=usuario)
          .order_by("-id"))

    # --- filtros GET opcionales ---
    f_ini = request.GET.get("f_ini")  # yyyy-mm-dd
    f_fin = request.GET.get("f_fin")
    metodo = request.GET.get("metodo")  # 'online', 'caja', etc.
    ref = request.GET.get("ref")

    # fecha segura: usa 'fecha' si existe, si no 'creado_en'
    fecha_field = "fecha"
    if not hasattr(Pago, fecha_field):
        fecha_field = "creado_en"

    if f_ini:
        d = parse_date(f_ini)
        if d:
            qs = qs.filter(**{f"{fecha_field}__date__gte": d})
    if f_fin:
        d = parse_date(f_fin)
        if d:
            qs = qs.filter(**{f"{fecha_field}__date__lte": d})

    if metodo:
        qs = qs.filter(metodo__iexact=metodo)

    if ref:
        qs = qs.filter(referencia__icontains=ref)

    # paginación
    paginator = Paginator(qs, 15)
    page = request.GET.get("page")
    pagos = paginator.get_page(page)

    # para el selector de métodos mostramos los distintos existentes del usuario
    metodos = (Pago.objects
               .filter(cuenta__usuario=usuario)
               .order_by()
               .values_list("metodo", flat=True)
               .distinct())

    ctx = {
        "pagos": pagos,
        "metodos": [m for m in metodos if m],  # limpia None
        "f_ini": f_ini or "",
        "f_fin": f_fin or "",
        "metodo_sel": metodo or "",
        "ref": ref or "",
        "fecha_field": fecha_field,
    }
    return render(request, "pagos/mis_pagos.html", ctx)


@login_required(login_url="login")
def mis_pagos_csv(request):
    """
    Exporta a CSV los pagos del ciudadano aplicando los mismos filtros que la vista.
    """
    usuario = request.user
    qs = (Pago.objects
          .select_related("cuenta")
          .filter(cuenta__usuario=usuario)
          .order_by("-id"))

    f_ini = request.GET.get("f_ini")
    f_fin = request.GET.get("f_fin")
    metodo = request.GET.get("metodo")
    ref = request.GET.get("ref")

    fecha_field = "fecha"
    if not hasattr(Pago, fecha_field):
        fecha_field = "creado_en"

    if f_ini:
        d = parse_date(f_ini)
        if d:
            qs = qs.filter(**{f"{fecha_field}__date__gte": d})
    if f_fin:
        d = parse_date(f_fin)
        if d:
            qs = qs.filter(**{f"{fecha_field}__date__lte": d})
    if metodo:
        qs = qs.filter(metodo__iexact=metodo)
    if ref:
        qs = qs.filter(referencia__icontains=ref)

    # Construir CSV
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="mis_pagos.csv"'
    w = csv.writer(resp)
    w.writerow(["ID", "Fecha", "Cuenta", "Titular", "Método", "Referencia", "Monto (Q)"])

    for p in qs:
        fecha_val = getattr(p, fecha_field, None)
        cuenta = getattr(p, "cuenta", None)
        titular = getattr(cuenta, "titular", "") if cuenta else ""
        monto = getattr(p, "monto", "")
        w.writerow([p.id, fecha_val, cuenta, titular, p.metodo, p.referencia, monto])

    return resp
