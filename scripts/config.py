"""
Configuración central del skill afip-facturacion.

La configuración se lee de un archivo JSON externo al repositorio. El archivo
nunca debe versionarse: contiene el CUIT, el punto de venta y las rutas al
certificado y a la clave privada.

Orden de resolución del archivo de configuración:

    1. ruta pasada explícitamente (--config)
    2. $AFIP_CONFIG
    3. $AFIP_HOME/emisor_config.json
    4. ~/afip/emisor_config.json

IMPORTANTE — ambiente por defecto: HOMOLOGACIÓN.
Producción solo se activa si el archivo de configuración declara
"ambiente": "produccion" (o si se exporta AFIP_ENV=prod). Ninguna URL de
producción es alcanzable con la configuración por defecto.
"""
import json
import os


AMBIENTES = {
    "homologacion": {
        "wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
        "wsfe": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx",
    },
    "produccion": {
        "wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
        "wsfe": "https://servicios1.afip.gov.ar/wsfev1/service.asmx",
    },
}

AMBIENTE_DEFAULT = "homologacion"

_ALIAS_AMBIENTE = {
    "homo": "homologacion",
    "homologacion": "homologacion",
    "homologación": "homologacion",
    "test": "homologacion",
    "testing": "homologacion",
    "prod": "produccion",
    "produccion": "produccion",
    "producción": "produccion",
    "production": "produccion",
}


def normalizar_ambiente(valor):
    """Normaliza el nombre del ambiente. Cualquier valor desconocido -> homologación."""
    if not valor:
        return AMBIENTE_DEFAULT
    return _ALIAS_AMBIENTE.get(str(valor).strip().lower(), AMBIENTE_DEFAULT)


def resolver_ruta_config(ruta=None):
    """Devuelve la ruta del archivo de configuración según el orden de resolución."""
    if ruta:
        return os.path.abspath(os.path.expanduser(ruta))
    if os.environ.get("AFIP_CONFIG"):
        return os.path.abspath(os.path.expanduser(os.environ["AFIP_CONFIG"]))
    home = os.environ.get("AFIP_HOME", os.path.expanduser("~/afip"))
    return os.path.abspath(os.path.join(os.path.expanduser(home), "emisor_config.json"))


class Config:
    """Configuración resuelta del emisor + ambiente."""

    def __init__(self, datos, ruta_config):
        self.ruta_config = ruta_config
        self.base_dir = os.path.dirname(ruta_config)
        self.datos = datos

        # El ambiente del archivo manda; AFIP_ENV solo se usa si el archivo no lo declara.
        self.ambiente = normalizar_ambiente(
            datos.get("ambiente") or os.environ.get("AFIP_ENV")
        )
        self.wsaa_url = AMBIENTES[self.ambiente]["wsaa"]
        self.wsfe_url = AMBIENTES[self.ambiente]["wsfe"]

        self.cuit = int(str(datos.get("cuit", 0)).replace("-", "").strip() or 0)
        # Sin valor declarado queda en None: el punto de venta no se adivina.
        _pto_vta = datos.get("punto_venta")
        self.punto_venta = int(_pto_vta) if _pto_vta not in (None, "") else None

        self.cert_path = self._ruta(datos.get("cert_path") or datos.get("certificado"))
        self.key_path = self._ruta(datos.get("key_path") or datos.get("clave_privada"))
        self.ta_cache_path = self._ruta(datos.get("ta_cache_path")) or os.path.join(
            self.base_dir, "ta_{}_{}.json".format(self.ambiente, self.cuit)
        )
        self.facturas_log_path = self._ruta(datos.get("facturas_log_path")) or os.path.join(
            self.base_dir, "facturas_log_{}.json".format(self.ambiente)
        )

        self.emisor = datos.get("emisor", datos)

    def _ruta(self, valor):
        if not valor:
            return None
        valor = os.path.expanduser(str(valor))
        if not os.path.isabs(valor):
            valor = os.path.join(self.base_dir, valor)
        return os.path.abspath(valor)

    @property
    def es_produccion(self):
        return self.ambiente == "produccion"

    def validar(self):
        """Valida lo mínimo indispensable para operar. Lanza ValueError."""
        faltan = []
        if not self.cuit:
            faltan.append("cuit")
        if not self.cert_path:
            faltan.append("cert_path")
        if not self.key_path:
            faltan.append("key_path")
        if faltan:
            raise ValueError(
                "Faltan campos en {}: {}".format(self.ruta_config, ", ".join(faltan))
            )
        for etiqueta, ruta in (("certificado", self.cert_path), ("clave privada", self.key_path)):
            if not os.path.exists(ruta):
                raise ValueError("No existe el {}: {}".format(etiqueta, ruta))

    def resumen(self):
        return (
            "Ambiente : {}\n"
            "WSAA     : {}\n"
            "WSFEv1   : {}\n"
            "CUIT     : {}\n"
            "Config   : {}\n"
            "Cert     : {}\n"
            "TA cache : {}"
        ).format(
            self.ambiente.upper(), self.wsaa_url, self.wsfe_url,
            self.cuit, self.ruta_config, self.cert_path, self.ta_cache_path,
        )


def cargar_config(ruta=None):
    """Carga y valida la configuración desde el archivo JSON externo."""
    ruta_config = resolver_ruta_config(ruta)
    if not os.path.exists(ruta_config):
        raise FileNotFoundError(
            "No se encontró {}\n"
            "Copiá config.example.json fuera del repositorio y completalo. "
            "Ver references/setup.md.".format(ruta_config)
        )
    with open(ruta_config, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return Config(datos, ruta_config)


# ---------------------------------------------------------------------------
# Compatibilidad con los módulos que todavía leen constantes a nivel de módulo
# (generar_pdf.py). Ambiente por defecto: homologación.
# ---------------------------------------------------------------------------
AFIP_HOME = os.environ.get("AFIP_HOME", os.path.expanduser("~/afip"))
EMISOR_CONFIG_PATH = resolver_ruta_config()
BASE_DIR = os.path.dirname(EMISOR_CONFIG_PATH)

try:
    _CFG = cargar_config()
    CUIT = _CFG.cuit
    PUNTO_VENTA = _CFG.punto_venta
    WSAA_URL = _CFG.wsaa_url
    WSFE_URL = _CFG.wsfe_url
    FACTURAS_LOG_PATH = _CFG.facturas_log_path
    TOKEN_CACHE_PATH = _CFG.ta_cache_path
    PRIVATE_KEY_PATH = _CFG.key_path
    CERTIFICATE_PATH = _CFG.cert_path
except (FileNotFoundError, ValueError, json.JSONDecodeError):
    _CFG = None
    CUIT = 0
    PUNTO_VENTA = 1
    WSAA_URL = AMBIENTES[AMBIENTE_DEFAULT]["wsaa"]
    WSFE_URL = AMBIENTES[AMBIENTE_DEFAULT]["wsfe"]
    FACTURAS_LOG_PATH = os.path.join(BASE_DIR, "facturas_log_homologacion.json")
    TOKEN_CACHE_PATH = os.path.join(BASE_DIR, "ta_homologacion.json")
    PRIVATE_KEY_PATH = None
    CERTIFICATE_PATH = None
