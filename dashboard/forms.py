from django import forms
from .models import Usuario
from dashboard.models import Denuncia, Ubicacion, Barrio, CategoriaDenuncia, Permiso
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.utils import timezone
import datetime

ALLOWED_EXTS = ('.jpg', '.jpeg', '.png', '.pdf')
MAX_FILE_MB = 5
Q6 = Decimal("0.000001")

class RegistroUsuarioForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '********'
        }),
        label="Contraseña"
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '********'
        }),
        label="Confirmar contraseña"
    )

    class Meta:
        model = Usuario
        fields = ['nombre', 'apellido', 'correo', 'telefono']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ingresa tu nombre'
            }),
            'apellido': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ingresa tu apellido'
            }),
            'correo': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ingresa tu correo'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número de teléfono'
            }),
        }

    def clean_password2(self):
        p1 = self.cleaned_data.get('password')
        p2 = self.cleaned_data.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return p2


class DenunciaForm(forms.ModelForm):
    # Mapa (opcional)
    latitud = forms.DecimalField(required=False, max_digits=10, decimal_places=8)
    longitud = forms.DecimalField(required=False, max_digits=11, decimal_places=8)

    # Texto (OBLIGATORIO)
    direccion = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class':'form-control','placeholder':'Referencia / Calle'})
    )
    barrio = forms.ModelChoiceField(
        required=True,
        queryset=Barrio.objects.all(),
        widget=forms.Select(attrs={'class':'form-select'})
    )

    class Meta:
        model = Denuncia
        fields = ['categoria','fecha_hecho','descripcion','evidencia','es_anonima',
                  'latitud','longitud','direccion','barrio']
        widgets = {
            'categoria':   forms.Select(attrs={'class':'form-select'}),
            'fecha_hecho': forms.DateInput(attrs={'type':'date','class':'form-control','required': True}),
            'descripcion': forms.Textarea(attrs={'class':'form-control','rows':4}),
            'evidencia':   forms.ClearableFileInput(attrs={'class':'form-control'}),
            'es_anonima':  forms.CheckboxInput(attrs={'class':'form-check-input'}),
        }
        labels = {'fecha_hecho': 'Fecha del hecho'}

    def clean_fecha_hecho(self):
        fh = self.cleaned_data.get('fecha_hecho')
        if not fh:
            raise ValidationError("La fecha del hecho es obligatoria.")
        if fh > timezone.now().date():
            raise ValidationError("La fecha del hecho no puede ser futura.")
        return fh

    def clean_descripcion(self):
        desc = (self.cleaned_data.get('descripcion') or '').strip()
        if len(desc) < 10:
            raise ValidationError("La descripción debe tener al menos 10 caracteres.")
        return desc

    def clean_evidencia(self):
        f = self.cleaned_data.get('evidencia')
        if not f:
            return f
        if f.size > MAX_FILE_MB * 1024 * 1024:
            raise ValidationError(f"El archivo no debe superar {MAX_FILE_MB} MB.")
        name = f.name.lower()
        if not any(name.endswith(ext) for ext in ALLOWED_EXTS):
            raise ValidationError("Solo se permiten archivos JPG, PNG o PDF.")
        return f

    def clean(self):
        cleaned = super().clean()
        lat = cleaned.get('latitud')
        lng = cleaned.get('longitud')
        direccion = (cleaned.get('direccion') or '').strip()
        barrio = cleaned.get('barrio')

        # Requeridos: dirección + barrio SIEMPRE
        if not direccion:
            raise ValidationError("La dirección es obligatoria.")
        if not barrio:
            raise ValidationError("El barrio es obligatorio.")

        # Mapa: opcional, pero si se usa debe venir completo (lat y lng)
        if (lat is None) ^ (lng is None):
            raise ValidationError("Coordenadas incompletas. Marca un punto en el mapa nuevamente.")

        # No hay exclusión: se permite texto + mapa juntos
        return cleaned
    

class DenunciaEditForm(forms.ModelForm):
    direccion = forms.CharField(required=False, max_length=255, label="Dirección")
    barrio = forms.ModelChoiceField(queryset=Barrio.objects.all(), required=False, label="Barrio")
    latitud  = forms.DecimalField(required=False, max_digits=9, decimal_places=6, label="Latitud",
                                  widget=forms.HiddenInput())
    longitud = forms.DecimalField(required=False, max_digits=9, decimal_places=6, label="Longitud",
                                  widget=forms.HiddenInput())
    class Meta:
        model = Denuncia
        fields = ["categoria", "descripcion", "fecha_hecho", "es_anonima", "evidencia"]
        widgets = {
            "categoria": forms.Select(attrs={"class": "form-select"}),
            "descripcion": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
            "fecha_hecho": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "es_anonima": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "evidencia": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Estilos para campos extra si no usas NumberInput arriba
        self.fields["direccion"].widget.attrs.setdefault("class", "form-control")
        self.fields["barrio"].widget.attrs.setdefault("class", "form-select")

        # Formatear iniciales a 6 decimales para evitar que el browser envíe más de 6
        for name in ("latitud", "longitud"):
            val = self.initial.get(name, None)
            if val not in (None, ""):
                try:
                    d = Decimal(str(val)).quantize(Q6, rounding=ROUND_HALF_UP)
                    # convertir a string limpio sin notación científica
                    self.initial[name] = format(d, "f")
                except Exception:
                    pass  # si falla, lo dejamos como viene

    def _clean_coord(self, name, min_abs, max_abs):
        """Normaliza, redondea a 6 decimales y valida rango."""
        raw = self.data.get(self.add_prefix(name), "").strip()
        if raw == "":
            return None  # campo vacío es permitido

        # Cambiar coma por punto si el user usa coma decimal
        raw = raw.replace(",", ".")

        try:
            dec = Decimal(raw)
        except InvalidOperation:
            raise forms.ValidationError("Valor no válido.")

        # Rango
        if not (-max_abs <= dec <= max_abs):
            raise forms.ValidationError(f"Debe estar entre {-max_abs} y {max_abs}.")

        # Redondear a 6 decimales para ajustarse a decimal_places=6
        dec = dec.quantize(Q6, rounding=ROUND_HALF_UP)
        return dec

    def clean_latitud(self):
        val = self._clean_coord("latitud", -90, 90)
        return val

    def clean_longitud(self):
        val = self._clean_coord("longitud", -180, 180)
        return val
  
    def clean_descripcion(self):
        desc = (self.cleaned_data.get("descripcion") or "").strip()
        if len(desc) < 10:
            raise ValidationError("La descripción debe tener al menos 10 caracteres.")
        return desc

    def clean_fecha_hecho(self):
        fh = self.cleaned_data.get("fecha_hecho")
        if not fh:
            raise ValidationError("La fecha del hecho es obligatoria.")
        if fh > timezone.now().date():
            raise ValidationError("La fecha del hecho no puede ser futura.")
        return fh



    def clean(self):
        cleaned = super().clean()
        lat = cleaned.get("latitud")
        lng = cleaned.get("longitud")

        # 1) Coordenadas: ambas o ninguna
        if (lat is None) ^ (lng is None):
            raise ValidationError("Coordenadas incompletas. Marca un punto en el mapa nuevamente.")

        # 2) Dirección y barrio: SIEMPRE obligatorios en edición (como al crear)
        direccion = (cleaned.get("direccion") or "").strip()
        barrio = cleaned.get("barrio")

        # Si el usuario intenta borrarlos, error aunque la instancia tenga ubicación previa
        if not direccion:
            raise ValidationError({"direccion": "La dirección es obligatoria."})
        if not barrio:
            raise ValidationError({"barrio": "El barrio es obligatorio."})

        return cleaned
    
        
class AdminDenunciaEstadoForm(forms.ModelForm):
    class Meta:
        model = Denuncia
        fields = ["estado", "rechazo_motivo", "resolucion_nota", "resolucion_evidencia"]
        widgets = {
            "rechazo_motivo": forms.Textarea(attrs={"rows":3}),
            "resolucion_nota": forms.Textarea(attrs={"rows":3}),
        }
        

class PermisoForm(forms.ModelForm):
    # Ubicación (texto obligatorio; mapa opcional lo manejas en la vista)
    direccion = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Referencia / Calle'
        })
    )
    barrio = forms.ModelChoiceField(
        required=True,
        queryset=Barrio.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Permiso
        fields = [
            "tipo_permiso", "descripcion",
            "dpi_frente", "dpi_reverso", "evidencia_lugar",
            "requiere_pmt", "requiere_conos",
            "comienza_en", "termina_en",
            "direccion", "barrio",
        ]
        widgets = {
            "tipo_permiso":   forms.Select(attrs={"class": "form-select"}),
            "descripcion":    forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "dpi_frente":     forms.ClearableFileInput(attrs={"class": "form-control"}),
            "dpi_reverso":    forms.ClearableFileInput(attrs={"class": "form-control"}),
            "evidencia_lugar":forms.ClearableFileInput(attrs={"class": "form-control"}),
            "requiere_pmt":   forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "requiere_conos": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "comienza_en":    forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "termina_en":     forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        }
        labels = {
            "dpi_frente": "DPI (frente)",
            "dpi_reverso": "DPI (reverso)",
            "evidencia_lugar": "Evidencia del lugar",
            "comienza_en": "Inicio del permiso",
            "termina_en": "Fin del permiso",
        }

    # ---------- Validaciones por campo ----------
    def clean_descripcion(self):
        desc = (self.cleaned_data.get("descripcion") or "").strip()
        if len(desc) < 10:
            raise ValidationError("La descripción debe tener al menos 10 caracteres.")
        return desc

    def _validar_archivo(self, f, nombre):
        if not f:
            return f
        if f.size > MAX_FILE_MB * 1024 * 1024:
            raise ValidationError(f"{nombre}: el archivo no debe superar {MAX_FILE_MB} MB.")
        name = f.name.lower()
        if not any(name.endswith(ext) for ext in ALLOWED_EXTS):
            raise ValidationError(f"{nombre}: solo se permiten archivos JPG, PNG o PDF.")
        return f

    def clean_dpi_frente(self):
        return self._validar_archivo(self.cleaned_data.get("dpi_frente"), "DPI frente")

    def clean_dpi_reverso(self):
        return self._validar_archivo(self.cleaned_data.get("dpi_reverso"), "DPI reverso")

    def clean_evidencia_lugar(self):
        return self._validar_archivo(self.cleaned_data.get("evidencia_lugar"), "Evidencia del lugar")

    def clean_comienza_en(self):
        ini = self.cleaned_data.get("comienza_en")
        if not ini:
            raise ValidationError("Indica la fecha y hora de inicio del permiso.")
        # Permitimos 5 minutos de tolerancia respecto a 'ahora'
        ahora = timezone.now()
        tolerancia = datetime.timedelta(minutes=5)
        if ini < (ahora - tolerancia):
            raise ValidationError("El inicio no puede estar en el pasado.")
        return ini

    def clean_termina_en(self):
        fin = self.cleaned_data.get("termina_en")
        if not fin:
            raise ValidationError("Indica la fecha y hora de fin del permiso.")
        return fin

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dpi_frente"].required = True
        self.fields["dpi_reverso"].required = True
        
    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("dpi_frente"):
            raise ValidationError({"dpi_frente": "Debes subir el DPI (frente)."})
        if not cleaned.get("dpi_reverso"):
            raise ValidationError({"dpi_reverso": "Debes subir el DPI (reverso)."})
        return cleaned

    # ---------- Validación cruzada ----------
    def clean(self):
        cleaned = super().clean()
        ini = cleaned.get("comienza_en")
        fin = cleaned.get("termina_en")

        # compara solo si ambos pasaron sus clean_*
        if ini and fin and fin < ini:
            # Puedes asociarlo al campo para que pinte el error junto al input
            self.add_error("termina_en", "Debe ser igual o posterior a la fecha de inicio.")

        # Dirección y barrio ya son required=True, pero por si vienen vacíos por HTML:
        dir_ = (cleaned.get("direccion") or "").strip()
        if not dir_:
            self.add_error("direccion", "La dirección es obligatoria.")
        if not cleaned.get("barrio"):
            self.add_error("barrio", "El barrio es obligatorio.")

        return cleaned


class PermisoEditForm(forms.ModelForm):
    # Ubicación
    direccion = forms.CharField(required=True, max_length=255, label="Dirección",
                                widget=forms.TextInput(attrs={"class":"form-control"}))
    barrio = forms.ModelChoiceField(required=True, queryset=Barrio.objects.all(), label="Barrio",
                                    widget=forms.Select(attrs={"class":"form-select"}))
    latitud  = forms.DecimalField(required=False, max_digits=9, decimal_places=6,
                                  widget=forms.HiddenInput())
    longitud = forms.DecimalField(required=False, max_digits=9, decimal_places=6,
                                  widget=forms.HiddenInput())

    class Meta:
        model = Permiso
        fields = [
            "tipo_permiso", "descripcion",
            "dpi_frente", "dpi_reverso", "evidencia_lugar",
            "requiere_pmt", "requiere_conos",
            "comienza_en", "termina_en",
        ]
        widgets = {
            "tipo_permiso": forms.Select(attrs={"class": "form-select"}),
            "descripcion":  forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "dpi_frente":   forms.FileInput(attrs={"class": "form-control"}),
            "dpi_reverso":  forms.FileInput(attrs={"class": "form-control"}),
            "evidencia_lugar": forms.FileInput(attrs={"class": "form-control"}),
            "requiere_pmt":   forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "requiere_conos": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "comienza_en":  forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "termina_en":   forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        }

    # ===== Validaciones =====
    def clean_descripcion(self):
        desc = (self.cleaned_data.get("descripcion") or "").strip()
        if len(desc) < 10:
            raise ValidationError("La descripción debe tener al menos 10 caracteres.")
        return desc

    def _validar_archivo(self, f, nombre):
        if not f:
            return f
        if f.size > MAX_FILE_MB * 1024 * 1024:
            raise ValidationError(f"{nombre}: el archivo no debe superar {MAX_FILE_MB} MB.")
        if not any(f.name.lower().endswith(ext) for ext in ALLOWED_EXTS):
            raise ValidationError(f"{nombre}: solo se permiten archivos JPG, PNG o PDF.")
        return f

    def clean_dpi_frente(self):
        return self._validar_archivo(self.cleaned_data.get("dpi_frente"), "DPI frente")

    def clean_dpi_reverso(self):
        return self._validar_archivo(self.cleaned_data.get("dpi_reverso"), "DPI reverso")

    def clean_evidencia_lugar(self):
        return self._validar_archivo(self.cleaned_data.get("evidencia_lugar"), "Evidencia del lugar")

    def _clean_coord(self, name, min_abs, max_abs):
        raw = (self.data.get(self.add_prefix(name)) or "").strip()
        if raw == "":
            return None
        raw = raw.replace(",", ".")
        try:
            dec = Decimal(raw)
        except InvalidOperation:
            raise ValidationError("Valor no válido.")
        if not (-max_abs <= dec <= max_abs):
            raise ValidationError(f"Debe estar entre {-max_abs} y {max_abs}.")
        return dec.quantize(Q6, rounding=ROUND_HALF_UP)

    def clean_latitud(self):
        return self._clean_coord("latitud", -90, 90)

    def clean_longitud(self):
        return self._clean_coord("longitud", -180, 180)

    def clean(self):
        cleaned = super().clean()

        # Fechas coherentes
        ini = cleaned.get("comienza_en")
        fin = cleaned.get("termina_en")
        if ini and fin and fin < ini:
            raise ValidationError({"termina_en": "Debe ser igual o posterior al inicio."})

        # Dirección y barrio: SIEMPRE obligatorios en edición (como al crear)
        direccion = (cleaned.get("direccion") or "").strip()
        barrio = cleaned.get("barrio")
        if not direccion:
            raise ValidationError({"direccion": "La dirección es obligatoria."})
        if not barrio:
            raise ValidationError({"barrio": "El barrio es obligatorio."})

        # Coordenadas: ambas o ninguna
        lat = cleaned.get("latitud")
        lng = cleaned.get("longitud")
        if (lat is None) ^ (lng is None):
            raise ValidationError("Coordenadas incompletas. Marca un punto en el mapa nuevamente.")

        return cleaned
    
    
class AdminPermisoEstadoForm(forms.ModelForm):
    class Meta:
        model = Permiso
        fields = ["estado", "aceptacion_nota", "permiso_adjunto", "observaciones"]
        widgets = {
            "estado": forms.Select(attrs={"class": "form-select", "id": "id_estado"}),
            "aceptacion_nota": forms.Textarea(attrs={"class":"form-control", "rows": 3}),
            "permiso_adjunto": forms.ClearableFileInput(attrs={"class":"form-control"}),
            "observaciones": forms.Textarea(attrs={"class":"form-control", "rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        estado = (cleaned.get("estado") or "").strip()

        # Solo se permite/usa nota y adjunto cuando estado == "aceptada"
        if estado != "aceptada":
            cleaned["aceptacion_nota"] = self.instance.aceptacion_nota
            cleaned["permiso_adjunto"] = self.instance.permiso_adjunto

        # Descomentar para hacer la nota cobligatoria:
        # if estado == "aceptada" and not nota:
        #     raise ValidationError({"aceptacion_nota": "Debes escribir una nota de aceptación."})

        return cleaned
    

class VincularCuentaForm(forms.Form):
    nit = forms.CharField(max_length=20, label="NIT")
    titular = forms.CharField(
        max_length=120,
        label="Titular (opcional)",
        required=False
    )
    