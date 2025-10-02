# dashboard/utils/billing.py
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthrange
from decimal import Decimal
from django.db import transaction
from dashboard.models import Periodo, Tarifa, Boleta, CuentaServicio

def ensure_period(anio: int, mes: int, venc_day: int = 15) -> Periodo:
    """Crea o devuelve el Periodo {anio, mes} con vencimiento en el día 'venc_day'."""
    _, last_day = monthrange(anio, mes)
    venc = date(anio, mes, min(venc_day, last_day))
    per, _ = Periodo.objects.get_or_create(anio=anio, mes=mes, defaults={"vencimiento": venc})
    return per

def tarifa_vigente_para(fecha: date) -> Tarifa | None:
    """Devuelve la tarifa vigente para esa fecha."""
    qs = Tarifa.objects.order_by("-vigente_desde")
    for t in qs:
        if t.vigente_desde <= fecha and (t.vigente_hasta is None or fecha <= t.vigente_hasta):
            return t
    return None

@transaction.atomic
def ensure_boletas_pendientes(cuenta: CuentaServicio, desde: date, hasta: date) -> list[Boleta]:
    """
    Por cada mes entre 'desde' y 'hasta' crea la boleta si no existe.
    Total = monto_base + mora (si aplica).
    """
    created = []
    y, m = desde.year, desde.month
    hoy = date.today()

    while (y < hasta.year) or (y == hasta.year and m <= hasta.month):
        per = ensure_period(y, m)
        if not Boleta.objects.filter(cuenta=cuenta, periodo=per).exists():
            fecha_mes = date(y, m, 1)
            tarifa = tarifa_vigente_para(fecha_mes)
            if tarifa is None:
                m = 1 if m == 12 else m + 1
                y = y + 1 if m == 1 else y
                continue

            base = tarifa.monto_base

            # ---- Cálculo de mora ----
            recargo = Decimal("0.00")
            if hoy > per.vencimiento:
                delta = relativedelta(hoy, per.vencimiento)
                meses_atraso = delta.years * 12 + delta.months
                # Si usas mora fija:
                if hasattr(tarifa, "recargo_mora_fijo") and tarifa.recargo_mora_fijo > 0:
                    recargo = (tarifa.recargo_mora_fijo * meses_atraso).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                # Si sigues con porcentaje:
                elif tarifa.recargo_mora_porcentaje > 0:
                    recargo = (base * (tarifa.recargo_mora_porcentaje/100) * meses_atraso).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            total = base + recargo

            b = Boleta.objects.create(
                cuenta=cuenta,
                periodo=per,
                tarifa=tarifa,
                monto_base=base,
                recargo=recargo,
                descuento=Decimal("0.00"),
                total=total,
                saldo_actual=total,
            )
            created.append(b)

        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y

    return created