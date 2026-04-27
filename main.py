# ============================================================
# Antonio API - CONTPAQi Consultas
# Servidor FastAPI que conecta el agente Antonio con la base
# de datos de CONTPAQi Comercial vía SQL Server.
# ============================================================

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
import pyodbc
import os
import time

# Carga las variables del archivo .env (servidor, base de datos, credenciales)
load_dotenv()

app = FastAPI(title="Antonio API - CONTPAQi Consultas")

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
# Regresa la lista completa de clientes registrados en CONTPAQi.
# Excluye el registro especial '(Ninguno)' que CONTPAQi crea
# automáticamente al inicializar la empresa. Esto ya lo maneja
# la vista creada previamente.
# ============================================================
@app.get("/clientes")
def obtener_clientes():
    resultados = ejecutar_query("""
        SELECT 
            CIDCLIENTEPROVEEDOR,
            CCODIGOCLIENTE,
            CRAZONSOCIAL,
            CRFC,
            CESTATUS
        FROM vw_AgenteClientes
    """)

    if not resultados:
        return {
            "mensaje": "No se encontraron clientes registrados en CONTPAQi.",
            "clientes": []
        }

    return {"clientes": resultados}


# ============================================================
# ENDPOINT: GET /clientes/{codigo}
# Busca un cliente específico por su código en CONTPAQi.
# Regresa 404 si no existe, 400 si el código está vacío.
# ============================================================
@app.get("/clientes/{codigo}")
def obtener_cliente(codigo: str):
    # Validación básica del parámetro
    if not codigo.strip():
        raise HTTPException(
            status_code=400,
            detail="El código del cliente no puede estar vacío."
        )

    resultados = ejecutar_query("""
        SELECT 
            CIDCLIENTEPROVEEDOR,
            CCODIGOCLIENTE,
            CRAZONSOCIAL,
            CRFC,
            CESTATUS
        FROM vw_AgenteClientes
        WHERE CCODIGOCLIENTE = ?
    """, codigo.strip())

    if not resultados:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún cliente con el código '{codigo}' en CONTPAQi."
        )

    return resultados[0]


# ============================================================
# ENDPOINT: GET /productos
# Regresa la lista completa de productos registrados en CONTPAQi.
# Incluye precio de lista 1 y clave SAT para cada producto.
# Excluye el registro especial '(Ninguno)' que CONTPAQi crea
# automáticamente al inicializar la empresa. Esto ya lo maneja
# la vista creada previamente.
# ============================================================
@app.get("/productos")
def obtener_productos():
    resultados = ejecutar_query("""
        SELECT 
            CIDPRODUCTO,
            CCODIGOPRODUCTO,
            CNOMBREPRODUCTO,
            CPRECIO1,
            CSTATUSPRODUCTO,
            CCLAVESAT
        FROM vw_AgenteProductos
    """)

    if not resultados:
        return {
            "mensaje": "No se encontraron productos registrados en CONTPAQi.",
            "productos": []
        }

    return {"productos": resultados}


# ============================================================
# ENDPOINT: GET /productos/{codigo}
# Busca un producto específico por su código en CONTPAQi.
# Regresa 404 si no existe, 400 si el código está vacío.
# ============================================================
@app.get("/productos/{codigo}")
def obtener_producto(codigo: str):
    # Validación básica del parámetro
    if not codigo.strip():
        raise HTTPException(
            status_code=400,
            detail="El código del producto no puede estar vacío."
        )

    resultados = ejecutar_query("""
        SELECT 
            CIDPRODUCTO,
            CCODIGOPRODUCTO,
            CNOMBREPRODUCTO,
            CPRECIO1,
            CSTATUSPRODUCTO,
            CCLAVESAT
        FROM vw_AgenteProductos
        WHERE CCODIGOPRODUCTO = ?
    """, codigo.strip())

    if not resultados:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró ningún producto con el código '{codigo}' en CONTPAQi."
        )

    return resultados[0]