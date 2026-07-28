#!/usr/bin/env python3
"""
Facturación electrónica ARCA/AFIP — Factura C (monotributo) a Consumidor Final.

Flujo completo: FEDummy -> FEParamGetPtosVenta -> FECompUltimoAutorizado ->
FECAESolicitar -> FECompConsultar.

Uso:
    python3 facturar.py --config /ruta/fuera/del/repo/config.json --importe 1000
    python3 facturar.py --config config.json --importe 1000 --solo-consultas

El ambiente por defecto es HOMOLOGACIÓN. Producción requiere declarar
"ambiente": "produccion" en el archivo de configuración.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import cargar_config  # noqa: E402
from soap_client import SoapError  # noqa: E402
from wsaa import obtener_credenciales  # noqa: E402
import wsfe  # noqa: E402

TIPOS_CBTE = {
    "factura_c": wsfe.CBTE_FACTURA_C,
    "nota_debito_c": wsfe.CBTE_NOTA_DEBITO_C,
    "nota_credito_c": wsfe.CBTE_NOTA_CREDITO_C,
}


def _titulo(texto):
    print("\n" + "=" * 62)
    print(texto)
    print("=" * 62)


def _imprimir_pares(etiqueta, pares):
    for codigo, mensaje in pares:
        print("  {}: {} - {}".format(etiqueta, codigo, mensaje))


def elegir_punto_venta(cliente, solicitado, configurado):
    """Lista los puntos de venta y elige uno. Devuelve (pto_vta, lista, nota)."""
    lista, eventos = [], []
    nota = ""
    try:
        lista, eventos = cliente.puntos_venta()
    except wsfe.WSFEError as e:
        # En homologación es habitual que ARCA no devuelva puntos de venta.
        print("  FEParamGetPtosVenta sin resultados:")
        _imprimir_pares("Error", e.errores)
        nota = "FEParamGetPtosVenta sin resultados"

    if lista:
        for pv in lista:
            print("  PtoVta {:>5}  emision={:<12} bloqueado={:<3} baja={}".format(
                pv.get("Nro", "?"), pv.get("EmisionTipo", ""),
                pv.get("Bloqueado", ""), pv.get("FchBaja", "") or "-"))
    else:
        print("  (el ambiente no devolvió puntos de venta)")
    _imprimir_pares("Evento", eventos)

    nros = [int(pv["Nro"]) for pv in lista
            if pv.get("Nro") and str(pv.get("Bloqueado", "N")).upper() != "S"]

    if solicitado is not None:
        elegido = int(solicitado)
        if nros and elegido not in nros:
            nota = "PtoVta {} forzado por CLI; no figura entre los habilitados {}".format(
                elegido, nros)
    elif configurado and nros and int(configurado) in nros:
        elegido = int(configurado)
    elif nros:
        elegido = nros[0]
        if configurado and int(configurado) not in nros:
            nota = "PtoVta {} de config no habilitado; se usa {}".format(configurado, elegido)
    else:
        elegido = 1
        nota = (nota + "; " if nota else "") + "sin puntos de venta: se prueba con PtoVta=1"

    print("\n  PtoVta elegido: {}".format(elegido))
    if nota:
        print("  Nota: {}".format(nota))
    return elegido, lista, nota


def emitir(cliente, punto_venta, tipo_cbte, importe, concepto, doc_tipo, doc_nro,
           cond_iva_receptor, numero):
    """Solicita el CAE de un comprobante. NO reintenta ante error."""
    fecha = datetime.now().strftime("%Y%m%d")
    detalle = wsfe.detalle_factura_c(
        numero=numero, importe=importe, fecha=fecha, concepto=concepto,
        doc_tipo=doc_tipo, doc_nro=doc_nro, cond_iva_receptor=cond_iva_receptor,
    )
    print("  Request FECAEDetRequest:")
    print("    " + json.dumps(detalle, ensure_ascii=False))

    respuesta = cliente.solicitar_cae(punto_venta, tipo_cbte, detalle)

    errores = wsfe.extraer_errores(respuesta)
    eventos = wsfe.extraer_eventos(respuesta)
    cabecera = (respuesta or {}).get("FeCabResp") or {}
    det_resp = ((respuesta or {}).get("FeDetResp") or {}).get("FECAEDetResponse") or {}
    if isinstance(det_resp, list):
        det_resp = det_resp[0]

    resultado = {
        "punto_venta": punto_venta,
        "tipo_cbte": tipo_cbte,
        "numero": numero,
        "fecha": fecha,
        "importe": round(float(importe), 2),
        "concepto": concepto,
        "resultado_cabecera": cabecera.get("Resultado", ""),
        "estado": det_resp.get("Resultado", "") or cabecera.get("Resultado", "") or "ERROR",
        "cae": det_resp.get("CAE", ""),
        "cae_vencimiento": det_resp.get("CAEFchVto", ""),
        "errores": errores,
        "eventos": eventos,
        "observaciones": wsfe.extraer_observaciones(det_resp),
        "detalle_enviado": detalle,
    }

    if errores:
        _imprimir_pares("Error", errores)
    if resultado["observaciones"]:
        _imprimir_pares("Observación", resultado["observaciones"])
    if eventos:
        _imprimir_pares("Evento", eventos)

    return resultado


def guardar_log(cfg, resultado):
    ruta = cfg.facturas_log_path
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            log = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        log = []
    log.append(dict(resultado, ambiente=cfg.ambiente, cuit=cfg.cuit))
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False, default=str)
    return ruta


def main():
    parser = argparse.ArgumentParser(
        description="Emitir Factura C por ARCA/AFIP (por defecto en HOMOLOGACIÓN)")
    parser.add_argument("--config", help="ruta al config.json (fuera del repositorio)")
    parser.add_argument("--importe", "--monto", type=float, default=1000.0,
                        dest="importe", help="importe total del comprobante")
    parser.add_argument("--concepto", type=int, default=3, choices=[1, 2, 3],
                        help="1 productos, 2 servicios, 3 productos y servicios")
    parser.add_argument("--tipo", default="factura_c", choices=sorted(TIPOS_CBTE))
    parser.add_argument("--punto-venta", type=int, help="fuerza el punto de venta")
    parser.add_argument("--doc-tipo", type=int, default=wsfe.DOC_CONSUMIDOR_FINAL)
    parser.add_argument("--doc-nro", type=int, default=0)
    parser.add_argument("--cond-iva-receptor", type=int,
                        default=wsfe.COND_IVA_CONSUMIDOR_FINAL,
                        help="condición IVA del receptor (5 = consumidor final)")
    parser.add_argument("--solo-consultas", action="store_true",
                        help="corre FEDummy/PtosVenta/UltimoAutorizado sin emitir")
    parser.add_argument("--forzar-ta", action="store_true",
                        help="pide un TA nuevo aunque haya uno vigente (ARCA lo penaliza)")
    parser.add_argument("--pdf", action="store_true",
                        help="genera el PDF del comprobante (requiere reportlab y qrcode)")
    parser.add_argument("--json", dest="salida_json",
                        help="escribe el resultado completo en este archivo")
    args = parser.parse_args()

    try:
        cfg = cargar_config(args.config)
        cfg.validar()
    except (FileNotFoundError, ValueError) as e:
        print("ERROR de configuración: {}".format(e))
        return 2

    tipo_cbte = TIPOS_CBTE[args.tipo]

    _titulo("FACTURACIÓN ELECTRÓNICA ARCA/AFIP")
    print(cfg.resumen())
    if cfg.es_produccion:
        print("\n*** AMBIENTE DE PRODUCCIÓN: los comprobantes son reales y fiscales ***")

    # --- WSAA ---
    _titulo("WSAA — Ticket de Acceso")
    try:
        token, sign = obtener_credenciales(cfg, "wsfe", forzar=args.forzar_ta)
    except (SoapError, OSError) as e:
        print("ERROR obteniendo el TA: {}".format(e))
        return 1

    cliente = wsfe.WSFEClient(cfg, token, sign)

    # --- a. FEDummy ---
    _titulo("a. FEDummy — estado de los servidores")
    try:
        estado = cliente.dummy()
    except SoapError as e:
        print("ERROR: {}".format(e))
        return 1
    print("  AppServer : {}".format(estado.get("AppServer")))
    print("  DbServer  : {}".format(estado.get("DbServer")))
    print("  AuthServer: {}".format(estado.get("AuthServer")))
    if not all(str(estado.get(k, "")).upper() == "OK"
               for k in ("AppServer", "DbServer", "AuthServer")):
        print("  ALGUN SERVIDOR NO ESTA OK — se aborta antes de emitir.")
        return 1

    # --- b. FEParamGetPtosVenta ---
    _titulo("b. FEParamGetPtosVenta — puntos de venta")
    try:
        punto_venta, lista_pv, nota_pv = elegir_punto_venta(
            cliente, args.punto_venta, cfg.punto_venta)
    except SoapError as e:
        print("ERROR: {}".format(e))
        return 1

    # --- c. FECompUltimoAutorizado ---
    _titulo("c. FECompUltimoAutorizado — último comprobante")
    try:
        ultimo, eventos = cliente.ultimo_autorizado(punto_venta, tipo_cbte)
    except wsfe.WSFEError as e:
        _imprimir_pares("Error", e.errores)
        return 1
    except SoapError as e:
        print("ERROR: {}".format(e))
        return 1
    _imprimir_pares("Evento", eventos)
    proximo = ultimo + 1
    print("  Último autorizado: {}   Próximo: {}".format(ultimo, proximo))

    if args.solo_consultas:
        print("\n--solo-consultas: no se emite ningún comprobante.")
        return 0

    # --- d. FECAESolicitar (sin reintentos) ---
    _titulo("d. FECAESolicitar — Factura C {:04d}-{:08d}".format(punto_venta, proximo))
    try:
        resultado = emitir(
            cliente, punto_venta, tipo_cbte, args.importe, args.concepto,
            args.doc_tipo, args.doc_nro, args.cond_iva_receptor, proximo)
    except SoapError as e:
        # Puede haberse emitido igual: se consulta a mano, nunca se reintenta solo.
        print("ERROR de transporte en FECAESolicitar: {}".format(e))
        print("NO se reintenta automáticamente (riesgo de duplicado).")
        print("Verificá con: python3 facturar.py --config ... --solo-consultas")
        return 1

    resultado["punto_venta_nota"] = nota_pv
    resultado["puntos_venta"] = lista_pv
    resultado["ta_cache_path"] = cfg.ta_cache_path

    if resultado["estado"] != "A":
        print("\nCOMPROBANTE RECHAZADO (Resultado={})".format(resultado["estado"] or "?"))
        guardar_log(cfg, resultado)
        if args.salida_json:
            with open(args.salida_json, "w", encoding="utf-8") as f:
                json.dump(resultado, f, indent=2, ensure_ascii=False, default=str)
        return 1

    print("\n  COMPROBANTE APROBADO")
    print("  Número     : {:04d}-{:08d}".format(punto_venta, proximo))
    print("  CAE        : {}".format(resultado["cae"]))
    print("  Vto CAE    : {}".format(resultado["cae_vencimiento"]))
    print("  Importe    : ${:.2f}".format(resultado["importe"]))

    # --- e. FECompConsultar ---
    _titulo("e. FECompConsultar — verificación del comprobante emitido")
    try:
        consulta, eventos = cliente.consultar_comprobante(punto_venta, tipo_cbte, proximo)
        resultado["consulta"] = consulta
        _imprimir_pares("Evento", eventos)
        print(json.dumps(consulta, indent=2, ensure_ascii=False))
        if consulta.get("CodAutorizacion") and consulta["CodAutorizacion"] != resultado["cae"]:
            print("  ATENCIÓN: el CAE consultado no coincide con el emitido.")
    except (wsfe.WSFEError, SoapError) as e:
        print("No se pudo consultar el comprobante: {}".format(e))
        resultado["consulta_error"] = str(e)

    ruta_log = guardar_log(cfg, resultado)
    print("\nLog de comprobantes: {}".format(ruta_log))
    print("TA cacheado        : {}".format(cfg.ta_cache_path))

    if args.salida_json:
        with open(args.salida_json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, indent=2, ensure_ascii=False, default=str)
        print("Resultado JSON     : {}".format(args.salida_json))

    if args.pdf:
        try:
            from generar_pdf import generar_pdf
            print("PDF                : {}".format(generar_pdf(resultado)))
        except ImportError as e:
            print("PDF omitido (faltan dependencias: {})".format(e))

    return 0


if __name__ == "__main__":
    sys.exit(main())
