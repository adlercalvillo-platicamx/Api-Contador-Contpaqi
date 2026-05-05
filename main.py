# ============================================================
# Antonio API - CONTPAQi Consultas
# Servidor FastAPI que conecta el agente Antonio con la base
# de datos de CONTPAQi Comercial vía SQL Server.
# ============================================================

from fastapi import FastAPI, HTTPException, Security, Query
from fastapi.security.api_key import APIKeyHeader
from dotenv import load_dotenv
import pyodbc
import os
import time

# Carga las variables del archivo .env (servidor, base de datos, credenciales y token)
load_dotenv()

app = FastAPI(title="Antonio API - CONTPAQi Consultas")

# ============================================================
# CONFIGURACIÓN DE AUTENTICACIÓN
# Toda petición debe incluir el header X-API-Token con el
# valor definido en el .env. Sin él, la API rechaza el request.
# ============================================================
API_KEY_NAME = "X-API-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def verificar_token(api_key: str = Security(api_key_header)):
    # Compara el token recibido con el definido en .env
    if api_key != os.getenv("API_TOKEN"):
        raise HTTPException(
            status_code=401,
            detail="Token inválido. No tienes autorización para consultar esta API."
        )

# ============================================================
# CONFIGURACIÓN DE REINTENTOS
# Si la conexión falla, reintenta antes de lanzar el error.
# ============================================================
MAX_REINTENTOS = 3       # Número máximo de intentos
ESPERA_REINTENTOS = 1    # Segundos de espera entre intentos


# ============================================================
# FUNCIÓN: get_connection
# Establece la conexión con SQL Server usando las variables
# del .env. Si falla, reintenta hasta MAX_REINTENTOS veces.
# Solo aplica retry en errores de conexión, no de lógica.
# ============================================================
def get_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        f"Connection Timeout=30;"
    )

    ultimo_error = None

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            return pyodbc.connect(conn_str)

        except pyodbc.OperationalError as e:
            # Error de red o SQL Server no disponible — vale la pena reintentar
            ultimo_error = e
            if intento < MAX_REINTENTOS:
                time.sleep(ESPERA_REINTENTOS)

        except pyodbc.InterfaceError:
            # Error de configuración — no tiene sentido reintentar
            raise HTTPException(
                status_code=503,
                detail="Error de configuración en la conexión a CONTPAQi. Contacta a soporte técnico."
            )

        except Exception as e:
            # Error desconocido — no reintentamos
            raise HTTPException(
                status_code=503,
                detail=f"Error inesperado al conectarse a CONTPAQi: {str(e)}"
            )

    # Si agotó todos los reintentos, lanza el error de conexión
    raise HTTPException(
        status_code=503,
        detail="No fue posible conectarse a CONTPAQi después de varios intentos. "
               "Verifica que SQL Server esté activo y que la computadora del despacho esté encendida."
    )


# ============================================================
# FUNCIÓN: ejecutar_query
# Ejecuta una consulta SQL y regresa los resultados como lista
# de diccionarios. Centraliza el manejo de errores de queries
# para no repetir lógica en cada endpoint.
# ============================================================
def ejecutar_query(query: str, params=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Ejecuta con o sin parámetros según se requiera
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        # Convierte los resultados a lista de diccionarios
        # usando los nombres de columna reales de CONTPAQi
        columnas = [col[0] for col in cursor.description]
        resultados = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        conn.close()
        return resultados

    except HTTPException:
        # Re-lanza errores de conexión ya manejados en get_connection
        raise

    except pyodbc.ProgrammingError:
        # Error en la query — probablemente cambió la estructura de la BD
        raise HTTPException(
            status_code=500,
            detail="Error en la consulta a CONTPAQi. Es posible que la estructura "
                   "de la base de datos haya cambiado. Contacta a soporte técnico."
        )

    except pyodbc.DataError:
        # Los datos enviados no tienen el formato que espera SQL Server
        raise HTTPException(
            status_code=400,
            detail="Los datos enviados no tienen el formato correcto."
        )

    except Exception as e:
        # Cualquier otro error inesperado
        raise HTTPException(
            status_code=500,
            detail=f"Error inesperado al consultar CONTPAQi: {str(e)}"
        )


# ============================================================
# ENDPOINT: GET /clientes
# Regresa clientes registrados en CONTPAQi.
# Query params:
#   - limite: cuántos registros regresar (default 50, max 500)
#   - offset: desde qué registro empezar (default 0)
#   - orden: asc = primeros registrados, desc = últimos (default asc)
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/clientes")
async def obtener_clientes(
    limite: int = Query(default=50, ge=1, le=500, description="Número de registros a regresar"),
    offset: int = Query(default=0, ge=0, description="Número de registros a saltar"),
    orden: str = Query(default="asc", pattern="^(asc|desc)$", description="asc = primeros, desc = últimos"),
    token: str = Security(verificar_token)
):
    # Construye la query con paginación y orden dinámico
    orden_sql = "ASC" if orden == "asc" else "DESC"
    query = f"""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY CIDCLIENTEPROVEEDOR {orden_sql}) AS rn
            FROM vw_AgenteClientes
        ) t
        WHERE rn > ? AND rn <= ?
    """
    resultados = ejecutar_query(query, (offset, offset + limite))

    # Elimina la columna auxiliar rn del resultado
    for r in resultados:
        r.pop("rn", None)

    if not resultados:
        return {
            "mensaje": "No se encontraron clientes registrados en CONTPAQi.",
            "clientes": []
        }

    return {
        "total_regresados": len(resultados),
        "limite": limite,
        "offset": offset,
        "orden": orden,
        "clientes": resultados
    }


# ============================================================
# ENDPOINT: GET /clientes/{codigo}
# Busca un cliente específico por su código en CONTPAQi.
# Regresa 404 si no existe, 400 si el código está vacío.
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/clientes/{codigo}")
async def obtener_cliente(codigo: str, token: str = Security(verificar_token)):
    # Validación básica del parámetro
    if not codigo.strip():
        raise HTTPException(
            status_code=400,
            detail="El código del cliente no puede estar vacío."
        )

    resultados = ejecutar_query(
        "SELECT * FROM vw_AgenteClientes WHERE CCODIGOCLIENTE = ?",
        codigo.strip()
    )

    if not resultados:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún cliente con el código '{codigo}' en CONTPAQi."
        )

    return resultados[0]


# ============================================================
# ENDPOINT: GET /productos
# Regresa productos registrados en CONTPAQi.
# Query params:
#   - limite: cuántos registros regresar (default 50, max 500)
#   - offset: desde qué registro empezar (default 0)
#   - orden: asc = primeros registrados, desc = últimos (default asc)
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/productos")
async def obtener_productos(
    limite: int = Query(default=50, ge=1, le=500, description="Número de registros a regresar"),
    offset: int = Query(default=0, ge=0, description="Número de registros a saltar"),
    orden: str = Query(default="asc", pattern="^(asc|desc)$", description="asc = primeros, desc = últimos"),
    token: str = Security(verificar_token)
):
    # Construye la query con paginación y orden dinámico
    orden_sql = "ASC" if orden == "asc" else "DESC"
    query = f"""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY CIDPRODUCTO {orden_sql}) AS rn
            FROM vw_AgenteProductos
        ) t
        WHERE rn > ? AND rn <= ?
    """
    resultados = ejecutar_query(query, (offset, offset + limite))

    # Elimina la columna auxiliar rn del resultado
    for r in resultados:
        r.pop("rn", None)

    if not resultados:
        return {
            "mensaje": "No se encontraron productos registrados en CONTPAQi.",
            "productos": []
        }

    return {
        "total_regresados": len(resultados),
        "limite": limite,
        "offset": offset,
        "orden": orden,
        "productos": resultados
    }


# ============================================================
# ENDPOINT: GET /productos/{codigo}
# Busca un producto específico por su código en CONTPAQi.
# Regresa 404 si no existe, 400 si el código está vacío.
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/productos/{codigo}")
async def obtener_producto(codigo: str, token: str = Security(verificar_token)):
    # Validación básica del parámetro
    if not codigo.strip():
        raise HTTPException(
            status_code=400,
            detail="El código del producto no puede estar vacío."
        )

    resultados = ejecutar_query(
        "SELECT * FROM vw_AgenteProductos WHERE CCODIGOPRODUCTO = ?",
        codigo.strip()
    )

    if not resultados:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún producto con el código '{codigo}' en CONTPAQi."
        )

    return resultados[0]


# ============================================================
# ENDPOINT: GET /documentos
# Regresa documentos (facturas) registrados en CONTPAQi.
# Query params:
#   - limite: cuántos registros regresar (default 50, max 500)
#   - offset: desde qué registro empezar (default 0)
#   - orden: asc = primeros registrados, desc = últimos (default asc)
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/documentos")
async def obtener_documentos(
    limite: int = Query(default=50, ge=1, le=500, description="Número de registros a regresar"),
    offset: int = Query(default=0, ge=0, description="Número de registros a saltar"),
    orden: str = Query(default="asc", pattern="^(asc|desc)$", description="asc = primeros, desc = últimos"),
    token: str = Security(verificar_token)
):
    orden_sql = "ASC" if orden == "asc" else "DESC"
    query = f"""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY CIDDOCUMENTO {orden_sql}) AS rn
            FROM vw_AgenteDocumentos
        ) t
        WHERE rn > ? AND rn <= ?
    """
    resultados = ejecutar_query(query, (offset, offset + limite))

    for r in resultados:
        r.pop("rn", None)

    if not resultados:
        return {
            "mensaje": "No se encontraron documentos registrados en CONTPAQi.",
            "documentos": []
        }

    return {
        "total_regresados": len(resultados),
        "limite": limite,
        "offset": offset,
        "orden": orden,
        "documentos": resultados
    }


# ============================================================
# ENDPOINT: GET /documentos/cliente/{codigo}
# Regresa todos los documentos pendientes de un cliente específico.
# Útil para consultas de cobranza por cliente.
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/documentos/cliente/{codigo}")
async def obtener_documentos_cliente(codigo: str, token: str = Security(verificar_token)):
    # Validación básica del parámetro
    if not codigo.strip():
        raise HTTPException(
            status_code=400,
            detail="El código del cliente no puede estar vacío."
        )

    # Busca el ID del cliente por su código
    cliente = ejecutar_query(
        "SELECT CIDCLIENTEPROVEEDOR FROM vw_AgenteClientes WHERE CCODIGOCLIENTE = ?",
        codigo.strip()
    )

    if not cliente:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún cliente con el código '{codigo}' en CONTPAQi."
        )

    id_cliente = cliente[0]["CIDCLIENTEPROVEEDOR"]

    # Busca documentos pendientes del cliente
    resultados = ejecutar_query(
        """
        SELECT * FROM vw_AgenteDocumentos
        WHERE CIDCLIENTEPROVEEDOR = ?
        AND CPENDIENTE > 0
        ORDER BY CFECHA ASC
        """,
        id_cliente
    )

    if not resultados:
        return {
            "mensaje": f"El cliente '{codigo}' no tiene documentos pendientes en CONTPAQi.",
            "documentos": []
        }

    return {
        "total_regresados": len(resultados),
        "cliente_codigo": codigo,
        "documentos": resultados
    }


# ============================================================
# ENDPOINT: GET /cobranza/resumen
# Regresa un resumen de cobranza por cliente — total facturado,
# total pendiente y número de facturas de cada cliente.
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/cobranza/resumen")
async def obtener_resumen_cobranza(token: str = Security(verificar_token)):
    resultados = ejecutar_query("SELECT * FROM vw_AgenteResumenCobranza ORDER BY CTOTALPENDIENTE DESC")

    if not resultados:
        return {
            "mensaje": "No hay documentos pendientes en CONTPAQi.",
            "resumen": []
        }

    total_general = sum(r["CTOTALPENDIENTE"] for r in resultados)

    return {
        "total_pendiente_general": round(total_general, 2),
        "total_clientes_con_saldo": len(resultados),
        "resumen": resultados
    }


# ============================================================
# ENDPOINT: GET /cobranza/resumen/{codigo}
# Regresa el resumen de cobranza de un cliente específico.
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/cobranza/resumen/{codigo}")
async def obtener_resumen_cobranza_cliente(codigo: str, token: str = Security(verificar_token)):
    if not codigo.strip():
        raise HTTPException(
            status_code=400,
            detail="El código del cliente no puede estar vacío."
        )

    # Busca el ID del cliente por su código
    cliente = ejecutar_query(
        "SELECT CIDCLIENTEPROVEEDOR FROM vw_AgenteClientes WHERE CCODIGOCLIENTE = ?",
        codigo.strip()
    )

    if not cliente:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún cliente con el código '{codigo}' en CONTPAQi."
        )

    id_cliente = cliente[0]["CIDCLIENTEPROVEEDOR"]

    resultados = ejecutar_query(
        "SELECT * FROM vw_AgenteResumenCobranza WHERE CIDCLIENTEPROVEEDOR = ?",
        id_cliente
    )

    if not resultados:
        return {
            "mensaje": f"El cliente '{codigo}' no tiene facturas pendientes en CONTPAQi.",
            "resumen": {}
        }

    return resultados[0]


# ============================================================
# ENDPOINT: GET /clientes/rfc/{rfc}
# Busca un cliente específico por su RFC en CONTPAQi.
# Regresa 404 si no existe, 400 si el RFC está vacío.
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/clientes/rfc/{rfc}")
async def obtener_cliente_por_rfc(rfc: str, token: str = Security(verificar_token)):
    # Validación básica del parámetro
    if not rfc.strip():
        raise HTTPException(
            status_code=400,
            detail="El RFC no puede estar vacío."
        )

    resultados = ejecutar_query(
        "SELECT * FROM vw_AgenteClientes WHERE CRFC = ?",
        rfc.strip().upper()
    )

    if not resultados:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún cliente con el RFC '{rfc}' en CONTPAQi."
        )

    return resultados[0]


# ============================================================
# ENDPOINT: GET /documentos/fechas
# Regresa documentos en un rango de fechas específico.
# Query params:
#   - fecha_inicio: fecha de inicio en formato YYYY-MM-DD
#   - fecha_fin: fecha de fin en formato YYYY-MM-DD
#   - limite: cuántos registros regresar (default 50, max 500)
#   - offset: desde qué registro empezar (default 0)
# Requiere header X-API-Token válido.
# ============================================================
@app.get("/documentos/fechas")
async def obtener_documentos_por_fechas(
    fecha_inicio: str = Query(description="Fecha de inicio en formato YYYY-MM-DD"),
    fecha_fin: str = Query(description="Fecha de fin en formato YYYY-MM-DD"),
    limite: int = Query(default=50, ge=1, le=500, description="Número de registros a regresar"),
    offset: int = Query(default=0, ge=0, description="Número de registros a saltar"),
    token: str = Security(verificar_token)
):
    # Validación de fechas
    try:
        from datetime import datetime
        fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
        fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Formato de fecha incorrecto. Usa el formato YYYY-MM-DD (ej. 2026-04-01)."
        )

    if fecha_inicio_dt > fecha_fin_dt:
        raise HTTPException(
            status_code=400,
            detail="La fecha de inicio no puede ser mayor a la fecha de fin."
        )

    query = f"""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY CFECHA ASC) AS rn
            FROM vw_AgenteDocumentos
            WHERE CFECHA >= ? AND CFECHA < DATEADD(day, 1, CAST(? AS DATE))
        ) t
        WHERE rn > ? AND rn <= ?
    """

    resultados = ejecutar_query(query, (fecha_inicio, fecha_fin, offset, offset + limite))

    for r in resultados:
        r.pop("rn", None)

    if not resultados:
        return {
            "mensaje": f"No se encontraron documentos entre {fecha_inicio} y {fecha_fin}.",
            "documentos": []
        }

    return {
        "total_regresados": len(resultados),
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "limite": limite,
        "offset": offset,
        "documentos": resultados
    }


# ============================================================
# ENDPOINT: GET /health
# Endpoint liviano para verificar que el servidor está activo.
# No toca la base de datos. Se usa para mantener el túnel de
# ngrok activo y evitar que se duerma por inactividad.
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "servidor": "Antonio API CONTPAQi"}