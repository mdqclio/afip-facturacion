"""
WSFEv1 — Facturación Electrónica de ARCA/AFIP.

Operaciones usadas por el flujo de emisión:
    FEDummy                 estado de los servidores
    FEParamGetPtosVenta     puntos de venta habilitados
    FECompUltimoAutorizado  último comprobante autorizado
    FECAESolicitar          solicitud de CAE
    FECompConsultar         consulta de un comprobante emitido
"""
import soap_client

NS_FEV1 = "http://ar.gov.afip.dif.FEV1/"

# Tipos de comprobante (RG 100/1415)
CBTE_FACTURA_C = 11
CBTE_NOTA_DEBITO_C = 12
CBTE_NOTA_CREDITO_C = 13

# Conceptos
CONCEPTO_PRODUCTOS = 1
CONCEPTO_SERVICIOS = 2
CONCEPTO_PRODUCTOS_Y_SERVICIOS = 3

# Documento del receptor
DOC_CONSUMIDOR_FINAL = 99

# Condición IVA del receptor (RG 5616). 5 = Consumidor Final.
COND_IVA_CONSUMIDOR_FINAL = 5


class WSFEError(RuntimeError):
    """Error de negocio devuelto por WSFEv1 (nodo Errors)."""

    def __init__(self, operacion, errores):
        self.operacion = operacion
        self.errores = errores
        detalle = "; ".join("{} - {}".format(c, m) for c, m in errores) or "sin detalle"
        super().__init__("{} devolvió errores: {}".format(operacion, detalle))


def _como_lista(valor):
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def extraer_errores(resultado):
    """Devuelve [(Code, Msg)] del nodo Errors."""
    errores = (resultado or {}).get("Errors") or {}
    return [(e.get("Code", ""), e.get("Msg", "")) for e in _como_lista(errores.get("Err"))]


def extraer_eventos(resultado):
    """Devuelve [(Code, Msg)] del nodo Events."""
    eventos = (resultado or {}).get("Events") or {}
    return [(e.get("Code", ""), e.get("Msg", "")) for e in _como_lista(eventos.get("Evt"))]


def extraer_observaciones(detalle):
    """Devuelve [(Code, Msg)] del nodo Observaciones de un FECAEDetResponse."""
    obs = (detalle or {}).get("Observaciones") or {}
    return [(o.get("Code", ""), o.get("Msg", "")) for o in _como_lista(obs.get("Obs"))]


class WSFEClient:
    """Cliente de WSFEv1. No reintenta FECAESolicitar: un reintento a ciegas
    puede duplicar comprobantes."""

    def __init__(self, cfg, token=None, sign=None, timeout=60):
        self.cfg = cfg
        self.url = cfg.wsfe_url
        self.token = token
        self.sign = sign
        self.timeout = timeout

    @property
    def auth(self):
        return {"Token": self.token, "Sign": self.sign, "Cuit": self.cfg.cuit}

    def _llamar(self, operacion, cuerpo=None):
        elemento = soap_client.llamar(
            self.url,
            namespace=NS_FEV1,
            operacion=operacion,
            cuerpo=cuerpo or {},
            soap_action=NS_FEV1 + operacion,
            timeout=self.timeout,
        )
        datos = soap_client.elemento_a_dict(elemento)
        if isinstance(datos, dict):
            # <OperacionResponse><OperacionResult>...</OperacionResult></...>
            clave = operacion + "Result"
            if clave in datos:
                return datos[clave]
        return datos

    # --- a. FEDummy -------------------------------------------------------
    def dummy(self):
        """Estado de AppServer / DbServer / AuthServer. No requiere Auth."""
        return self._llamar("FEDummy")

    # --- b. FEParamGetPtosVenta -------------------------------------------
    def puntos_venta(self):
        """Lista los puntos de venta habilitados. Lanza WSFEError si ARCA devuelve Errors."""
        res = self._llamar("FEParamGetPtosVenta", {"Auth": self.auth})
        errores = extraer_errores(res)
        if errores:
            raise WSFEError("FEParamGetPtosVenta", errores)
        result_get = (res or {}).get("ResultGet") or {}
        return _como_lista(result_get.get("PtoVenta")), extraer_eventos(res)

    # --- c. FECompUltimoAutorizado ----------------------------------------
    def ultimo_autorizado(self, punto_venta, cbte_tipo=CBTE_FACTURA_C):
        res = self._llamar("FECompUltimoAutorizado", {
            "Auth": self.auth,
            "PtoVta": int(punto_venta),
            "CbteTipo": int(cbte_tipo),
        })
        errores = extraer_errores(res)
        if errores:
            raise WSFEError("FECompUltimoAutorizado", errores)
        return int(res.get("CbteNro", 0)), extraer_eventos(res)

    # --- d. FECAESolicitar ------------------------------------------------
    def solicitar_cae(self, punto_venta, cbte_tipo, detalle):
        """Solicita el CAE de UN comprobante. Sin reintentos automáticos."""
        cuerpo = {
            "Auth": self.auth,
            "FeCAEReq": {
                "FeCabReq": {
                    "CantReg": 1,
                    "PtoVta": int(punto_venta),
                    "CbteTipo": int(cbte_tipo),
                },
                "FeDetReq": {"FECAEDetRequest": [detalle]},
            },
        }
        return self._llamar("FECAESolicitar", cuerpo)

    # --- e. FECompConsultar -----------------------------------------------
    def consultar_comprobante(self, punto_venta, cbte_tipo, cbte_nro):
        res = self._llamar("FECompConsultar", {
            "Auth": self.auth,
            "FeCompConsReq": {
                "CbteTipo": int(cbte_tipo),
                "CbteNro": int(cbte_nro),
                "PtoVta": int(punto_venta),
            },
        })
        errores = extraer_errores(res)
        if errores:
            raise WSFEError("FECompConsultar", errores)
        return (res or {}).get("ResultGet") or {}, extraer_eventos(res)


def detalle_factura_c(numero, importe, fecha, concepto=CONCEPTO_PRODUCTOS_Y_SERVICIOS,
                      doc_tipo=DOC_CONSUMIDOR_FINAL, doc_nro=0,
                      cond_iva_receptor=COND_IVA_CONSUMIDOR_FINAL,
                      fch_serv_desde=None, fch_serv_hasta=None, fch_vto_pago=None):
    """Arma el FECAEDetRequest de una Factura C.

    En Factura C el IVA no se discrimina: ImpIVA = 0, ImpTotConc = 0 y
    ImpNeto = ImpTotal. El orden de las claves es el del xsd:sequence de ARCA.
    """
    importe = round(float(importe), 2)
    detalle = {
        "Concepto": int(concepto),
        "DocTipo": int(doc_tipo),
        "DocNro": int(doc_nro),
        "CbteDesde": int(numero),
        "CbteHasta": int(numero),
        "CbteFch": fecha,
        "ImpTotal": "{:.2f}".format(importe),
        "ImpTotConc": "0.00",
        "ImpNeto": "{:.2f}".format(importe),
        "ImpOpEx": "0.00",
        "ImpTrib": "0.00",
        "ImpIVA": "0.00",
    }
    if int(concepto) in (CONCEPTO_SERVICIOS, CONCEPTO_PRODUCTOS_Y_SERVICIOS):
        detalle["FchServDesde"] = fch_serv_desde or fecha
        detalle["FchServHasta"] = fch_serv_hasta or fecha
        detalle["FchVtoPago"] = fch_vto_pago or fecha
    detalle["MonId"] = "PES"
    detalle["MonCotiz"] = 1
    detalle["CondicionIVAReceptorId"] = int(cond_iva_receptor)
    return detalle
