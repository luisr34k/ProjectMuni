# dashboard/models.py
from django.utils import timezone
from django.core.exceptions import ValidationError
import uuid
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

ACTOR_CHOICES = [
    ('ciudadano', 'Ciudadano'),
    ('administrador', 'Administrador'),
    ('sistema', 'Sistema'),
]


class UsuarioManager(BaseUserManager):
    def create_user(self, correo, nombre, apellido, password=None, **extra_fields):
        if not correo:
            raise ValueError('El usuario debe tener un correo electrónico')
        correo = self.normalize_email(correo)
        user = self.model(correo=correo, nombre=nombre, apellido=apellido, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, correo, nombre, apellido, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('es_activo', True)
        return self.create_user(correo, nombre, apellido, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    TIPO_USUARIO_CHOICES = [
        ('ciudadano', 'Ciudadano'),
        ('administrador', 'Administrador'),
    ]

    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    correo = models.EmailField(unique=True, max_length=150)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    es_activo = models.BooleanField(default=False)
    token_activacion = models.UUIDField(default=uuid.uuid4, editable=False)
    token_creado_en = models.DateTimeField(default=timezone.now)  # Fecha para validar 24h
    tipo_usuario = models.CharField(max_length=20, choices=TIPO_USUARIO_CHOICES, default='ciudadano')
    creado_en = models.DateTimeField(auto_now_add=True)

    # Requeridos por Django
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = 'correo'
    REQUIRED_FIELDS = ['nombre', 'apellido', 'telefono']

    objects = UsuarioManager()

    def __str__(self):
        return self.correo


class Barrio(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    def __str__(self): return self.nombre


class Ubicacion(models.Model):
    latitud = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitud = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    direccion = models.TextField(blank=True, null=True)
    barrio = models.ForeignKey(Barrio, null=True, blank=True, on_delete=models.SET_NULL)
    def __str__(self): return self.direccion or f"{self.latitud}, {self.longitud}"


class CategoriaDenuncia(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self): return self.nombre


class Denuncia(models.Model):
    ESTADOS = [
        ('enviada', 'Enviada'),
        ('en revisión', 'En revisión'),
        ('en proceso', 'En proceso'),
        ('resuelta', 'Resuelta'),
        ('rechazada', 'Rechazada'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    categoria = models.ForeignKey('CategoriaDenuncia', on_delete=models.PROTECT)
    descripcion = models.TextField()
    fecha_hecho = models.DateField()
    es_anonima = models.BooleanField(default=False)

    estado = models.CharField(max_length=20, choices=ESTADOS, default='enviada')

    ubicacion = models.ForeignKey('Ubicacion', on_delete=models.SET_NULL, null=True, blank=True)
    evidencia = models.FileField(upload_to='denuncias/evidencias/', null=True, blank=True)

    # Rechazo
    rechazo_motivo = models.TextField(blank=True, default="")

    # Resolución (opcionales)
    resolucion_nota = models.TextField(blank=True, default="")
    resolucion_evidencia = models.FileField(upload_to='denuncias/resoluciones/', null=True, blank=True)
    resuelto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='denuncias_resueltas'
    )

    creada_en = models.DateTimeField(auto_now_add=True)
    finalizada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['estado']),
            models.Index(fields=['creada_en']),
        ]

    def __str__(self):
        return f"Denuncia #{self.id} - {self.categoria}"

    def marcar_resuelta(self, usuario=None):
        self.estado = 'resuelta'
        if not self.finalizada_en:
            self.finalizada_en = timezone.now()
        if usuario and not self.resuelto_por:
            self.resuelto_por = usuario

    def marcar_rechazada(self, motivo: str):
        self.estado = 'rechazada'
        self.rechazo_motivo = motivo
        # No fijamos finalizada_en obligatoriamente; opcional si quieres:
        # if not self.finalizada_en:
        #     self.finalizada_en = timezone.now()
    
    def log(self, usuario, accion: str):
        from .models import BitacoraDenuncia
        BitacoraDenuncia.objects.create(
            denuncia=self,
            usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
            accion=accion[:1000],  # por si te pasas de largo
        )


class TipoPermiso(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    def __str__(self):
        return self.nombre


class BitacoraDenuncia(models.Model):
    denuncia = models.ForeignKey('Denuncia', on_delete=models.CASCADE, related_name='bitacoras')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.TextField()
    # --- CAMPOS NUEVOS PARA ENRIQUECER ---
    estado_anterior = models.CharField(max_length=20, blank=True, default="")
    estado_nuevo = models.CharField(max_length=20, blank=True, default="")
    cambios = models.JSONField(default=dict, blank=True)     # {"campo": ["antes","despues"]}
    actor = models.CharField(max_length=20, choices=ACTOR_CHOICES, blank=True, default="")
    ip = models.CharField(max_length=45, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    # --------------------------------------
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Bitácora {self.denuncia_id}"

    class Meta:
        indexes = [
            models.Index(fields=['fecha']),
        ]


class Permiso(models.Model):
    ESTADOS = [
        ('enviada', 'Enviada'),
        ('revisada', 'Revisada'),
        ('aceptada', 'Aceptada'),
        ('en proceso', 'En proceso'),
        ('finalizada', 'Finalizada'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    ubicacion = models.ForeignKey('Ubicacion', on_delete=models.SET_NULL, null=True, blank=True)
    tipo_permiso = models.ForeignKey('TipoPermiso', on_delete=models.PROTECT)
    descripcion = models.TextField(blank=True, default='')

    # Archivos / adjuntos (entrada del ciudadano)
    dpi_frente = models.FileField(upload_to='permisos/dpi/', null=True, blank=True)
    dpi_reverso = models.FileField(upload_to='permisos/dpi/', null=True, blank=True)
    evidencia_lugar = models.FileField(upload_to='permisos/evidencia_lugar/', null=True, blank=True)

    # Operación
    observaciones = models.TextField(blank=True, default='')
    requiere_pmt = models.BooleanField(default=False)
    requiere_conos = models.BooleanField(default=False)

    # Estado del trámite
    estado = models.CharField(max_length=20, choices=ESTADOS, default='enviada')
    visible_en_mapa = models.BooleanField(default=False)

    # >>> NUEVO: datos de aceptación (equivalente a “resolución” en Denuncia)
    aceptacion_nota = models.TextField(blank=True, default='')
    permiso_adjunto = models.FileField(upload_to='permisos/adjuntos/', null=True, blank=True)
    aceptado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='permisos_aceptados'
    )
    
    creado_en = models.DateTimeField(auto_now_add=True)
    comienza_en = models.DateTimeField()  
    termina_en  = models.DateTimeField()
    finalizado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['estado']),
            models.Index(fields=['creado_en']),
        ]

    def clean(self):
        super().clean()
        if self.comienza_en and self.termina_en and self.termina_en < self.comienza_en:
            raise ValidationError({"termina_en": "Debe ser igual o posterior a la fecha de inicio."})
        
    def __str__(self):
        return f"Permiso #{self.id} - {self.tipo_permiso}"

    # Helpers opcionales (similares a Denuncia)
    def marcar_aceptada(self, usuario=None, nota=''):
        self.estado = 'aceptada'
        if nota:
            self.aceptacion_nota = nota
        if usuario and not self.aceptado_por:
            self.aceptado_por = usuario

    def marcar_finalizada(self):
        self.estado = 'finalizada'
        if not self.finalizado_en:
            from django.utils import timezone
            self.finalizado_en = timezone.now()


class BitacoraPermiso(models.Model):
    permiso = models.ForeignKey('Permiso', on_delete=models.CASCADE, related_name='bitacoras')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.TextField()
    # --- NUEVOS CAMPOS (igual que en BitacoraDenuncia) ---
    estado_anterior = models.CharField(max_length=20, blank=True, default="")
    estado_nuevo = models.CharField(max_length=20, blank=True, default="")
    cambios = models.JSONField(default=dict, blank=True)     # {"campo": ["antes","despues"]}
    actor = models.CharField(max_length=20, choices=ACTOR_CHOICES, blank=True, default="")
    ip = models.CharField(max_length=45, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    # ------------------------------------------------------
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Bitácora Permiso {self.permiso_id}"

    class Meta:
        indexes = [
            models.Index(fields=['fecha']),
        ]
        
 
class CuentaServicio(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    titular = models.CharField(max_length=120)
    nit = models.CharField(max_length=20, blank=True, default='')
    codigo_catastral = models.CharField(max_length=50, blank=True, default='')
    ubicacion = models.ForeignKey('Ubicacion', null=True, blank=True, on_delete=models.SET_NULL)
    activa = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['usuario']),
            models.Index(fields=['activa']),
        ]

class Tarifa(models.Model):
    nombre = models.CharField(max_length=60)
    monto_base = models.DecimalField(max_digits=10, decimal_places=2)     # ej. 6.00
    recargo_mora_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recargo_mora_fijo = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # ej. 1.00
    vigente_desde = models.DateField()
    vigente_hasta = models.DateField(null=True, blank=True)

class Periodo(models.Model):
    anio = models.IntegerField()
    mes = models.IntegerField()
    vencimiento = models.DateField()

    @property
    def etiqueta(self): return f"{self.anio}-{self.mes:02d}"

    class Meta:
        unique_together = [('anio', 'mes')]
        indexes = [models.Index(fields=['anio', 'mes'])]

class Boleta(models.Model):
    ESTADOS = [('pendiente','Pendiente'),('parcial','Parcial'),('pagada','Pagada'),('anulada','Anulada')]
    cuenta = models.ForeignKey(CuentaServicio, on_delete=models.CASCADE, related_name='boletas')
    periodo = models.ForeignKey(Periodo, on_delete=models.PROTECT)
    tarifa = models.ForeignKey(Tarifa, on_delete=models.PROTECT)
    monto_base = models.DecimalField(max_digits=10, decimal_places=2)
    recargo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    saldo_actual = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente')
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('cuenta', 'periodo')]
        indexes = [
            models.Index(fields=['cuenta', 'estado']),
            models.Index(fields=['periodo']),
            models.Index(fields=['creada_en']),
        ]

    # ---- Helpers coherencia ----
    def recalc_total(self):
        tot = (self.monto_base or Decimal('0')) + (self.recargo or Decimal('0')) - (self.descuento or Decimal('0'))
        self.total = tot
        # si no tiene aplicaciones todavía, el saldo = total
        if not self.pk or not self.aplicaciones.exists():
            self.saldo_actual = tot

    def aplicar(self, monto: Decimal) -> Decimal:
        """
        Aplica 'monto' a esta boleta.
        Devuelve el SOBRANTE si no cupo todo.
        """
        if self.estado in ('pagada', 'anulada'):
            return monto

        pendiente = self.saldo_actual
        if pendiente <= 0:
            self.estado = 'pagada'
            self.save(update_fields=['estado'])
            return monto

        apli = min(pendiente, monto)
        nuevo_saldo = pendiente - apli
        self.saldo_actual = nuevo_saldo
        self.estado = 'pagada' if nuevo_saldo <= 0 else 'parcial'
        self.save(update_fields=['saldo_actual', 'estado'])
        return monto - apli

class Pago(models.Model):
    METODOS = [('caja','Caja'),('transferencia','Transferencia'),('tarjeta','Tarjeta'),('online','Online')]
    cuenta = models.ForeignKey(CuentaServicio, on_delete=models.PROTECT, related_name='pagos')
    fecha = models.DateTimeField(auto_now_add=True)
    metodo = models.CharField(max_length=20, choices=METODOS)
    referencia = models.CharField(max_length=100, blank=True, default='')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    usuario_registra = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    observaciones = models.TextField(blank=True, default='')

    def distribuir_en_boletas(self):
        """
        Reparte self.monto a boletas pendientes/parciales de la cuenta (FIFO por periodo).
        Crea AplicacionPago por cada asignación.
        """
        restante = Decimal(self.monto)
        if restante <= 0:
            return

        boletas = (Boleta.objects
                   .filter(cuenta=self.cuenta, estado__in=['pendiente', 'parcial'])
                   .select_related('periodo')
                   .order_by('periodo__anio', 'periodo__mes', 'creada_en'))

        with transaction.atomic():
            for b in boletas:
                if restante <= 0:
                    break
                antes = b.saldo_actual
                restante = b.aplicar(restante)
                aplicado = antes - b.saldo_actual
                if aplicado > 0:
                    AplicacionPago.objects.create(
                        pago=self, boleta=b, monto_aplicado=aplicado
                    )

class AplicacionPago(models.Model):
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name='aplicaciones')
    boleta = models.ForeignKey(Boleta, on_delete=models.PROTECT, related_name='aplicaciones')
    monto_aplicado = models.DecimalField(max_digits=10, decimal_places=2)

class TransaccionOnline(models.Model):
    pago = models.OneToOneField(Pago, on_delete=models.CASCADE, related_name='transaccion', null=True, blank=True)
    gateway = models.CharField(max_length=50, default='Recurrente')
    orden_id = models.CharField(max_length=100)      # ID que devuelve Recurrente (payment_intent id)
    estado = models.CharField(max_length=30)         # pending, success, failed
    payload = models.JSONField(default=dict, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['orden_id']),
            models.Index(fields=['estado']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['orden_id'], name='uniq_recurrente_orden_id')
        ]
        
        