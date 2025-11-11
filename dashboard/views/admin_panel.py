# dashboard/views/admin_panel.py
from django.contrib.auth.decorators import user_passes_test
from django.contrib import admin
from dashboard.models import CuentaServicio, Tarifa, Periodo, Boleta, Pago, AplicacionPago, TransaccionOnline
from dashboard.utils.email_utils import notify_permiso_estado
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.contrib import messages
from datetime import timedelta
from decimal import Decimal
from django.db.models.functions import Coalesce, TruncMonth
from django.utils.dateparse import parse_date
from dashboard.forms import AdminDenunciaEstadoForm
from dashboard.models import Denuncia, Permiso, BitacoraPermiso
from dashboard.utils.email_utils import notify_estado_cambio  
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from dashboard.models import Permiso, TipoPermiso
from django.contrib.auth.decorators import login_required, user_passes_test
from dashboard.forms import AdminPermisoEstadoForm
from dashboard.utils.audit import log_permiso
from django.utils import timezone
from django.db.models.functions import Coalesce
from django.utils.timezone import now
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Q, Value, CharField, OuterRef, Subquery


ESTADOS = ["enviada", "en revisión", "en proceso", "resuelta", "rechazada"]
ESTADOS_TX = ["success", "failed", "pending", "ignored"]

def es_admin(user):
    return user.is_authenticated and (user.is_staff or getattr(user, 'tipo_usuario', '') == 'administrador')

@staff_member_required
def index(request):
    # --- KPIs rápidos ---
    tot_denuncias = Denuncia.objects.count()
    tot_permisos  = Permiso.objects.count()

    # Boletas pendientes (conteo y saldo)
    qs_boletas_pend = Boleta.objects.filter(estado__in=["pendiente", "parcial"])
    boletas_pendientes = qs_boletas_pend.count()
    boletas_pend_total = qs_boletas_pend.aggregate(
        s=Coalesce(Sum("saldo_actual"), Decimal("0"))
    )["s"]

    # Anotar último estado de transacción por Pago
    ultima_tx_estado = (
        TransaccionOnline.objects
        .filter(pago_id=OuterRef("pk"))
        .order_by("-actualizado_en", "-creado_en")
        .values("estado")[:1]
    )
    pagos_annot = (
        Pago.objects
        .annotate(
            estado_tx=Coalesce(
                Subquery(ultima_tx_estado, output_field=CharField()),
                Value("pending")
            )
        )
    )

    # Total de ingresos (solo pagos cuyo último estado es success)
    total_ingresos = (
        pagos_annot
        .filter(estado_tx="success")
        .aggregate(s=Coalesce(Sum("monto"), Decimal("0")))
    )["s"]

    # Distribución por estado (según última TX)
    pagos_estado = {
        "success": pagos_annot.filter(estado_tx="success").count(),
        "failed":  pagos_annot.filter(estado_tx="failed").count(),
        "pending": pagos_annot.filter(estado_tx="pending").count(),
    }

    # --- Ingresos por mes (últimos 6, con meses faltantes = 0) ---
    hoy = now()
    base = hoy.date().replace(day=1)

    def shift_month(d, delta):
        # delta en meses (negativo/positivo). Devuelve el día 1 del mes resultante.
        y = d.year + (d.month - 1 + delta) // 12
        m = (d.month - 1 + delta) % 12 + 1
        return d.replace(year=y, month=m, day=1)

    # Secuencia fija de 6 meses: [-5, -4, -3, -2, -1, 0] (incluye mes actual)
    ult6 = [shift_month(base, k) for k in range(-5, 1)]
    # Para acotar la consulta, tomamos desde el 1er mes de la serie hasta el 1ro del mes siguiente al actual
    rango_inicio = ult6[0]
    rango_fin_exclusivo = shift_month(base, 1)

    # Agregación por mes usando la fecha de éxito (actualizado_en)
    agg = (
        TransaccionOnline.objects
        .filter(
            estado="success",
            actualizado_en__date__gte=rango_inicio,
            actualizado_en__date__lt=rango_fin_exclusivo,
        )
        .annotate(mes=TruncMonth("actualizado_en"))
        .values("mes")
        .annotate(total=Coalesce(Sum("pago__monto"), Decimal("0")))
    )

    # Diccionario {YYYY-MM-01 (date): total_float}
    totals = {}
    for x in agg:
        if x["mes"]:
            clave = x["mes"].date().replace(day=1)
            totals[clave] = float(x["total"] or 0)

    ingresos_mes = [
        {"mes": m.strftime("%Y-%m"), "total": totals.get(m, 0.0)}
        for m in ult6
    ]

    # ----- Auditoría (últimos 30 días) -----
    hace_30 = hoy - timedelta(days=30)
    tx_ult30 = TransaccionOnline.objects.filter(creado_en__gte=hace_30)

    intentos_30 = tx_ult30.count()
    exitos_30   = tx_ult30.filter(estado="success").count()
    fallidos_30 = tx_ult30.filter(estado="failed").count()
    conversion_30 = (exitos_30 * 100.0 / intentos_30) if intentos_30 else 0.0

    # Tiempos de cobro (success): segundos = actualizado_en - creado_en
    tx_succ_30 = tx_ult30.filter(estado="success").values("creado_en", "actualizado_en")
    dur_secs = []
    for t in tx_succ_30:
        delta = (t["actualizado_en"] - t["creado_en"]).total_seconds()
        if delta >= 0:
            dur_secs.append(delta)
    dur_avg = round(sum(dur_secs) / len(dur_secs), 2) if dur_secs else 0.0
    dur_p95 = 0.0
    if dur_secs:
        s = sorted(dur_secs)
        idx = int(0.95 * (len(s) - 1))
        dur_p95 = round(s[idx], 2)

    # Serie diaria intentos/éxitos (últimos 14 días)
    desde_14 = hoy - timedelta(days=13)
    by_day = {(hoy - timedelta(days=i)).date(): {"intentos": 0, "success": 0} for i in range(14)}
    for d in (
        tx_ult30
        .filter(creado_en__date__gte=desde_14.date())
        .values("creado_en__date", "estado")
    ):
        by_day[d["creado_en__date"]]["intentos"] += 1
        if d["estado"] == "success":
            by_day[d["creado_en__date"]]["success"] += 1
    buckets = [
        {
            "dia": k.strftime("%Y-%m-%d"),
            "intentos": by_day[k]["intentos"],
            "success": by_day[k]["success"],
        }
        for k in sorted(by_day.keys())
    ]

    # Últimos registros (tablas rápidas)
    ultimas_denuncias = (
        Denuncia.objects
        .select_related("categoria")
        .order_by("-creada_en")[:5]
    )
    ultimos_permisos = (
        Permiso.objects
        .select_related()
        .order_by("-creado_en")[:5]
    )
    ultimos_pagos = (
        pagos_annot
        .select_related("cuenta", "cuenta__usuario")
        .order_by("-id")[:5]
    )

    ctx = {
        # KPIs
        "tot_denuncias": tot_denuncias,
        "tot_permisos": tot_permisos,
        "boletas_pendientes": boletas_pendientes,
        "boletas_pend_total": boletas_pend_total,
        "total_ingresos": total_ingresos,

        # series para gráficas
        "ingresos_mes": ingresos_mes,   # [{mes:"YYYY-MM", total: float}, ...] siempre 6 items
        "pagos_estado": pagos_estado,   # {"success": X, "failed": Y, "pending": Z}

        # tablas rápidas
        "ultimas_denuncias": ultimas_denuncias,
        "ultimos_permisos": ultimos_permisos,
        "ultimos_pagos": ultimos_pagos,

        # auditoría pagos
        "intentos_30": intentos_30,
        "exitos_30": exitos_30,
        "fallidos_30": fallidos_30,
        "conversion_30": round(conversion_30, 2),
        "dur_avg": dur_avg,   # segundos
        "dur_p95": dur_p95,   # segundos
        "serie_intentos": buckets,  # [{dia, intentos, success}]
    }
    return render(request, "admin_panel/index.html", ctx)


@user_passes_test(es_admin, login_url='login')
def denuncias(request):
    qs = Denuncia.objects.select_related('categoria','usuario','ubicacion').order_by('-creada_en')
    estado = request.GET.get('estado', '')   # <-- default vacío
    if estado:
        qs = qs.filter(estado=estado)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page') or 1)

    return render(request, 'admin_panel/denuncias_list.html', {
        "page_obj": page_obj,
        "estado": estado,
        "ESTADOS": ESTADOS,
    })

@user_passes_test(es_admin, login_url='login')
def denuncia_detalle(request, pk):
    d = get_object_or_404(
        Denuncia.objects.select_related('categoria','usuario','ubicacion'), pk=pk
    )

    # ✅ Auto-marcar como "en revisión" si estaba "enviada"
    if d.estado == "enviada":
        anterior = d.estado
        d.estado = "en revisión"
        d.save(update_fields=["estado"])

        # bitácora + (opcional) correo
        from dashboard.utils.audit import log_denuncia
        log_denuncia(
            denuncia=d,
            usuario=request.user,
            accion="Actualización",
            estado_anterior=anterior,
            estado_nuevo=d.estado,
            cambios={"estado": [anterior, d.estado]},
            request=request,
        )

        # (opcional) correo
        try:
            from dashboard.utils.email_utils import notify_estado_cambio
            notify_estado_cambio(d, anterior, d.estado)
        except Exception:
            pass

    form = AdminDenunciaEstadoForm(instance=d)
    return render(
        request,
        'admin_panel/denuncia_detalle.html',
        {"d": d, "ESTADOS": ESTADOS, "form_estado": form}
    )

@user_passes_test(es_admin, login_url='login')
def cambiar_estado(request, pk):
    d = get_object_or_404(Denuncia, pk=pk)

    if request.method != 'POST':
        return redirect('admin_denuncia_detalle', pk=pk)

    anterior = d.estado  # guarda el estado actual antes de aplicar cambios

    form = AdminDenunciaEstadoForm(request.POST, request.FILES, instance=d)
    if not form.is_valid():
        # Muestra errores del form en la misma pantalla de detalle
        for fld, errs in form.errors.items():
            for e in errs:
                messages.error(request, f"{fld}: {e}")
        return redirect('admin_denuncia_detalle', pk=pk)

    # Reglas de negocio previas a guardar definitivo
    nuevo = form.cleaned_data.get("estado")
    motivo = (form.cleaned_data.get("rechazo_motivo") or "").strip()

    if nuevo == "rechazada" and not motivo:
        messages.error(request, "Debes indicar el motivo del rechazo.")
        return redirect('admin_denuncia_detalle', pk=pk)

    # Si no es rechazada, limpia motivo
    if nuevo != "rechazada":
        d.rechazo_motivo = ""

    # Si se marca resuelta o rechazada, puedes setear finalizada_en si quieres
    if nuevo in ("resuelta", "rechazada") and not d.finalizada_en:
        from django.utils import timezone
        d.finalizada_en = timezone.now()

    # Guarda todos los cambios del form (incluye resolucion_nota / resolucion_evidencia)
    d = form.save()


    # Notifica si cambió el estado
    if nuevo != anterior:
        notify_estado_cambio(d, anterior, nuevo)
        messages.success(request, f"Estado actualizado de “{anterior}” a “{nuevo}”.")
    else:
        messages.info(request, "El estado no cambió. Datos guardados.")

    return redirect('admin_denuncia_detalle', pk=pk)

def admin_cambiar_estado_permiso(request, pk):
    if request.method != 'POST':
        return redirect('admin_permiso_detalle', pk=pk)

    p = get_object_or_404(Permiso, pk=pk)
    nuevo = (request.POST.get('estado') or '').strip()
    anterior = p.estado

    if nuevo not in dict(Permiso.ESTADOS):
        messages.error(request, "Estado inválido.")
        return redirect('admin_permiso_detalle', pk=pk)

    if nuevo != anterior:
        p.estado = nuevo
        p.save(update_fields=['estado'])  # pre_save señal marcará finalizado_en si aplica

        BitacoraPermiso.objects.create(
            permiso=p,
            usuario=request.user,
            accion=f"Estado: {anterior} → {nuevo}"
        )
        messages.success(request, f"Estado actualizado a “{nuevo}”.")
    else:
        messages.info(request, "El estado no cambió.")

    return redirect('admin_permiso_detalle', pk=pk)

@login_required(login_url='login')
@user_passes_test(es_admin)
def permisos(request):
    qs = (Permiso.objects
          .select_related("tipo_permiso", "usuario", "ubicacion__barrio")
          .order_by("-creado_en"))

    # --- filtros simples ---
    estado = request.GET.get("estado") or ""
    tipo_id = request.GET.get("tipo") or ""
    q = (request.GET.get("q") or "").strip()

    if estado:
        qs = qs.filter(estado=estado)
    if tipo_id:
        qs = qs.filter(tipo_permiso_id=tipo_id)
    if q:
        qs = qs.filter(
            Q(descripcion__icontains=q) |
            Q(ubicacion__direccion__icontains=q) |
            Q(usuario__correo__icontains=q)
        )

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = {
        "page_obj": page_obj,
        "ESTADOS": [e for e, _ in Permiso.ESTADOS],  # para el select
        "estado": estado,
        "tipo": tipo_id,
        "tipos": TipoPermiso.objects.all().order_by("nombre"),
        "q": q,
    }
    return render(request, "admin_panel/permisos_list.html", ctx)

@login_required(login_url="login")
@user_passes_test(es_admin, login_url="login")
def permiso_detalle(request, pk):
    p = get_object_or_404(
        Permiso.objects.select_related("tipo_permiso", "usuario", "ubicacion__barrio").prefetch_related("bitacoras"),
        pk=pk
    )

    if p.estado == "enviada":
         estado_anterior = p.estado
         p.estado = "revisada"
         p.save(update_fields=["estado"])
         log_permiso(
             permiso=p, usuario=request.user, accion="Actualización",
             estado_anterior=estado_anterior, estado_nuevo=p.estado,
             cambios={"estado": [estado_anterior, p.estado]},
             request=request
         )

    form_estado = AdminPermisoEstadoForm(instance=p)
    # Ordenar bitácora (por si no hay ordering)
    bitacoras = sorted(p.bitacoras.all(), key=lambda b: b.fecha, reverse=True)

    return render(request, "admin_panel/permiso_detalle.html", {
        "p": p,
        "form_estado": form_estado,
        "bitacoras": bitacoras,
    })

@login_required(login_url="login")
@user_passes_test(es_admin, login_url="login")
def permiso_cambiar_estado(request, pk):
    p = get_object_or_404(Permiso, pk=pk)
    if request.method != "POST":
        return redirect("admin_permiso_detalle", pk=pk)

    # --- snapshot 'antes' ---
    def snap(obj: Permiso):
        return {
            "estado": obj.estado,
            "aceptacion_nota": (obj.aceptacion_nota or "").strip(),
            "observaciones": (obj.observaciones or "").strip(),
            "permiso_adjunto": getattr(obj.permiso_adjunto, "name", ""),  # nombre o ""
        }

    before = snap(p)

    form = AdminPermisoEstadoForm(request.POST, request.FILES, instance=p)
    if not form.is_valid():
        messages.error(request, "Revisa el formulario.")
        bitacoras = sorted(p.bitacoras.all(), key=lambda b: b.fecha, reverse=True)
        return render(request, "admin_panel/permiso_detalle.html", {
            "p": p,
            "form_estado": form,
            "bitacoras": bitacoras,
        })

    p = form.save(commit=False)

    # Reglas adicionales de negocio
    if p.estado == "finalizada" and not p.finalizado_en:
        p.finalizado_en = timezone.now()
    if p.estado == "aceptada" and not p.aceptado_por:
        p.aceptado_por = request.user

    p.save()

    # --- snapshot 'después' ---
    after = snap(p)

    # --- diff simple clave→(antes, después) ---
    diffs = {k: (before[k], after[k]) for k in after.keys() if before[k] != after[k]}

    # Bitácora (solo si hubo algo)
    if diffs:
        log_permiso(
            permiso=p,
            usuario=request.user,
            accion="Actualización",
            estado_anterior=before["estado"],
            estado_nuevo=after["estado"],
            cambios=diffs,
            request=request,
        )

    # Email (no romper si no hay adjunto/plantilla/etc.)
    try:
        notify_permiso_estado(p, before["estado"], after["estado"])
    except Exception:
        pass

    # Mensajes claros según lo que cambió
    if "estado" in diffs:
        messages.success(request, f'Estado actualizado de “{before["estado"]}” a “{after["estado"]}”.')
    else:
        if diffs:
            messages.info(request, "El estado no cambió. Datos guardados.")
        else:
            messages.info(request, "No hubo cambios.")

    return redirect("admin_permiso_detalle", pk=pk)


@staff_member_required
def admin_pagos_auditoria(request):
    qs = (TransaccionOnline.objects
          .select_related("pago", "pago__cuenta", "pago__cuenta__usuario")
          .order_by("-creado_en"))

    # --- filtros ---
    from django.utils.dateparse import parse_date
    f_ini   = request.GET.get("f_ini")
    f_fin   = request.GET.get("f_fin")
    estado  = request.GET.get("estado")
    q       = (request.GET.get("q") or "").strip()

    if f_ini:
        d = parse_date(f_ini)
        if d: qs = qs.filter(creado_en__date__gte=d)
    if f_fin:
        d = parse_date(f_fin)
        if d: qs = qs.filter(creado_en__date__lte=d)
    if estado in set(ESTADOS_TX):
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(
            Q(orden_id__icontains=q) |
            Q(pago__cuenta__usuario__correo__icontains=q) |
            Q(pago__cuenta__codigo_catastral__icontains=q) |
            Q(pago__cuenta__id__iexact=q)
        )

    # ⚡️ Primero pagina, luego calculas latencia sólo para los items de la página (evita cargar todo)
    from django.core.paginator import Paginator
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))

    filas = []
    for tx in page.object_list:
        lat = None
        if tx.estado in ("success", "failed") and tx.actualizado_en and tx.creado_en:
            lat = (tx.actualizado_en - tx.creado_en).total_seconds()
        fail_reason = (
            (tx.payload or {}).get("data", {}).get("failure_reason")
            or (tx.payload or {}).get("failure_reason")
            or (tx.payload or {}).get("checkout", {}).get("failure_reason")
            or ""
        )
        filas.append({"tx": tx, "lat": lat, "fail_reason": fail_reason})

    return render(request, "admin_panel/pagos_auditoria.html", {
        "page": page,
        "filas": filas,
        "f_ini": f_ini or "",
        "f_fin": f_fin or "",
        "estado": estado or "",
        "q": q,
        "ESTADOS_TX": ESTADOS_TX,  # ⬅️ para el <select>
    })
    
    