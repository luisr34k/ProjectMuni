# dashboard/views/payments.py

# 1. Librerías estándar de Python
import json
import os
from datetime import date
from decimal import Decimal
from decimal import ROUND_HALF_UP

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

# 3. Módulos de la aplicación
from dashboard.forms import VincularCuentaForm
from dashboard.models import CuentaServicio, Boleta, Pago, TransaccionOnline
from dashboard.utils import recurrente as rec
from dashboard.utils.billing import ensure_boletas_pendientes

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
    Webhook de Recurrente con verificación de firma (Svix) + idempotencia.
    Soporta payloads tipo:
      a) {"type": "payment.succeeded", "data": {...}}
      b) {"event_type": "payment_intent.succeeded", ... (flat) }
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    secret = settings.RECURRENTE_WEBHOOK_SECRET
    if not secret:
        return HttpResponseBadRequest("Missing signing secret")

    # 1) Verificar firma (usa headers 'svix-*')
    try:
        payload_raw = request.body  # bytes
        headers = {k: v for k, v in request.headers.items()}
        verified = Webhook(secret).verify(payload_raw, headers)  # dict seguro
    except Exception as e:
        return HttpResponseBadRequest(f"Invalid signature: {e}")

    # 2) Normalizar estructura
    event_type = verified.get("type") or verified.get("event_type")
    data_obj   = verified.get("data") or verified  # si no hay data, usa raíz

    # 2.1) ID externo robusto para idempotencia
    external_id = (
        data_obj.get("id")  # id del intent/event (p.ej. pa_xxx)
        or (data_obj.get("payment") or {}).get("id")
        or ((data_obj.get("checkout") or {}).get("latest_intent") or {}).get("id")
        or ((data_obj.get("checkout") or {}).get("id"))
        or verified.get("id")  # fallback
    )
    if not external_id:
        return JsonResponse({"error": "missing external id"}, status=400)

    # 2.2) Metadata puede venir anidada en checkout.metadata
    meta = (
        data_obj.get("metadata")
        or verified.get("metadata")
        or ((data_obj.get("checkout") or {}).get("metadata"))
        or {}
    )
    pago_id = meta.get("pago_id")

    # (debug opcional)
    try:
        print(f"[REC-HOOK] event_type={event_type} pago_id={pago_id} "
              f"has_checkout_meta={bool((data_obj.get('checkout') or {}).get('metadata'))}")
    except Exception:
        pass

    if not pago_id:
        # registra la transacción como fallida para trazabilidad
        with transaction.atomic():
            tx, _ = TransaccionOnline.objects.select_for_update().get_or_create(
                orden_id=external_id,
                defaults={"estado": "pending", "payload": verified}
            )
            tx.estado = "failed"
            tx.payload = verified
            tx.save(update_fields=["estado", "payload", "actualizado_en"])
        return JsonResponse({"error": "missing pago_id in metadata"}, status=400)

    # 3) Idempotencia y actualización del dominio
    with transaction.atomic():
        tx, _ = TransaccionOnline.objects.select_for_update().get_or_create(
            orden_id=external_id,
            defaults={"estado": "pending", "payload": verified}
        )
        if tx.estado in ("success", "failed"):
            return HttpResponse(status=200)  # ya procesado

        pago = Pago.objects.select_for_update().get(pk=pago_id)

        # Acepta ambas nomenclaturas de eventos
        succeeded_events = {"payment.succeeded", "payment_intent.succeeded"}
        failed_events    = {"payment.failed", "payment_intent.failed", "payment_intent.canceled"}

        if event_type in succeeded_events:
            # Marca referencia y distribuye
            if not pago.referencia:
                pago.referencia = external_id
                pago.save(update_fields=["referencia"])
            pago.distribuir_en_boletas()

            tx.estado = "success"
            tx.pago = pago
            tx.payload = verified
            tx.save(update_fields=["estado", "pago", "payload", "actualizado_en"])

        elif event_type in failed_events:
            tx.estado = "failed"
            tx.payload = verified
            tx.save(update_fields=["estado", "payload", "actualizado_en"])

        else:
            # Otros eventos: conserva payload para auditoría
            tx.payload = verified
            tx.save(update_fields=["payload", "actualizado_en"])

    return HttpResponse(status=200)
