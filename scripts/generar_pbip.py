"""
Genera el dashboard de Power BI en formato PBIP (Power BI Project: archivos de texto versionables).

Salida: powerbi/CarteraMorosidad.pbip + carpetas .SemanticModel y .Report
Abrir con Power BI Desktop → Inicio → Actualizar (descarga los CSV desde GitHub).

Uso:
    python scripts/generar_pbip.py
"""
import json
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "powerbi"
NOMBRE = "CarteraMorosidad"
URL = "https://raw.githubusercontent.com/ego4men/analisis-cartera-morosidad/main/powerbi/datos/"


# ---------------------------------------------------------------------------
# 1. Modelo semántico (TMSL): tablas, Power Query, relaciones y medidas DAX
# ---------------------------------------------------------------------------
def columna(nombre, tipo, resumen="none", formato=None, oculta=False):
    c = {"name": nombre, "dataType": tipo, "sourceColumn": nombre, "summarizeBy": resumen}
    if formato:
        c["formatString"] = formato
    if oculta:
        c["isHidden"] = True
    return c


def consulta_csv(archivo, tipos, pasos_extra=()):
    tipos_m = ", ".join(f'{{"{c}", {t}}}' for c, t in tipos)
    lineas = [
        "let",
        f'    Origen = Csv.Document(Web.Contents("{URL}{archivo}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars=true]),",
        f'    Tipos = Table.TransformColumnTypes(Encabezados, {{{tipos_m}}}, "en-US")' + ("," if pasos_extra else ""),
    ]
    lineas += list(pasos_extra)
    ultimo = pasos_extra[-1].split("=")[0].strip() if pasos_extra else "Tipos"
    lineas += ["in", f"    {ultimo}"]
    return lineas


def tabla(nombre, columnas, expresion, medidas=None, oculta=False, categoria=None):
    t = {"name": nombre, "columns": columnas,
         "partitions": [{"name": nombre, "mode": "import", "source": {"type": "m", "expression": expresion}}]}
    if medidas:
        t["measures"] = medidas
    if oculta:
        t["isHidden"] = True
    if categoria:
        t["dataCategory"] = categoria
    return t


def medida(nombre, expresion, formato, carpeta=None):
    m = {"name": nombre, "expression": expresion, "formatString": formato}
    if carpeta:
        m["displayFolder"] = carpeta
    return m


MONEDA = '"S/ "#,0'
PCT = "0.00%"
ENTERO = "#,0"

f_estado = tabla(
    "fEstado",
    [columna("credito_id", "int64"), columna("cliente_id", "int64"), columna("agencia_id", "int64", oculta=True),
     columna("producto", "string"), columna("canal", "string"), columna("fecha_desembolso", "dateTime", formato="dd/mm/yyyy"),
     columna("monto_desembolsado", "double", "sum", MONEDA), columna("saldo_capital", "double", "sum", MONEDA),
     columna("cuotas_vencidas", "int64"), columna("monto_vencido", "double", "sum", MONEDA),
     columna("dias_atraso", "int64"), columna("tramo_mora", "string"), columna("estado", "string")],
    consulta_csv("estado_corte.csv",
                 [("credito_id", "Int64.Type"), ("cliente_id", "Int64.Type"), ("agencia_id", "Int64.Type"),
                  ("producto", "type text"), ("canal", "type text"), ("fecha_desembolso", "type date"),
                  ("monto_desembolsado", "type number"), ("saldo_capital", "type number"),
                  ("cuotas_vencidas", "Int64.Type"), ("monto_vencido", "type number"),
                  ("dias_atraso", "Int64.Type"), ("tramo_mora", "type text")],
                 ['    Estado = Table.AddColumn(Tipos, "estado", each if List.Contains({"Cancelado", "Castigado"}, [tramo_mora]) then [tramo_mora] else "Vigente", type text)']),
)

f_cierre = tabla(
    "fCierre",
    [columna("fecha_cierre", "dateTime", formato="mmm yyyy"), columna("credito_id", "int64"),
     columna("producto", "string"), columna("canal", "string"), columna("agencia_id", "int64", oculta=True),
     columna("saldo_capital", "double", "sum", MONEDA), columna("dias_atraso", "int64"), columna("tramo_mora", "string")],
    consulta_csv("cierre_mensual.csv",
                 [("fecha_cierre", "type date"), ("credito_id", "Int64.Type"), ("producto", "type text"),
                  ("canal", "type text"), ("agencia_id", "Int64.Type"), ("saldo_capital", "type number"),
                  ("dias_atraso", "Int64.Type"), ("tramo_mora", "type text")]),
)

d_agencia = tabla(
    "dAgencia",
    [columna("agencia_id", "int64"), columna("nombre_agencia", "string"), columna("region", "string")],
    consulta_csv("agencias.csv", [("agencia_id", "Int64.Type"), ("nombre_agencia", "type text"), ("region", "type text")]),
)

d_calendario = tabla(
    "dCalendario",
    [{**columna("Fecha", "dateTime", formato="dd/mm/yyyy"), "isKey": True},
     columna("Año", "int64"), columna("Mes", "string"), columna("MesNumero", "int64", oculta=True)],
    ["let",
     "    Fechas = List.Dates(#date(2024, 1, 1), Duration.Days(#date(2026, 9, 30) - #date(2024, 1, 1)) + 1, #duration(1, 0, 0, 0)),",
     '    Tabla = Table.FromList(Fechas, Splitter.SplitByNothing(), {"Fecha"}),',
     '    Tipo = Table.TransformColumnTypes(Tabla, {{"Fecha", type date}}),',
     '    Anio = Table.AddColumn(Tipo, "Año", each Date.Year([Fecha]), Int64.Type),',
     '    Mes = Table.AddColumn(Anio, "Mes", each Date.ToText([Fecha], "MMM yyyy", "es-PE"), type text),',
     '    MesNumero = Table.AddColumn(Mes, "MesNumero", each Date.Year([Fecha]) * 100 + Date.Month([Fecha]), Int64.Type)',
     "in",
     "    MesNumero"],
    categoria="Time",
)
d_calendario["columns"][2]["sortByColumn"] = "MesNumero"

medidas = tabla(
    "_Medidas",
    [columna("Columna", "string", oculta=True)],
    ['let', '    Origen = #table(type table [Columna = text], {})', 'in', '    Origen'],
    medidas=[
        medida("Saldo Vigente", 'CALCULATE ( SUM ( fEstado[saldo_capital] ), fEstado[estado] = "Vigente" )', MONEDA, "Corte"),
        medida("Créditos Vigentes", 'CALCULATE ( COUNTROWS ( fEstado ), fEstado[estado] = "Vigente" )', ENTERO, "Corte"),
        medida("Saldo Mora 30", "CALCULATE ( [Saldo Vigente], fEstado[dias_atraso] > 30 )", MONEDA, "Corte"),
        medida("% Mora 30", "DIVIDE ( [Saldo Mora 30], [Saldo Vigente] )", PCT, "Corte"),
        medida("% Mora 90", "DIVIDE ( CALCULATE ( [Saldo Vigente], fEstado[dias_atraso] > 90 ), [Saldo Vigente] )", PCT, "Corte"),
        medida("Saldo Castigado", 'CALCULATE ( SUM ( fEstado[saldo_capital] ), fEstado[estado] = "Castigado" )', MONEDA, "Corte"),
        medida("Monto Vencido 1-60",
               "CALCULATE ( SUM ( fEstado[monto_vencido] ), fEstado[dias_atraso] >= 1, fEstado[dias_atraso] <= 60 )",
               MONEDA, "Cobranza"),
        medida("Saldo Mes", "SUM ( fCierre[saldo_capital] )", MONEDA, "Evolución"),
        medida("% Mora 30 Mes", "DIVIDE ( CALCULATE ( [Saldo Mes], fCierre[dias_atraso] > 30 ), [Saldo Mes] )", PCT, "Evolución"),
        medida("Var. Mora vs Mes Anterior",
               "VAR actual = [% Mora 30 Mes]\n"
               "VAR anterior = CALCULATE ( [% Mora 30 Mes], DATEADD ( dCalendario[Fecha], -1, MONTH ) )\n"
               "RETURN IF ( NOT ISBLANK ( anterior ), actual - anterior )",
               "+0.00%;-0.00%;0.00%", "Evolución"),
    ],
)

modelo = {
    "compatibilityLevel": 1567,
    "model": {
        "culture": "es-ES",
        "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
        "defaultPowerBIDataSourceVersion": "powerBI_V3",
        "sourceQueryCulture": "es-ES",
        "tables": [f_estado, f_cierre, d_agencia, d_calendario, medidas],
        "relationships": [
            {"name": "rel_agencia_estado", "fromTable": "fEstado", "fromColumn": "agencia_id",
             "toTable": "dAgencia", "toColumn": "agencia_id"},
            {"name": "rel_agencia_cierre", "fromTable": "fCierre", "fromColumn": "agencia_id",
             "toTable": "dAgencia", "toColumn": "agencia_id"},
            {"name": "rel_calendario_cierre", "fromTable": "fCierre", "fromColumn": "fecha_cierre",
             "toTable": "dCalendario", "toColumn": "Fecha"},
        ],
        "annotations": [
            {"name": "PBI_QueryOrder", "value": json.dumps(["fEstado", "fCierre", "dAgencia", "dCalendario", "_Medidas"])},
            {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
        ],
    },
}

# ---------------------------------------------------------------------------
# 2. Reporte (formato report.json): tres páginas
# ---------------------------------------------------------------------------
ALIAS = {"fEstado": "e", "fCierre": "c", "dAgencia": "a", "dCalendario": "d", "_Medidas": "m"}
MEDIDAS = {m["name"] for m in medidas["measures"]}


def campo(ref):
    tabla_, prop = ref.split(".", 1)
    expr = {"Expression": {"SourceRef": {"Source": ALIAS[tabla_]}}, "Property": prop}
    if prop in MEDIDAS:
        return {"Measure": expr, "Name": ref, "NativeReferenceName": prop}
    return {"Column": expr, "Name": ref, "NativeReferenceName": prop}


def literal(texto):
    return {"expr": {"Literal": {"Value": f"'{texto}'"}}}


def visual(tipo, x, y, w, h, roles, titulo=None, orden=None, z=0, extra_objects=None):
    refs = [r for lista in roles.values() for r in lista]
    tablas = sorted({r.split(".")[0] for r in refs})
    query = {"Version": 2,
             "From": [{"Name": ALIAS[t], "Entity": t, "Type": 0} for t in tablas],
             "Select": [campo(r) for r in refs]}
    if orden:
        ref, direccion = orden
        query["OrderBy"] = [{"Direction": direccion, "Expression": {k: v for k, v in campo(ref).items()
                                                                    if k in ("Measure", "Column")}}]
    single = {
        "visualType": tipo,
        "projections": {rol: [{"queryRef": r, **({"active": True} if rol in ("Category", "Rows") else {})} for r in lista]
                        for rol, lista in roles.items()},
        "prototypeQuery": query,
        "drillFilterOtherVisuals": True,
    }
    vc = {}
    if titulo:
        vc["title"] = [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": literal(titulo)}}]
    if vc:
        single["vcObjects"] = vc
    if extra_objects:
        single["objects"] = extra_objects
    config = {"name": uuid.uuid4().hex[:20], "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
              "singleVisual": single}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(config, ensure_ascii=False), "filters": "[]"}


def texto(x, y, w, h, contenido, tamano=20, z=0):
    config = {
        "name": uuid.uuid4().hex[:20],
        "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
        "singleVisual": {"visualType": "textbox", "drillFilterOtherVisuals": True, "objects": {"general": [{"properties": {
            "paragraphs": [{"textRuns": [{"value": contenido, "textStyle": {"fontWeight": "bold", "fontSize": f"{tamano}pt"}}]}]}}]}},
    }
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(config, ensure_ascii=False), "filters": "[]"}


def pagina(nombre, titulo, visuales):
    return {"name": nombre, "displayName": titulo, "displayOption": 1, "width": 1280, "height": 720,
            "config": "{}", "filters": "[]", "visualContainers": visuales}


p1 = pagina("Resumen", "Resumen ejecutivo", [
    texto(24, 12, 900, 48, "Cartera y morosidad · corte 30/09/2026", 20),
    visual("slicer", 24, 70, 300, 60, {"Values": ["fEstado.producto"]}, "Producto"),
    visual("slicer", 336, 70, 300, 60, {"Values": ["fEstado.canal"]}, "Canal"),
    visual("slicer", 648, 70, 300, 60, {"Values": ["dAgencia.region"]}, "Región"),
    visual("card", 24, 145, 296, 110, {"Values": ["_Medidas.Saldo Vigente"]}),
    visual("card", 336, 145, 296, 110, {"Values": ["_Medidas.% Mora 30"]}),
    visual("card", 648, 145, 296, 110, {"Values": ["_Medidas.% Mora 90"]}),
    visual("card", 960, 145, 296, 110, {"Values": ["_Medidas.Saldo Castigado"]}),
    visual("lineChart", 24, 270, 616, 430, {"Category": ["dCalendario.Mes"], "Y": ["_Medidas.% Mora 30 Mes"]},
           "Ratio de mora > 30 días por mes"),
    visual("clusteredBarChart", 656, 270, 600, 200, {"Category": ["fEstado.producto"], "Y": ["_Medidas.% Mora 30"]},
           "Mora > 30 días por producto", orden=("_Medidas.% Mora 30", 2)),
    visual("clusteredColumnChart", 656, 485, 600, 215, {"Category": ["dCalendario.Mes"], "Y": ["_Medidas.Saldo Mes"]},
           "Saldo de capital por mes"),
])

p2 = pagina("Agencias", "Agencias", [
    texto(24, 12, 900, 48, "Mora por agencia y tramo de atraso", 20),
    visual("clusteredBarChart", 24, 70, 560, 630, {"Category": ["dAgencia.nombre_agencia"], "Y": ["_Medidas.% Mora 30"]},
           "Mora > 30 días por agencia", orden=("_Medidas.% Mora 30", 2)),
    visual("pivotTable", 600, 70, 656, 630,
           {"Rows": ["dAgencia.nombre_agencia"], "Columns": ["fEstado.tramo_mora"], "Values": ["_Medidas.Saldo Vigente"]},
           "Saldo vigente por agencia y tramo de mora"),
])

p3 = pagina("Cobranza", "Gestión de cobranza", [
    texto(24, 12, 1100, 48, "Lista de gestión: créditos con 1 a 60 días de atraso", 20),
    visual("slicer", 24, 70, 400, 60, {"Values": ["dAgencia.nombre_agencia"]}, "Agencia"),
    visual("card", 440, 70, 300, 60, {"Values": ["_Medidas.Monto Vencido 1-60"]}),
    visual("tableEx", 24, 145, 1232, 555,
           {"Values": ["fEstado.credito_id", "fEstado.cliente_id", "dAgencia.nombre_agencia", "fEstado.producto",
                       "fEstado.dias_atraso", "fEstado.cuotas_vencidas", "_Medidas.Monto Vencido 1-60"]},
           "Priorizar por monto vencido (solo aparecen créditos con 1 a 60 días)",
           orden=("_Medidas.Monto Vencido 1-60", 2)),
])

reporte = {
    "config": json.dumps({"version": "5.43", "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True,
                          "linguisticSchemaSyncVersion": 0, "objects": {}}),
    "layoutOptimization": 0,
    "sections": [p1, p2, p3],
    "filters": "[]",
}

# ---------------------------------------------------------------------------
# 3. Escribir la estructura PBIP
# ---------------------------------------------------------------------------
modelo_dir = RAIZ / f"{NOMBRE}.SemanticModel"
reporte_dir = RAIZ / f"{NOMBRE}.Report"
modelo_dir.mkdir(parents=True, exist_ok=True)
reporte_dir.mkdir(parents=True, exist_ok=True)


def escribir(ruta, contenido):
    ruta.write_text(json.dumps(contenido, indent=2, ensure_ascii=False), encoding="utf-8")


escribir(RAIZ / f"{NOMBRE}.pbip", {"version": "1.0", "artifacts": [{"report": {"path": f"{NOMBRE}.Report"}}],
                                   "settings": {"enableAutoRecovery": True}})
escribir(modelo_dir / "definition.pbism", {"version": "1.0", "settings": {}})
escribir(modelo_dir / "model.bim", modelo)
escribir(reporte_dir / "definition.pbir", {"version": "1.0", "datasetReference": {
    "byPath": {"path": f"../{NOMBRE}.SemanticModel"}, "byConnection": None}})
escribir(reporte_dir / "report.json", reporte)
(RAIZ / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
print(f"Proyecto generado en {RAIZ / (NOMBRE + '.pbip')}")
