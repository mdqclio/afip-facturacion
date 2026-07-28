"""Fecha y hora de Argentina, independientes de la zona horaria del servidor.

ARCA opera en America/Argentina/Buenos_Aires. Usar datetime.now() pelado hace
que un servidor en UTC arme comprobantes con la fecha del día siguiente entre
las 21:00 y la medianoche hora argentina.
"""
import datetime

try:
    from zoneinfo import ZoneInfo

    TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:  # noqa: BLE001 - sin base tzdata en el sistema
    # Argentina no aplica horario de verano desde 2009: UTC-3 fijo es correcto.
    TZ_AR = datetime.timezone(datetime.timedelta(hours=-3), name="-03")


def ahora_ar():
    """Devuelve el datetime actual con la zona horaria argentina."""
    return datetime.datetime.now(TZ_AR)


def hoy_ar():
    """Devuelve la fecha de hoy en Argentina como date."""
    return ahora_ar().date()


def hoy_ar_afip():
    """Devuelve la fecha de hoy en Argentina en el formato AAAAMMDD que pide ARCA."""
    return hoy_ar().strftime("%Y%m%d")
