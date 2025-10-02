# dashboard/views/payments.py
import json
from django.utils.timezone import now
from decimal import Decimal
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from dashboard.models import CuentaServicio
from django.db import transaction
from dashboard.forms import VincularCuentaForm
from django.contrib import messages
from dashboard.models import CuentaServicio, Boleta
from dashboard.utils.billing import ensure_boletas_pendientes
from datetime import date
from django.views.decorators.http import require_POST
from django.conf import settings
from dashboard.models import CuentaServicio
from decimal import Decimal, ROUND_HALF_UP
from dashboard.models import CuentaServicio, Boleta, Pago, TransaccionOnline
from dashboard.utils import recurrente as rec

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

@csrf_exempt
def recurrente_webhook(request):
    """
    Recibe eventos de Recurrente. Manejo idempotente por orden_id (payment_intent id).
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    event_type = payload.get("event_type")
    intent_id  = payload.get("id")  # pa_XXXX segun doc
    if not intent_id:
        return JsonResponse({"error": "missing id"}, status=400)

    # Idempotencia por orden_id
    with transaction.atomic():
        tx, created = TransaccionOnline.objects.select_for_update().get_or_create(
            orden_id=intent_id,
            defaults={"estado": "pending", "payload": payload}
        )
        # Si ya está finalizada, salimos
        if tx.estado in ("success", "failed"):
            return HttpResponse(status=200)

        # Obtén pago_id desde metadata (recomendado por Recurrente)
        meta = payload.get("metadata") or {}
        pago_id = meta.get("pago_id")

        if not pago_id:
            # Como fallback podrías crear un log o marcar failed
            tx.estado = "failed"
            tx.payload = payload
            tx.save(update_fields=["estado", "payload", "actualizado_en"])
            return JsonResponse({"error": "missing pago_id in metadata"}, status=400)

        pago = Pago.objects.select_for_update().get(pk=pago_id)

        if event_type == "payment_intent.succeeded":
            # Marca referencia + distribuye en boletas
            pago.referencia = intent_id
            pago.save(update_fields=["referencia"])  # metodo ya es 'online'

            pago.distribuir_en_boletas()

            tx.estado = "success"
            tx.pago = pago
            tx.payload = payload
            tx.save(update_fields=["estado", "pago", "payload", "actualizado_en"])
        elif event_type in ("payment_intent.failed", "payment_intent.canceled"):
            tx.estado = "failed"
            tx.payload = payload
            tx.save(update_fields=["estado", "payload", "actualizado_en"])
        else:
            # Otros eventos: guarda payload para referencia
            tx.payload = payload
            tx.save(update_fields=["payload", "actualizado_en"])

    return HttpResponse(status=200)

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