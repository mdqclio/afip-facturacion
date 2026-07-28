# Setup inicial — AFIP Facturación Electrónica

Esto se hace **una sola vez** por monotributista. Después, emitir facturas es un solo comando.

## 0. Prerrequisitos

- Python 3.8+
- `pip install requests cryptography` (obligatorio) y `pip install qrcode reportlab Pillow` solo si querés el PDF
- `openssl` (viene con macOS/Linux)
- Clave fiscal AFIP nivel 3
- Monotributo activo

Empezá siempre por **homologación**: los comprobantes de prueba no tienen validez fiscal.

## 1. Elegir directorio de datos (fuera del repositorio)

Un directorio por ambiente, para no mezclar certificados:

```bash
mkdir -p ~/arca-homo && chmod 700 ~/arca-homo
```

Ahí van la clave privada, el certificado, `config.json`, el TA cacheado y el log. Nunca dentro del repo.

## 2. Crear `config.json`

Copiá `config.example.json` a `~/arca-homo/config.json` y completalo:

```json
{
  "ambiente": "homologacion",
  "cuit": "20XXXXXXXXX",
  "punto_venta": 1,
  "cert_path": "/home/usuario/arca-homo/mi_cert.crt",
  "key_path": "/home/usuario/arca-homo/mi_clave.key",
  "ta_cache_path": "/home/usuario/arca-homo/ta_homologacion.json",
  "facturas_log_path": "/home/usuario/arca-homo/facturas_log.json",
  "emisor": {
    "razon_social": "APELLIDO NOMBRE",
    "condicion_iva": "Responsable Monotributo",
    "domicilio": "Calle 123 - Ciudad",
    "ingresos_brutos": "Exento",
    "inicio_actividades": "DD/MM/YYYY"
  }
}
```

`chmod 600 ~/arca-homo/config.json`. Si `ambiente` falta, se asume homologación. Datos fiscales: constancia de inscripción (https://seti.afip.gob.ar/padron-puc-constancia-internet/).

## 3. Generar clave privada + CSR

```bash
bash scripts/generar_certificado.sh 20XXXXXXXXX "APELLIDO NOMBRE"
```

Genera `$AFIP_HOME/certs/private_key.key` y `request.csr`.

## 4. Subir el CSR a AFIP

1. https://auth.afip.gob.ar → clave fiscal.
2. "Administrador de Relaciones de Clave Fiscal" (si no aparece, agregá el servicio).
3. Adherir servicio → AFIP → Servicios Interactivos → **"Administración de Certificados Digitales"**. Cerrá sesión y volvé a entrar.
4. Abrí "Administración de Certificados Digitales" → "Agregar alias" → nombre libre (ej. `facturacion`) → subí el `.csr`.
5. Descargá el `.crt` resultante y guardalo como `$AFIP_HOME/certs/certificate.crt`.

## 5. Asociar certificado al servicio WSFE

En "Administrador de Relaciones":

1. Nueva Relación.
2. Representado: tu CUIT.
3. Servicio: buscar "Facturación Electrónica" → AFIP → WebServices → **"Facturación Electrónica"**.
4. Representante: seleccioná el certificado que acabás de crear (por alias).
5. Confirmar con clave fiscal.

## 6. Dar de alta el punto de venta

Si todavía no tenés un punto de venta tipo "Web Services":

1. Ingresá al portal con clave fiscal.
2. Servicio "Regímenes de Facturación y Registración (REAR/RECE/RFI)" (adherirlo si no está).
3. ABM de puntos de venta → Agregar → Sistema de Facturación: **"Web Services"**.
4. Anotá el número y ponelo en `emisor_config.json` como `punto_venta`.

## 7. Probar

```bash
cd <ruta-del-skill>/scripts
python3 wsaa.py --config ~/arca-homo/config.json          # debería imprimir token y sign
python3 facturar.py --config ~/arca-homo/config.json --solo-consultas
python3 facturar.py --config ~/arca-homo/config.json --importe 1000
```

`--solo-consultas` corre FEDummy, FEParamGetPtosVenta y FECompUltimoAutorizado sin emitir nada: usalo siempre antes de la primera emisión.

## Homologación (testing)

Homologación usa un **certificado propio**, distinto del de producción, y son dos pasos separados:

1. **Crear el certificado**: WSASS (https://wsass-homo.afip.gob.ar/wsass/portal/main.aspx) → "Crear Certificado" → subís el CSR y descargás el `.crt`.
2. **Autorizar el certificado al servicio**: en el mismo WSASS → "Autorizar Web Service Testing" / "Crear Autorización a Servicio" → alias o DN del certificado + CUIT representado + servicio **`wsfe` (Facturación Electrónica)**.

Sin el paso 2, WSAA responde `coe.notAuthorized — Computador no autorizado a acceder al servicio`, aunque el certificado sea válido y la firma CMS correcta.

Los puntos de venta de homologación no coinciden necesariamente con los de producción: si `FEParamGetPtosVenta` no devuelve ninguno, probá con `PtoVta=1`.
