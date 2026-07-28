# Troubleshooting

## `DH_KEY_TOO_SMALL` o `SSL: DH_KEY_TOO_SMALL`

Algunos servidores de ARCA negocian claves Diffie-Hellman débiles. Ya está resuelto en `ssl_fix.py` (baja `SECLEVEL` a 1 manteniendo la verificación del certificado y del hostname). Si aparece, verificá que `soap_client.py` esté importando `get_afip_session` de `ssl_fix`.

## `coe.notAuthorized` / `Computador no autorizado a acceder al servicio`

Es un fault del WSAA: la firma CMS llegó bien, pero ARCA no tiene una autorización que vincule ese certificado con el servicio pedido (`wsfe`) para ese CUIT.

- **Homologación**: entrá a WSASS (https://wsass-homo.afip.gob.ar/wsass/portal/main.aspx) → "Autorizar Web Service Testing" (o "Crear Autorización a Servicio") → elegí el **alias/DN del certificado** que estás usando, el CUIT representado y el servicio **`wsfe` (Facturación Electrónica)**. Tener el certificado creado no alcanza: la autorización al servicio es un paso aparte.
- **Producción**: "Administrador de Relaciones de Clave Fiscal" → Nueva Relación → servicio "Facturación Electrónica" → representante = el alias del certificado (paso 5 del setup).
- Verificá también que no estés cruzando ambientes: el certificado de homologación no sirve contra producción ni al revés.
- Para confirmar que el problema es la autorización y no la firma, firmá el mismo TRA con `openssl smime -sign ... -nodetach -outform DER`: si devuelve el mismo fault, el código está bien y falta la autorización en ARCA.

## `El CEE no se encuentra autorizado a emitir comprobantes`

Punto de venta no dado de alta como "Web Services" en AFIP. Paso 6 del setup.

## Token expirado / `expired TA`

El TA dura ~12 horas y se cachea en la ruta `ta_cache_path` del `config.json`. El código lo reutiliza hasta 10 minutos antes de su vencimiento y recién ahí pide uno nuevo.

**No borres el cache ni uses `--forzar-ta` de rutina**: ARCA penaliza pedir un TA nuevo mientras hay uno vigente (`El CEE ya posee un TA valido para el acceso al WSN solicitado`). Si ves ese error, esperá a que venza el TA vigente en vez de reintentar.

## `FEParamGetPtosVenta` no devuelve puntos de venta

Normal en homologación: el ambiente de prueba no siempre replica los puntos de venta. El CLI informa el error de ARCA y cae a `PtoVta=1`, que en homologación suele estar habilitado. En producción significa que falta dar de alta el punto de venta tipo "Web Services" (paso 6 del setup).

## Factura rechazada con `10015 Fecha del comprobante invalida`

La fecha debe estar dentro de ±5 días de hoy (productos) o ±10 (servicios). Verificá reloj del sistema.

## Padrón no autorizado (`ws_sr_padron_*`)

AFIP bloquea los servicios de padrón para monotributistas. Por eso los datos del receptor no se auto-completan — se pasan por parámetro o se deja Consumidor Final.

## PDF con QR que no escanea

El QR codifica JSON base64. Verificá que `datos_factura` tenga `cae` como número (no string vacío) y `fecha` en formato `YYYYMMDD` o `YYYY-MM-DD`.

## `openssl genrsa` pide passphrase

No uses `-aes256` ni `-des3`. La clave debe quedar sin cifrar (la protege el filesystem con `chmod 600`).
