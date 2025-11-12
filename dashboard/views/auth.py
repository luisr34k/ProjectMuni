# dashboard/views/auth.py
from django.shortcuts import render, redirect
from django.urls import resolve, Resolver404, reverse
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from dashboard.models import Usuario
from django.utils.html import escape
from django.shortcuts import get_object_or_404
from datetime import timedelta
from django.utils import timezone
from dashboard.forms import RegistroUsuarioForm
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout

def login_view(request):
    # Si ya está logueado y abre el login, mándalo a su home según rol
    if request.method == "GET" and request.user.is_authenticated:
        return redirect(home_para(request.user))

    if request.method == "POST":
        correo = (request.POST.get('correo') or '').strip().lower()
        password = request.POST.get('password')
        remember = request.POST.get('remember') == 'on'
        next_raw = request.POST.get('next', '').strip()  # puede venir vacío o como '/admin-panel/'

        user = authenticate(request, username=correo, password=password)
        if user is None:
            messages.error(request, "Correo o contraseña incorrectos.")
            return render(request, 'auth/login.html', {"next": request.POST.get('next', '')})

        if not user.es_activo:
            messages.error(request, "Tu cuenta no está activada. Revisa tu correo.")
            return render(request, 'auth/login.html', {"next": request.POST.get('next', '')})

        login(request, user)
        if not remember:
            request.session.set_expiry(0)

        # Decidir destino
        if next_raw:
            # Si 'next' apunta a admin pero el usuario no es admin, ignoramos 'next'
            if es_ruta_admin(next_raw) and not es_admin(user):
                messages.warning(request, "No tienes permisos para acceder a esa sección. Te redirigimos a tu inicio.")
                return redirect(home_para(user))
            # Si es válido, adelante
            return redirect(next_raw)

        # Sin 'next' → home por rol
        return redirect(home_para(user))
    messages.get_messages(request) 
    # GET normal
    return render(request, 'auth/login.html', {"next": request.GET.get('next', '')})

def logout_view(request):
    logout(request)
    return redirect("login") 

def es_admin(user):
    return user.is_authenticated and (user.is_staff or getattr(user, 'tipo_usuario', '') == 'administrador')

def home_para(user) -> str:
    return 'admin_panel' if es_admin(user) else 'index'  # 'index' = dashboard de usuario

# ¿La ruta de "next" es a una URL admin?
def es_ruta_admin(path: str) -> bool:
    try:
        match = resolve(path)
        return match.url_name and match.url_name.startswith('admin_') or match.url_name == 'admin_panel'
    except Resolver404:
        return path.startswith('/admin-panel')


def register(request):
    if request.method == "POST":
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            usuario = form.save(commit=False)
            usuario.set_password(form.cleaned_data['password'])
            usuario.es_activo = False
            usuario.acepto_terminos = form.cleaned_data['acepto_terminos']
            usuario.fecha_aceptacion = timezone.now()
            usuario.save()

            # Link de activación
            token = usuario.token_activacion
            activation_link = request.build_absolute_uri(
                reverse("activar_cuenta", args=[token])
            )

            asunto = "Activa tu cuenta - Muni San Luis"
            mensaje = f"""
            Hola {escape(usuario.nombre)},
            Gracias por registrarte.
            Activa tu cuenta aquí: {activation_link}
            """

            send_mail(
                asunto,
                mensaje,
                settings.DEFAULT_FROM_EMAIL,
                [usuario.correo],
                fail_silently=False
            )

            messages.success(request, "Registro exitoso. Revisa tu correo para activar tu cuenta.")
            return redirect("login")
    else:
        form = RegistroUsuarioForm()

    return render(request, "auth/register.html", {"form": form})

def terminos_view(request):
    return render(request, "auth/terminos.html")

def privacidad_view(request):
    return render(request, "auth/privacidad.html")


def activar_cuenta(request, token):
    usuario = get_object_or_404(Usuario, token_activacion=token)

    # Validar si el token ha expirado (24 horas)
    if timezone.now() > usuario.token_creado_en + timedelta(hours=24):
        messages.error(request, "El enlace de activación ha expirado. Solicita uno nuevo.")
        return redirect("login")

    if usuario.es_activo:
        messages.info(request, "Tu cuenta ya está activa. Puedes iniciar sesión.")
    else:
        usuario.es_activo = True
        usuario.save()
        messages.success(request, "Tu cuenta ha sido activada correctamente. Ya puedes iniciar sesión.")

    return redirect("login")

