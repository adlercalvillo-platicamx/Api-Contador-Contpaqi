from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
import pyodbc
import os

load_dotenv()

app = FastAPI(title="Antonio API - CONTPAQi Consultas")

def get_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
    )
    return pyodbc.connect(conn_str)

@app.get("/clientes")
def obtener_clientes():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                CIDCLIENTEPROVEEDOR,
                CCODIGOCLIENTE,
                CRAZONSOCIAL,
                CRFC,
                CESTATUS
            FROM admClientes
            WHERE CCODIGOCLIENTE != '(Ninguno)'
        """)
        columnas = [col[0] for col in cursor.description]
        resultados = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        conn.close()
        return {"clientes": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/clientes/{codigo}")
def obtener_cliente(codigo: str):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                CIDCLIENTEPROVEEDOR,
                CCODIGOCLIENTE,
                CRAZONSOCIAL,
                CRFC,
                CESTATUS
            FROM admClientes
            WHERE CCODIGOCLIENTE = ?
        """, codigo)
        columnas = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        return dict(zip(columnas, row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/productos")
def obtener_productos():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                CIDPRODUCTO,
                CCODIGOPRODUCTO,
                CNOMBREPRODUCTO,
                CPRECIO1,
                CSTATUSPRODUCTO,
                CCLAVESAT
            FROM admProductos
            WHERE CCODIGOPRODUCTO != '(Ninguno)'
        """)
        columnas = [col[0] for col in cursor.description]
        resultados = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        conn.close()
        return {"productos": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/productos/{codigo}")
def obtener_producto(codigo: str):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                CIDPRODUCTO,
                CCODIGOPRODUCTO,
                CNOMBREPRODUCTO,
                CPRECIO1,
                CSTATUSPRODUCTO,
                CCLAVESAT
            FROM admProductos
            WHERE CCODIGOPRODUCTO = ?
        """, codigo)
        columnas = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return dict(zip(columnas, row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))