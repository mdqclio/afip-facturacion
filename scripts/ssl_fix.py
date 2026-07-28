"""
Sesión HTTPS para los servidores de ARCA/AFIP.

Algunos servidores de ARCA negocian claves Diffie-Hellman por debajo del nivel
de seguridad que OpenSSL 3 acepta por defecto (DH_KEY_TOO_SMALL). Se baja el
SECLEVEL a 1 para poder completar el handshake, PERO se mantiene la validación
del certificado y del hostname: por el canal viajan el token y el sign del TA,
así que desactivar la verificación abriría la puerta a un MITM.
"""
import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context


class AFIPSSLAdapter(HTTPAdapter):
    """Adapter con SECLEVEL=1 y verificación de certificado intacta."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._contexto()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._contexto()
        return super().proxy_manager_for(*args, **kwargs)

    @staticmethod
    def _contexto():
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx


def get_afip_session():
    """Retorna una session de requests configurada para ARCA/AFIP."""
    session = requests.Session()
    session.mount("https://", AFIPSSLAdapter())
    return session
