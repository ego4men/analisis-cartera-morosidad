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
        medida("Var. Mora 30 vs Mes Anterior",
               "VAR ultimo = MAX ( fCierre[fecha_cierre] )\n"
               "VAR previo = EOMONTH ( ultimo, -1 )\n"
               "RETURN CALCULATE ( [% Mora 30 Mes], fCierre[fecha_cierre] = ultimo )\n"
               "     - CALCULATE ( [% Mora 30 Mes], fCierre[fecha_cierre] = previo )",
               "+0.00%;-0.00%;0.00%", "Evolución"),
        medida("Créditos 1-60",
               "CALCULATE ( COUNTROWS ( fEstado ), fEstado[dias_atraso] >= 1, fEstado[dias_atraso] <= 60 )",
               ENTERO, "Cobranza"),
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


def visual(tipo, x, y, w, h, roles, titulo=None, orden=None, z=0, extra_objects=None, contenedor=None):
    refs = [r for lista in roles.values() for r in lista]
    tablas = sorted({r.split(".")[0] for r in refs})
    query = {"Version": 2,
             "From": [{"Name": ALIAS[t], "Entity": t, "Type": 0} for t in tablas],
             "Select": [campo(r) for r in refs]}
    if orden:
        ref, direccion = orden
        query["OrderBy"] = [{"Direction": direccion, "Expression": {k: v for k, v in campo(ref).items()
                                                                    if k in ("Measure", "Column")}}]
    single = {"visualType": tipo, "drillFilterOtherVisuals": True}
    if roles:
        single["projections"] = {rol: [{"queryRef": r, **({"active": True} if rol in ("Category", "Rows") else {})}
                                       for r in lista] for rol, lista in roles.items()}
        single["prototypeQuery"] = query
    vc = dict(contenedor or {})
    if titulo:
        vc["title"] = [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": literal(titulo)}}]
    if vc:
        single["vcObjects"] = vc
    if extra_objects:
        single["objects"] = extra_objects
    config = {"name": uuid.uuid4().hex[:20], "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
              "singleVisual": single}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(config, ensure_ascii=False), "filters": "[]"}


def texto(x, y, w, h, contenido, tamano=20, z=0, subtitulo=None, fondo=None):
    parrafos = [{"textRuns": [{"value": contenido, "textStyle": {"fontWeight": "bold", "fontSize": f"{tamano}pt",
                                                                  "color": "#FFFFFF"}}]}]
    if subtitulo:
        parrafos.append({"textRuns": [{"value": subtitulo, "textStyle": {"fontSize": "10pt", "color": "#9FB0BF"}}]})
    single = {"visualType": "textbox", "drillFilterOtherVisuals": True,
              "objects": {"general": [{"properties": {"paragraphs": parrafos}}]}}
    if fondo:
        verdadero, falso = {"expr": {"Literal": {"Value": "true"}}}, {"expr": {"Literal": {"Value": "false"}}}
        single["vcObjects"] = {
            "background": [{"properties": {"show": verdadero,
                                           "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{fondo}'"}}}}},
                                           "transparency": {"expr": {"Literal": {"Value": "0D"}}}}}],
            "border": [{"properties": {"show": falso}}],
            "dropShadow": [{"properties": {"show": falso}}],
            "padding": [{"properties": {"top": {"expr": {"Literal": {"Value": "14D"}}},
                                        "left": {"expr": {"Literal": {"Value": "24D"}}}}}],
        }
    config = {"name": uuid.uuid4().hex[:20], "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
              "singleVisual": single}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(config, ensure_ascii=False), "filters": "[]"}


def pagina(nombre, titulo, visuales):
    return {"name": nombre, "displayName": titulo, "displayOption": 1, "width": 1280, "height": 720,
            "config": "{}", "filters": "[]", "visualContainers": visuales}


def L(valor):
    return {"expr": {"Literal": {"Value": valor}}}


def color(hexa):
    return {"solid": {"color": L(f"'{hexa}'")}}


# Paleta semántica (coincide con el tema tema_cartera_riesgo.json)
VERDE, AMBAR, NARANJA, ROJO, AZUL = "#2BD9A4", "#F2B84B", "#F0874B", "#E5484D", "#5AA9E6"
FONDO_CABECERA = "#102231"

SEGMENTADOR = {"data": [{"properties": {"mode": L("'Dropdown'")}}], "header": [{"properties": {"show": L("false")}}]}


def tarjeta(valor_color="#FFFFFF", moneda=False):
    props = {"color": color(valor_color)}
    if moneda:
        props.update({"labelDisplayUnits": L("1D"), "labelPrecision": L("0L")})
    return {"labels": [{"properties": props}]}


def relleno(hexa):
    return {"dataPoint": [{"properties": {"fill": color(hexa)}}]}


EJE_FECHA = {"categoryAxis": [{"properties": {"axisType": L("'Scalar'"), "showAxisTitle": L("false")}}],
             "valueAxis": [{"properties": {"showAxisTitle": L("false")}}]}
SIN_TITULOS = {"categoryAxis": [{"properties": {"showAxisTitle": L("false")}}],
               "valueAxis": [{"properties": {"showAxisTitle": L("false")}}]}
ETIQUETAS = {"labels": [{"properties": {"show": L("true")}}]}
MARCADORES = {"lineStyles": [{"properties": {"showMarker": L("true"), "strokeWidth": L("3D")}}]}


def combinar(*partes):
    salida = {}
    for p in partes:
        salida.update(p)
    return salida


def cabecera(titulo, subtitulo):
    """Banda superior con título, subtítulo y navegación entre páginas."""
    return [
        texto(0, 0, 1280, 76, titulo, 18, subtitulo=subtitulo, fondo=FONDO_CABECERA),
        visual("pageNavigator", 820, 18, 440, 40, {}, z=1000, contenedor={
            "background": [{"properties": {"show": L("false")}}], "border": [{"properties": {"show": L("false")}}],
            "dropShadow": [{"properties": {"show": L("false")}}]}),
    ]


p1 = pagina("Resumen", "Resumen ejecutivo", cabecera(
    "Cartera y morosidad", "Resumen ejecutivo · corte 30/09/2026 · datos sintéticos") + [
    visual("slicer", 24, 92, 296, 64, {"Values": ["fEstado.producto"]}, "Producto", extra_objects=SEGMENTADOR),
    visual("slicer", 336, 92, 296, 64, {"Values": ["fEstado.canal"]}, "Canal", extra_objects=SEGMENTADOR),
    visual("slicer", 648, 92, 296, 64, {"Values": ["dAgencia.region"]}, "Región", extra_objects=SEGMENTADOR),
    visual("card", 960, 92, 296, 64, {"Values": ["_Medidas.Créditos Vigentes"]}, extra_objects=tarjeta()),
    visual("card", 24, 172, 296, 96, {"Values": ["_Medidas.Saldo Vigente"]}, extra_objects=tarjeta(moneda=True)),
    visual("card", 336, 172, 296, 96, {"Values": ["_Medidas.% Mora 30"]}, extra_objects=tarjeta(AMBAR)),
    visual("card", 648, 172, 296, 96, {"Values": ["_Medidas.Var. Mora 30 vs Mes Anterior"]}, extra_objects=tarjeta(NARANJA)),
    visual("card", 960, 172, 296, 96, {"Values": ["_Medidas.Saldo Castigado"]}, extra_objects=tarjeta(ROJO, moneda=True)),
    visual("lineChart", 24, 284, 616, 420, {"Category": ["fCierre.fecha_cierre"], "Y": ["_Medidas.% Mora 30 Mes"]},
           "Ratio de mora > 30 días por mes", extra_objects=combinar(EJE_FECHA, relleno(AMBAR), MARCADORES)),
    visual("clusteredBarChart", 656, 284, 600, 196, {"Category": ["fEstado.producto"], "Y": ["_Medidas.% Mora 30"]},
           "Mora > 30 días por producto", orden=("_Medidas.% Mora 30", 2),
           extra_objects=combinar(SIN_TITULOS, relleno(AMBAR), ETIQUETAS)),
    visual("clusteredColumnChart", 656, 496, 600, 208, {"Category": ["fCierre.fecha_cierre"], "Y": ["_Medidas.Saldo Mes"]},
           "Saldo de capital por mes", extra_objects=combinar(EJE_FECHA, relleno(AZUL))),
])

p2 = pagina("Agencias", "Agencias", cabecera(
    "Riesgo por agencia", "Mora y composición del saldo por tramo de atraso · corte 30/09/2026") + [
    visual("clusteredBarChart", 24, 92, 520, 612, {"Category": ["dAgencia.nombre_agencia"], "Y": ["_Medidas.% Mora 30"]},
           "Mora > 30 días por agencia", orden=("_Medidas.% Mora 30", 2),
           extra_objects=combinar(SIN_TITULOS, relleno(AMBAR), ETIQUETAS)),
    visual("hundredPercentStackedBarChart", 560, 92, 696, 300,
           {"Category": ["dAgencia.nombre_agencia"], "Series": ["fEstado.tramo_mora"], "Y": ["_Medidas.Saldo Vigente"]},
           "Composición del saldo vigente por tramo de mora", extra_objects=SIN_TITULOS),
    visual("pivotTable", 560, 408, 696, 296,
           {"Rows": ["dAgencia.nombre_agencia"], "Columns": ["fEstado.tramo_mora"], "Values": ["_Medidas.Saldo Vigente"]},
           "Saldo vigente por agencia y tramo (S/)"),
])

p3 = pagina("Cobranza", "Gestión de cobranza", cabecera(
    "Gestión de cobranza", "Créditos con 1 a 60 días de atraso, priorizados por monto vencido") + [
    visual("slicer", 24, 92, 296, 64, {"Values": ["dAgencia.nombre_agencia"]}, "Agencia", extra_objects=SEGMENTADOR),
    visual("slicer", 336, 92, 296, 64, {"Values": ["fEstado.producto"]}, "Producto", extra_objects=SEGMENTADOR),
    visual("card", 648, 92, 296, 64, {"Values": ["_Medidas.Monto Vencido 1-60"]}, extra_objects=tarjeta(AMBAR, moneda=True)),
    visual("card", 960, 92, 296, 64, {"Values": ["_Medidas.Créditos 1-60"]}, extra_objects=tarjeta()),
    visual("tableEx", 24, 172, 820, 532,
           {"Values": ["fEstado.credito_id", "dAgencia.nombre_agencia", "fEstado.producto",
                       "fEstado.dias_atraso", "fEstado.cuotas_vencidas", "_Medidas.Monto Vencido 1-60"]},
           "Lista de gestión priorizada", orden=("_Medidas.Monto Vencido 1-60", 2)),
    visual("clusteredBarChart", 860, 172, 396, 260, {"Category": ["fEstado.producto"], "Y": ["_Medidas.Monto Vencido 1-60"]},
           "Monto vencido 1-60 por producto", orden=("_Medidas.Monto Vencido 1-60", 2),
           extra_objects=combinar(SIN_TITULOS, relleno(AZUL), ETIQUETAS)),
    visual("clusteredBarChart", 860, 448, 396, 256, {"Category": ["dAgencia.nombre_agencia"], "Y": ["_Medidas.Créditos 1-60"]},
           "Créditos por gestionar por agencia", orden=("_Medidas.Créditos 1-60", 2),
           extra_objects=combinar(SIN_TITULOS, relleno(VERDE), ETIQUETAS)),
])

# Tema base: Power BI Desktop exige uno (se copia desde la instalación local de Power BI)
TEMA = "CY24SU10"
TEMA_PROPIO = "CarteraRiesgo.json"   # tema de diseño propio: powerbi/tema_cartera_riesgo.json
reporte = {
    "config": json.dumps({"version": "5.65", "themeCollection": {"baseTheme": {"name": TEMA, "version": "5.59", "type": 2},
                                                               "customTheme": {"name": TEMA_PROPIO, "version": "5.59", "type": 1}},
                          "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True,
                          "linguisticSchemaSyncVersion": 0, "objects": {}}),
    "layoutOptimization": 0,
    "resourcePackages": [{"resourcePackage": {"name": "SharedResources", "type": 2, "disabled": False,
                                              "items": [{"type": 202, "path": f"BaseThemes/{TEMA}.json", "name": TEMA}]}},
                         {"resourcePackage": {"name": "RegisteredResources", "type": 1, "disabled": False,
                                              "items": [{"type": 202, "path": TEMA_PROPIO, "name": TEMA_PROPIO}]}}],
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
tema_dir = reporte_dir / "StaticResources" / "SharedResources" / "BaseThemes"
tema_dir.mkdir(parents=True, exist_ok=True)
tema_origen = Path(r"C:\Program Files\Microsoft Power BI Desktop\bin\WebView2Resources\minerva\SHAREDRESOURCES\BASETHEMES") / f"{TEMA}.JSON"
if tema_origen.exists():
    (tema_dir / f"{TEMA}.json").write_bytes(tema_origen.read_bytes())
elif not (tema_dir / f"{TEMA}.json").exists():
    raise FileNotFoundError(f"No se encontró el tema base {TEMA}: instala Power BI Desktop o copia el archivo a {tema_dir}")
registrados = reporte_dir / "StaticResources" / "RegisteredResources"
registrados.mkdir(parents=True, exist_ok=True)
(registrados / TEMA_PROPIO).write_bytes((RAIZ / "tema_cartera_riesgo.json").read_bytes())
(RAIZ / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
print(f"Proyecto generado en {RAIZ / (NOMBRE + '.pbip')}")
