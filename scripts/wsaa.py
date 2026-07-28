"""
WSAA — Web Service de Autenticación y Autorización de ARCA/AFIP.

Genera el Ticket de Requerimiento de Acceso (TRA), lo firma en CMS/PKCS#7 con
el certificado + clave privada y obtiene el Ticket de Acceso (TA: token + sign).

El TA se cachea en disco y se reutiliza hasta su expiración (~12 h). ARCA
penaliza el pedido de un TA nuevo mientras hay uno vigente, así que nunca se
solicita uno nuevo si el cacheado sigue válido.
"""
import base64
import datetime
import json
import os
import time
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509 import load_pem_x509_certificate

import soap_client

NS_WSAA = "http://wsaa.view.sua.dvadac.desein.afip.gov"

# Margen antes del vencimiento a partir del cual se considera que el TA venció.
MARGEN_VENCIMIENTO = datetime.timedelta(minutes=10)


def crear_tra(service="wsfe", ttl_minutos=10):
    """Arma el XML del loginTicketRequest."""
    ahora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
    unique_id = str(int(time.time()))
    # generationTime con 10 minutos de tolerancia hacia atrás para absorber
    # desfasajes de reloj contra el servidor de ARCA.
    generation = (ahora - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S-03:00")
    expiration = (ahora + datetime.timedelta(minutes=ttl_minutos)).strftime("%Y-%m-%dT%H:%M:%S-03:00")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<loginTicketRequest version="1.0">'
        "<header>"
        "<uniqueId>{uid}</uniqueId>"
        "<generationTime>{gen}</generationTime>"
        "<expirationTime>{exp}</expirationTime>"
        "</header>"
        "<service>{svc}</service>"
        "</loginTicketRequest>"
    ).format(uid=unique_id, gen=generation, exp=expiration, svc=service).encode("utf-8")


def firmar_tra(tra_xml, cert_path, key_path):
    """Firma el TRA en CMS/PKCS#7 (firma adjunta, DER) y lo devuelve en base64."""
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    with open(cert_path, "rb") as f:
        certificate = load_pem_x509_certificate(f.read())

    firmado = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(tra_xml)
        .add_signer(certificate, private_key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )
    return base64.b64encode(firmado).decode("ascii")


def login_cms(wsaa_url, cms_b64, timeout=60):
    """Envía el TRA firmado al WSAA. Devuelve (token, sign, expiration, generation)."""
    respuesta = soap_client.llamar(
        wsaa_url,
        namespace=NS_WSAA,
        operacion="loginCms",
        cuerpo={"in0": cms_b64},
        soap_action="",
        timeout=timeout,
    )
    xml_ta = soap_client.elemento_a_dict(respuesta)
    if isinstance(xml_ta, dict):
        xml_ta = xml_ta.get("loginCmsReturn", "")
    if not xml_ta:
        raise soap_client.SoapError("WSAA devolvió una respuesta vacía")

    raiz = ET.fromstring(xml_ta)
    token = raiz.findtext(".//token")
    sign = raiz.findtext(".//sign")
    expiration = raiz.findtext(".//expirationTime")
    generation = raiz.findtext(".//generationTime")
    if not token or not sign:
        raise soap_client.SoapError("TA sin token/sign:\n{}".format(xml_ta[:1000]))
    return token, sign, expiration, generation


def _ta_vigente(cache, ambiente, cuit, service):
    """True si el TA cacheado corresponde a este ambiente/CUIT/servicio y no venció."""
    if cache.get("ambiente") != ambiente:
        return False
    if int(cache.get("cuit", 0)) != int(cuit):
        return False
    if cache.get("service") != service:
        return False
    try:
        exp = datetime.datetime.fromisoformat(cache["expiration"])
    except (KeyError, ValueError):
        return False
    ahora = datetime.datetime.now(exp.tzinfo)
    return ahora < exp - MARGEN_VENCIMIENTO


def obtener_credenciales(cfg, service="wsfe", forzar=False, verbose=True):
    """Devuelve (token, sign) reutilizando el TA cacheado mientras siga vigente."""
    ruta_cache = cfg.ta_cache_path

    if not forzar and os.path.exists(ruta_cache):
        try:
            with open(ruta_cache, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            cache = {}
        if _ta_vigente(cache, cfg.ambiente, cfg.cuit, service):
            if verbose:
                print("TA cacheado vigente hasta {} ({})".format(cache["expiration"], ruta_cache))
            return cache["token"], cache["sign"]
        if verbose and cache:
            print("TA cacheado vencido o de otro ambiente/CUIT; se pide uno nuevo.")

    if verbose:
        print("Solicitando TA nuevo a WSAA ({})...".format(cfg.wsaa_url))

    tra = crear_tra(service)
    cms = firmar_tra(tra, cfg.cert_path, cfg.key_path)
    token, sign, expiration, generation = login_cms(cfg.wsaa_url, cms)

    os.makedirs(os.path.dirname(ruta_cache) or ".", exist_ok=True)
    datos = {
        "ambiente": cfg.ambiente,
        "cuit": cfg.cuit,
        "service": service,
        "token": token,
        "sign": sign,
        "generation": generation,
        "expiration": expiration,
    }
    # El TA es una credencial: 0600 y escritura atómica.
    tmp = ruta_cache + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta_cache)

    if verbose:
        print("TA obtenido, válido hasta {} (cache: {})".format(expiration, ruta_cache))
    return token, sign


if __name__ == "__main__":
    import argparse

    from config import cargar_config

    parser = argparse.ArgumentParser(description="Obtener TA del WSAA")
    parser.add_argument("--config")
    parser.add_argument("--service", default="wsfe")
    parser.add_argument("--forzar", action="store_true",
                        help="pide un TA nuevo aunque haya uno vigente (ARCA lo penaliza)")
    args = parser.parse_args()

    cfg = cargar_config(args.config)
    cfg.validar()
    print(cfg.resumen())
    tok, sig = obtener_credenciales(cfg, args.service, forzar=args.forzar)
    print("Token: {}...".format(tok[:50]))
    print("Sign : {}...".format(sig[:50]))
