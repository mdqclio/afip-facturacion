"""
Cliente SOAP mínimo para los web services de ARCA/AFIP.

Usa solo requests + xml.etree de la biblioteca estándar: no hace falta zeep ni
lxml, que no están disponibles en todos los entornos. Los WSDL de WSAA y WSFEv1
son document/literal y sus mensajes son estables, así que se arman a mano.
"""
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from ssl_fix import get_afip_session

NS_SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"


class SoapError(RuntimeError):
    """Fault SOAP o respuesta HTTP no exitosa."""


def _serializar(nombre, valor, ns_prefijo=""):
    """Serializa dict/list/escalar a XML. Los dicts conservan el orden de inserción,
    que es el orden exigido por los xsd:sequence de ARCA."""
    tag = "{}{}".format(ns_prefijo, nombre)
    if isinstance(valor, dict):
        hijos = "".join(_serializar(k, v, ns_prefijo) for k, v in valor.items())
        return "<{tag}>{hijos}</{tag}>".format(tag=tag, hijos=hijos)
    if isinstance(valor, (list, tuple)):
        # Una lista repite el mismo tag una vez por elemento.
        return "".join(_serializar(nombre, item, ns_prefijo) for item in valor)
    if valor is None:
        return "<{tag}/>".format(tag=tag)
    if isinstance(valor, bool):
        texto = "true" if valor else "false"
    else:
        texto = str(valor)
    return "<{tag}>{texto}</{tag}>".format(tag=tag, texto=escape(texto))


def _sin_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def elemento_a_dict(elem):
    """Convierte un Element en dict/list/str, descartando los namespaces.
    Los tags repetidos se agrupan en una lista."""
    hijos = list(elem)
    if not hijos:
        return (elem.text or "").strip()
    salida = {}
    for hijo in hijos:
        nombre = _sin_ns(hijo.tag)
        valor = elemento_a_dict(hijo)
        if nombre in salida:
            if not isinstance(salida[nombre], list):
                salida[nombre] = [salida[nombre]]
            salida[nombre].append(valor)
        else:
            salida[nombre] = valor
    return salida


def llamar(url, namespace, operacion, cuerpo=None, soap_action=None, timeout=60,
           ns_prefijo_cuerpo=True):
    """Ejecuta una operación SOAP 1.1 y devuelve el Element del cuerpo de la respuesta.

    cuerpo: dict con los parámetros de la operación (orden = orden del xsd:sequence).
    """
    prefijo = "m:" if ns_prefijo_cuerpo else ""
    interior = "".join(_serializar(k, v, prefijo) for k, v in (cuerpo or {}).items())
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="{ns_env}" xmlns:m="{ns}">'
        "<soapenv:Header/>"
        "<soapenv:Body><{p}{op}>{interior}</{p}{op}></soapenv:Body>"
        "</soapenv:Envelope>"
    ).format(ns_env=NS_SOAPENV, ns=namespace, p=prefijo, op=operacion, interior=interior)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"{}"'.format(soap_action if soap_action is not None else ""),
        "User-Agent": "afip-facturacion/1.0",
    }

    session = get_afip_session()
    resp = session.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout)

    try:
        raiz = ET.fromstring(resp.content)
    except ET.ParseError:
        raise SoapError(
            "Respuesta no-XML de {} (HTTP {}):\n{}".format(url, resp.status_code, resp.text[:2000])
        )

    body = raiz.find("{%s}Body" % NS_SOAPENV)
    if body is None:
        raise SoapError("Respuesta SOAP sin Body:\n{}".format(resp.text[:2000]))

    fault = body.find("{%s}Fault" % NS_SOAPENV)
    if fault is not None:
        detalle = elemento_a_dict(fault)
        raise SoapError("SOAP Fault en {}: {}".format(operacion, detalle))

    if resp.status_code >= 400:
        raise SoapError("HTTP {} en {}:\n{}".format(resp.status_code, operacion, resp.text[:2000]))

    hijos = list(body)
    if not hijos:
        raise SoapError("Body SOAP vacío en {}".format(operacion))
    return hijos[0]
