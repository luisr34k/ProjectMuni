# dashboard/views/user.py
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from dashboard.forms import (
    DenunciaEditForm,
    DenunciaForm,
    PermisoEditForm,
    PermisoForm,
)
from dashboard.models import Denuncia, Permiso, Ubicacion
from dashboard.utils.email_utils import notify_denuncia_creada


from django.contrib.auth.decorators import login_required
from dashboard.models import Pago, Permiso, Denuncia

@login_required(login_url="login")
def index(request):
    user = request.user

    # KPIs básicos (puedes ajustar según tus modelos)
    pagos_totales = Pago.objects.filter(usuario_registra=user).count()
    pagos_pendientes = Pago.objects.filter(usuario_registra=user, referencia="").count()
    permisos_count = Permiso.objects.filter(usuario=user).count()
    denuncias_count = Denuncia.objects.filter(usuario=user).count()

    ctx = {
        "user": user,
        "pagos_totales": pagos_totales,
        "pagos_pendientes": pagos_pendientes,
        "permisos_count": permisos_count,
        "denuncias_count": denuncias_count,
    }
    return render(request, "user/index.html", ctx)


def mapa_publico(request):
    """
    Mapa público centrado en San Luis Jilotepeque.
    No requiere login.
    """
    ctx = {
        "center_lat": 14.65,
        "center_lng": -89.73,
        "zoom": 13,
    }
    return render(request, "user/mapa_publico.html", ctx)


@login_required(login_url="login")
def mis_denuncias(request):
    qs = (
        Denuncia.objects.filter(usuario=request.user)
        .select_related("categoria", "ubicacion")
        .order_by("-creada_en")
    )
    page = Paginator(qs, 8).get_page(request.GET.get("page"))
    return render(request, "user/denuncias_mias.html", {"denuncias": page})


@login_required(login_url="login")
def mis_permisos(request):
    qs = (
        Permiso.objects.filter(usuario=request.user)
        .select_related("tipo_permiso", "ubicacion")
        .order_by("-creado_en")
    )
    page = Paginator(qs, 8).get_page(request.GET.get("page"))
    return render(request, "user/permisos_mios.html", {"permisos": page})


def denuncias_publicas_json(request):
    """
    Denuncias públicas en JSON (actualmente: solo anónimas).
    Ajusta el filtro si luego agregas otro flag de visibilidad.
    """
    data = (
        Denuncia.objects.filter(es_anonima=True)
        .select_related("categoria", "ubicacion")
        .values(
            "id",
            "categoria__nombre",
            "estado",
            "creada_en",
            "ubicacion__latitud",
            "ubicacion__longitud",
            "ubicacion__direccion",
        )
    )
    return JsonResponse(list(data), safe=False)


@login_required(login_url="login")
def denuncias_view(request):
    """GET: formulario de creación de denuncia."""
    form = DenunciaForm()
    return render(request, "user/form_denuncias.html", {"form": form})


@login_required(login_url="login")
def detalle_denuncia(request, pk):
    d = get_object_or_404(
        Denuncia.objects.select_related("categoria", "ubicacion__barrio").prefetch_related("bitacoras"),
        pk=pk,
        usuario=request.user,
    )
    bitacoras = sorted(d.bitacoras.all(), key=lambda b: b.fecha, reverse=True)
    return render(request, "user/denuncia_detalle.html", {"d": d, "bitacoras": bitacoras})


@login_required(login_url="login")
def permiso_detalle(request, pk):
    p = get_object_or_404(
        Permiso.objects.select_related("tipo_permiso", "ubicacion__barrio").prefetch_related("bitacoras"),
        pk=pk,
        usuario=request.user,
    )
    bitacoras = sorted(p.bitacoras.all(), key=lambda b: b.fecha, reverse=True)
    return render(request, "user/permiso_detalle.html", {"p": p, "bitacoras": bitacoras})


@login_required(login_url="login")
def crear_denuncia(request):
    if request.method == "POST":
        form = DenunciaForm(request.POST, request.FILES)
        if form.is_valid():
            denuncia = form.save(commit=False)

            direccion = form.cleaned_data["direccion"].strip()
            barrio = form.cleaned_data["barrio"]
            lat = form.cleaned_data.get("latitud")
            lng = form.cleaned_data.get("longitud")

            # Crear ubicación (siempre hay dirección/barrio)
            ubic = Ubicacion(direccion=direccion, barrio=barrio)
            if lat is not None and lng is not None and str(lat) != "" and str(lng) != "":
                ubic.latitud = lat
                ubic.longitud = lng
            ubic.save()

            denuncia.ubicacion = ubic
            denuncia.usuario = None if form.cleaned_data.get("es_anonima") else request.user
            denuncia.save()

            if denuncia.usuario:
                notify_denuncia_creada(denuncia)

            messages.success(request, "Denuncia enviada correctamente.")
            return redirect("mis_denuncias")
    else:
        form = DenunciaForm()

    return render(request, "user/form_denuncias.html", {"form": form})


@login_required(login_url="login")
def editar_denuncia(request, pk):
    d = get_object_or_404(Denuncia, pk=pk, usuario=request.user)

    if d.estado != "enviada":
        messages.error(request, "Solo puedes editar denuncias en estado ‘enviada’.")
        return redirect("mis_denuncias")

    if request.method == "POST":
        form = DenunciaEditForm(request.POST, request.FILES, instance=d)
        if form.is_valid():
            d = form.save(commit=False)

            dir_ = (form.cleaned_data.get("direccion") or "").strip()
            barrio = form.cleaned_data.get("barrio")
            lat = form.cleaned_data.get("latitud")
            lng = form.cleaned_data.get("longitud")

            if any([dir_, barrio is not None, lat not in (None, ""), lng not in (None, "")]):
                u = d.ubicacion or Ubicacion()
                if dir_ != "":
                    u.direccion = dir_
                if barrio is not None:
                    u.barrio = barrio
                if lat not in (None, "") and lng not in (None, ""):
                    u.latitud = lat
                    u.longitud = lng
                u.save()
                d.ubicacion = u

            # Evidencia (borrar si marcó)
            if form.cleaned_data.get("eliminar_evidencia"):
                if d.evidencia:
                    d.evidencia.delete(save=False)
                d.evidencia = None

            if form.cleaned_data.get("es_anonima"):
                d.usuario = None

            d.save()
            messages.success(request, "Denuncia actualizada correctamente.")
            return redirect("mis_denuncias")
    else:
        initial = {}
        if d.ubicacion:
            if d.ubicacion.direccion:
                initial["direccion"] = d.ubicacion.direccion
            if d.ubicacion.barrio:
                initial["barrio"] = d.ubicacion.barrio_id
            if d.ubicacion.latitud is not None:
                initial["latitud"] = d.ubicacion.latitud
            if d.ubicacion.longitud is not None:
                initial["longitud"] = d.ubicacion.longitud
        form = DenunciaEditForm(instance=d, initial=initial)

    return render(request, "user/denuncia_edit.html", {"form": form, "d": d})


@login_required(login_url="login")
def permisos_view(request):
    """GET: muestra el formulario de permisos."""
    form = PermisoForm()
    return render(request, "user/form_permisos.html", {"form": form})


@login_required(login_url="login")
def crear_permiso(request):
    if request.method == "POST":
        form = PermisoForm(request.POST, request.FILES)
        if form.is_valid():
            p = form.save(commit=False)
            p.usuario = request.user

            # Ubicación
            dir_ = (form.cleaned_data.get("direccion") or "").strip()
            barrio = form.cleaned_data.get("barrio")
            raw_lat = (request.POST.get("latitud") or "").strip().replace(",", ".")
            raw_lng = (request.POST.get("longitud") or "").strip().replace(",", ".")

            u = Ubicacion(direccion=dir_, barrio=barrio)
            # Guarda como Decimal si hay números válidos
            if raw_lat and raw_lng:
                try:
                    u.latitud = Decimal(raw_lat)
                    u.longitud = Decimal(raw_lng)
                except InvalidOperation:
                    pass
            u.save()
            p.ubicacion = u

            p.save()
            messages.success(request, "Solicitud de permiso enviada correctamente.")
            return redirect("mis_permisos")
    else:
        form = PermisoForm()

    return render(request, "user/form_permisos.html", {"form": form})


@login_required(login_url="login")
def editar_permiso(request, pk):
    p = get_object_or_404(Permiso, pk=pk, usuario=request.user)

    if p.estado != "enviada":
        messages.error(request, "Solo puedes editar permisos en estado ‘enviada’.")
        return redirect("mis_permisos")

    if request.method == "POST":
        form = PermisoEditForm(request.POST, request.FILES, instance=p)
        if form.is_valid():
            p = form.save(commit=False)

            dir_ = (form.cleaned_data.get("direccion") or "").strip()
            barrio = form.cleaned_data.get("barrio")

            raw_lat = (request.POST.get("latitud") or "").strip().replace(",", ".")
            raw_lng = (request.POST.get("longitud") or "").strip().replace(",", ".")

            if any([dir_, barrio is not None, raw_lat, raw_lng]):
                u = p.ubicacion or Ubicacion()
                if dir_ != "":
                    u.direccion = dir_
                if barrio is not None:
                    u.barrio = barrio

                if raw_lat and raw_lng:
                    try:
                        u.latitud = Decimal(raw_lat)
                        u.longitud = Decimal(raw_lng)
                    except InvalidOperation:
                        pass
                u.save()
                p.ubicacion = u

            # Adjuntos (eliminar si el usuario marcó). Estos flags deben venir del template.
            if form.cleaned_data.get("eliminar_dpi_frente"):
                if p.dpi_frente:
                    p.dpi_frente.delete(save=False)
                p.dpi_frente = None
            if form.cleaned_data.get("eliminar_dpi_reverso"):
                if p.dpi_reverso:
                    p.dpi_reverso.delete(save=False)
                p.dpi_reverso = None
            if form.cleaned_data.get("eliminar_evidencia_lugar"):
                if p.evidencia_lugar:
                    p.evidencia_lugar.delete(save=False)
                p.evidencia_lugar = None

            p.save()
            messages.success(request, "Permiso actualizado correctamente.")
            return redirect("permiso_detalle", pk=p.pk)
    else:
        initial = {}
        if p.ubicacion:
            if p.ubicacion.direccion:
                initial["direccion"] = p.ubicacion.direccion
            if p.ubicacion.barrio:
                initial["barrio"] = p.ubicacion.barrio_id
        form = PermisoEditForm(instance=p, initial=initial)

    return render(request, "user/permiso_edit.html", {"form": form, "p": p})
