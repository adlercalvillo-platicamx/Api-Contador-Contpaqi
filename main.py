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
        f"Connection Timeout=10;"
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