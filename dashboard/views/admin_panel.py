# dashboard/views/admin_panel.py
from django.contrib.auth.decorators import user_passes_test
from django.contrib import admin
from dashboard.models import CuentaServicio, Tarifa, Periodo, Boleta, Pago, AplicacionPago, TransaccionOnline
from dashboard.utils.email_utils import notify_permiso_estado
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.contrib import messages
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

ESTADOS = ["enviada", "en revisión", "en proceso", "resuelta", "rechazada"]


def es_admin(user):
    return user.is_authenticated and (user.is_staff or getattr(user, 'tipo_usuario', '') == 'administrador')

@user_passes_test(es_admin, login_url='login')
def index(request):
    ctx = {
        "tot_denuncias": Denuncia.objects.count(),
        "ultimas_denuncias": Denuncia.objects.select_related('categoria').order_by('-creada_en')[:10],
    }
    return render(request, 'admin_panel/index.html', ctx)

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

