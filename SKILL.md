---
name: afip-facturacion
description: Emitir facturas electrónicas de Argentina (AFIP/ARCA) para monotributistas — Factura C con CAE, PDF con QR según RG 4291/2018, vía web services WSAA/WSFE. Usar este skill cuando el usuario quiera facturar, emitir una factura, generar un comprobante electrónico AFIP/ARCA, obtener CAE, hacer un PDF de factura, o configurar facturación electrónica en Argentina. También aplica si mencionan "Factura C", "monotributo", "ARCA", "AFIP web services", punto de venta, o cualquier flujo que involucre emitir comprobantes fiscales argentinos.
---

# Facturación Electrónica AFIP/ARCA (Argentina)

Emite Factura C (monotributo) a Consumidor Final u otro receptor, obtiene el CAE vía WSFEv1 y genera el PDF oficial con QR code.

**Ambiente por defecto: HOMOLOGACIÓN.** Producción requiere declararla explícitamente en el archivo de configuración.

## Arquitectura

```
skill/
├── SKILL.md               (este archivo)
├── config.example.json    (plantilla de configuración; el archivo real vive fuera del repo)
├── scripts/
│   ├── config.py          (carga config.json externo + resuelve ambiente/URLs)
│   ├── soap_client.py     (cliente SOAP mínimo: requests + xml.etree, sin zeep/lxml)
│   ├── ssl_fix.py         (SECLEVEL=1 para el handshake de ARCA, verificación TLS intacta)
│   ├── wsaa.py            (autenticación: TRA firmado en CMS → token/sign, con cache del TA)
│   ├── wsfe.py            (WSFEv1: FEDummy, PtosVenta, UltimoAutorizado, CAESolicitar, CompConsultar)
│   ├── facturar.py        (CLI: corre el flujo completo)
│   ├── generar_pdf.py     (PDF con QR, formato ARCA oficial — requiere reportlab + qrcode)
│   └── generar_certificado.sh (genera clave privada + CSR)
└── references/
    ├── setup.md           (pasos completos de configuración inicial)
    └── troubleshooting.md (errores comunes)
```

**Datos del usuario** (NO viven dentro del repo): certificado, clave privada, `config.json`, TA cacheado y log de comprobantes. Convención sugerida: un directorio por ambiente, p. ej. `~/arca-homo/` y `~/arca-prod/`.

```
~/arca-homo/
├── config.json                      (ambiente, CUIT, punto de venta, rutas)
├── <alias>.key                      (clave privada RSA 2048)
├── <alias>.crt                      (certificado descargado de ARCA)
├── ta_homologacion.json             (TA cacheado, 0600, auto-generado)
└── facturas_log_homologacion.json   (log de comprobantes)
```

El `.gitignore` bloquea `*.key`, `*.crt`, `config.json`, `ta_*.json` y `facturas_log*.json`. Nunca copiar credenciales dentro del repositorio.

## Dependencias

Solo `requests` y `cryptography` (biblioteca estándar para el resto). `qrcode` + `reportlab` son opcionales y solo para el PDF.

## Cuándo usar este skill

- "facturar", "emitir factura", "hacer una factura"
- "generá una factura C por $X"
- "necesito una factura de AFIP"
- "configurar facturación electrónica"
- "sacar CAE para una factura"
- "regenerar el PDF de una factura"

## Configuración

`config.json` (fuera del repo — ver `config.example.json`):

```json
{
  "ambiente": "homologacion",
  "cuit": "20XXXXXXXXX",
  "punto_venta": 5,
  "cert_path": "/ruta/fuera/del/repo/cert.crt",
  "key_path": "/ruta/fuera/del/repo/clave.key",
  "ta_cache_path": "/ruta/fuera/del/repo/ta_homologacion.json",
  "facturas_log_path": "/ruta/fuera/del/repo/facturas_log.json",
  "emisor": {
    "razon_social": "APELLIDO NOMBRE",
    "condicion_iva": "Responsable Monotributo",
    "domicilio": "Calle 123 - Ciudad",
    "ingresos_brutos": "Exento",
    "inicio_actividades": "DD/MM/YYYY"
  }
}
```

Orden de resolución del archivo: `--config` → `$AFIP_CONFIG` → `$AFIP_HOME/emisor_config.json` → `~/afip/emisor_config.json`.

## Ambiente: homologación vs producción

| ambiente        | WSAA                                              | WSFEv1                                              |
|-----------------|---------------------------------------------------|-----------------------------------------------------|
| `homologacion`  | `https://wsaahomo.afip.gov.ar/ws/services/LoginCms` | `https://wswhomo.afip.gov.ar/wsfev1/service.asmx`   |
| `produccion`    | `https://wsaa.afip.gov.ar/ws/services/LoginCms`     | `https://servicios1.afip.gov.ar/wsfev1/service.asmx` |

Si el campo `ambiente` falta o tiene un valor desconocido, se usa **homologación**. Los comprobantes de homologación no tienen validez fiscal; los de producción sí, y son irreversibles.

## Flujo de trabajo

```bash
cd scripts
python3 facturar.py --config ~/arca-homo/config.json --importe 1000
```

El CLI corre, en orden:

1. **WSAA** — reutiliza el TA cacheado; solo pide uno nuevo si venció.
2. **FEDummy** — aborta si AppServer/DbServer/AuthServer no están los tres OK.
3. **FEParamGetPtosVenta** — lista los puntos de venta; si el ambiente no devuelve ninguno, cae a `PtoVta=1` y lo informa.
4. **FECompUltimoAutorizado** — último comprobante del punto de venta elegido.
5. **FECAESolicitar** — un comprobante, `CbteDesde = CbteHasta = último + 1`.
6. **FECompConsultar** — verifica el CAE y su vencimiento contra ARCA.

Parámetros:

- `--config RUTA` — archivo de configuración (fuera del repo)
- `--importe N` — importe total (default 1000; alias `--monto`)
- `--concepto 1|2|3` — 1=Productos, 2=Servicios, 3=Productos y servicios (default 3)
- `--punto-venta N` — fuerza el punto de venta
- `--doc-tipo` / `--doc-nro` — receptor (default 99 / 0 = Consumidor Final)
- `--cond-iva-receptor N` — condición IVA del receptor, RG 5616 (default 5 = Consumidor Final)
- `--solo-consultas` — corre 1–4 y no emite nada
- `--json RUTA` — vuelca el resultado completo
- `--pdf` — genera el PDF (requiere reportlab + qrcode)
- `--forzar-ta` — pide un TA nuevo aunque haya uno vigente (ARCA lo penaliza; evitar)

Factura C no discrimina IVA: `ImpIVA = 0`, `ImpTotConc = 0`, `ImpNeto = ImpTotal`.

## Ticket de Acceso (TA)

El TA dura ~12 h y se cachea en `ta_cache_path` con permisos 0600. **Nunca** se pide uno nuevo mientras el cacheado siga vigente (margen de 10 min antes del vencimiento): ARCA penaliza los pedidos repetidos.

## Manejo de errores

- Los nodos `Errors`, `Events` y `Observaciones` de ARCA se imprimen completos (código + mensaje).
- `FECAESolicitar` **no se reintenta automáticamente**: un reintento a ciegas puede duplicar el comprobante. Ante un error de transporte, verificar primero con `--solo-consultas` o `FECompConsultar`.
- `FEDummy` y las consultas sí se pueden reintentar sin riesgo.

## Antes de emitir en producción: verificar con el usuario

**Emitir una factura en producción es irreversible y tiene consecuencias fiscales.** Antes de correr `facturar.py` contra producción, mostrá al usuario ambiente, importe, concepto y receptor, y pedí confirmación explícita. Solo se puede anular emitiendo una nota de crédito.

## Setup inicial

Ver `references/setup.md`: generar clave privada + CSR, subir al portal, **autorizar el certificado al servicio `wsfe`** (en homologación se hace en WSASS), dar de alta el punto de venta.

## Errores comunes

Ver `references/troubleshooting.md` — "Computador no autorizado", DH_KEY_TOO_SMALL, TA vencido, rechazos de CAE.
