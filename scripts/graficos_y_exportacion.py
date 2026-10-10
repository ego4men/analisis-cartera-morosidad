"""
Lee las vistas de PostgreSQL, genera los gráficos del README (img/) y exporta
las tablas que consume el dashboard de Power BI (powerbi/datos/).

Conexión: usa las variables de entorno estándar de PostgreSQL, así la
contraseña nunca queda escrita en el código. En PowerShell:
    $env:PGPASSWORD = "tu_contraseña"      # solo vive en esa ventana
    python scripts/graficos_y_exportacion.py
Opcionales: PGHOST (localhost), PGPORT (5432), PGUSER (postgres), PGDATABASE (cartera).
"""
import os
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd
import psycopg2

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

RAIZ = Path(__file__).resolve().parent.parent
IMG = RAIZ / "img"
PBI = RAIZ / "powerbi" / "datos"
IMG.mkdir(exist_ok=True)
PBI.mkdir(parents=True, exist_ok=True)

# Paleta (validada para daltonismo) y estilo sobrio
AZUL, NARANJA, AGUA = "#2a78d6", "#eb6834", "#1baf7a"
TEXTO, TEXTO_2, GRILLA = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.family": "Segoe UI", "font.size": 10, "axes.edgecolor": GRILLA,
    "axes.labelcolor": TEXTO_2, "xtick.color": TEXTO_2, "ytick.color": TEXTO_2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRILLA, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": TEXTO,
    "axes.titlelocation": "left", "figure.dpi": 150, "savefig.bbox": "tight",
})

conexion = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"), port=os.getenv("PGPORT", "5432"),
    user=os.getenv("PGUSER", "postgres"), dbname=os.getenv("PGDATABASE", "cartera"),
)


def consulta(sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, conexion)


# ---------------------------------------------------------------------------
# 1. Exportación para Power BI (modelo estrella: 2 hechos + dimensiones)
# ---------------------------------------------------------------------------
consulta("SELECT * FROM v_estado_corte").to_csv(PBI / "estado_corte.csv", index=False)
consulta("SELECT * FROM cierre_mensual").to_csv(PBI / "cierre_mensual.csv", index=False)
consulta("SELECT * FROM agencias").to_csv(PBI / "agencias.csv", index=False)

# ---------------------------------------------------------------------------
# 2. Evolución mensual: saldo y mora > 30 días (dos gráficos, un eje cada uno)
# ---------------------------------------------------------------------------
evol = consulta("""
    SELECT fecha_cierre,
           SUM(saldo_capital) / 1e6 AS saldo_mm,
           SUM(saldo_capital) FILTER (WHERE dias_atraso > 30) / SUM(saldo_capital) AS mora_30
    FROM cierre_mensual GROUP BY fecha_cierre ORDER BY fecha_cierre
""")
evol = evol[evol.fecha_cierre >= pd.Timestamp("2024-06-30").date()]
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True,
                               gridspec_kw={"height_ratios": [1, 1.2]})
ax1.bar(evol.fecha_cierre, evol.saldo_mm, width=20, color=AZUL)
ax1.set_title("Saldo de capital (millones de S/)")
ax2.plot(evol.fecha_cierre, evol.mora_30, color=NARANJA, linewidth=2, marker="o", markersize=4)
ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=1))
ax2.set_ylim(0, evol.mora_30.max() * 1.15)
ax2.set_title("Ratio de mora > 30 días")
ultimo = evol.iloc[-1]
ax2.annotate(f"{ultimo.mora_30:.1%}", (ultimo.fecha_cierre, ultimo.mora_30),
             xytext=(6, 0), textcoords="offset points", va="center", color=TEXTO, fontweight="bold")
fig.tight_layout()
fig.savefig(IMG / "01_evolucion_saldo_mora.png")
plt.close(fig)

# ---------------------------------------------------------------------------
# 3. Mora por producto
# ---------------------------------------------------------------------------
prod = consulta("""
    SELECT producto,
           SUM(saldo_capital) FILTER (WHERE dias_atraso > 30) / SUM(saldo_capital) AS mora_30
    FROM v_estado_corte WHERE tramo_mora NOT IN ('Cancelado', 'Castigado')
    GROUP BY producto ORDER BY mora_30
""")
fig, ax = plt.subplots(figsize=(7, 2.6))
ax.barh(prod.producto, prod.mora_30, color=AZUL, height=0.55)
for y, v in enumerate(prod.mora_30):
    ax.text(v + 0.002, y, f"{v:.1%}", va="center", color=TEXTO)
ax.xaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=0))
ax.grid(axis="y", visible=False)
ax.set_title("Mora > 30 días por producto (corte 30/09/2026)")
fig.savefig(IMG / "02_mora_producto.png")
plt.close(fig)

# ---------------------------------------------------------------------------
# 4. Matriz de roll rates (mapa de calor, una sola tonalidad)
# ---------------------------------------------------------------------------
roll = consulta("""
    WITH t AS (
        SELECT fecha_cierre, tramo_mora AS hacia,
               LAG(tramo_mora)   OVER w AS desde,
               LAG(fecha_cierre) OVER w AS cierre_ant
        FROM cierre_mensual
        WHERE fecha_cierre >= DATE '2025-01-31'
        WINDOW w AS (PARTITION BY credito_id ORDER BY fecha_cierre)
    )
    SELECT desde, hacia, COUNT(*) AS n FROM t
    WHERE desde IS NOT NULL
      AND fecha_cierre = (cierre_ant + INTERVAL '1 day' + INTERVAL '1 month' - INTERVAL '1 day')::date
    GROUP BY desde, hacia
""")
matriz = roll.pivot(index="desde", columns="hacia", values="n").fillna(0)
matriz = matriz.div(matriz.sum(axis=1), axis=0)
etiquetas = ["Al día", "1-30", "31-60", "61-90", "90+"]
fig, ax = plt.subplots(figsize=(6.4, 4.6))
ax.imshow(matriz.values, cmap="Blues", vmin=0, vmax=1)
ax.set_xticks(range(5), etiquetas)
ax.set_yticks(range(5), etiquetas)
ax.grid(False)
for i in range(5):
    for j in range(5):
        v = matriz.values[i, j]
        ax.text(j, i, f"{v:.0%}", ha="center", va="center",
                color="white" if v > 0.55 else TEXTO, fontsize=9)
ax.set_xlabel("Tramo al mes siguiente")
ax.set_ylabel("Tramo este mes")
ax.set_title("Roll rates mensuales (ene-2025 a sep-2026)")
fig.savefig(IMG / "03_roll_rates.png")
plt.close(fig)

# ---------------------------------------------------------------------------
# 5. Ranking de agencias vs. promedio
# ---------------------------------------------------------------------------
ag = consulta("""
    SELECT a.nombre_agencia,
           SUM(e.saldo_capital) FILTER (WHERE e.dias_atraso > 30) / SUM(e.saldo_capital) AS mora_30
    FROM v_estado_corte e JOIN agencias a USING (agencia_id)
    WHERE e.tramo_mora NOT IN ('Cancelado', 'Castigado')
    GROUP BY a.nombre_agencia ORDER BY mora_30
""")
total = consulta("""
    SELECT SUM(saldo_capital) FILTER (WHERE dias_atraso > 30) / SUM(saldo_capital) AS m
    FROM v_estado_corte WHERE tramo_mora NOT IN ('Cancelado', 'Castigado')
""").m[0]
fig, ax = plt.subplots(figsize=(7.5, 4.4))
colores = [NARANJA if v > total else AZUL for v in ag.mora_30]
ax.barh(ag.nombre_agencia, ag.mora_30, color=colores, height=0.6)
ax.axvline(total, color=TEXTO_2, linestyle="--", linewidth=1)
ax.text(total, -0.9, f" Cartera total {total:.1%}", color=TEXTO_2, va="center")
ax.set_ylim(-1.3, len(ag) - 0.5)
for y, v in enumerate(ag.mora_30):
    ax.text(v + 0.002, y, f"{v:.1%}", va="center", color=TEXTO, fontsize=9)
ax.xaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=0))
ax.grid(axis="y", visible=False)
ax.set_title("Mora > 30 días por agencia (naranja = sobre el promedio)")
fig.savefig(IMG / "04_ranking_agencias.png")
plt.close(fig)

# ---------------------------------------------------------------------------
# 6. Cosechas: % que cayó en mora > 30 en sus primeros 6 meses
# ---------------------------------------------------------------------------
cos = consulta("""
    WITH vida AS (
        SELECT c.credito_id, DATE_TRUNC('quarter', c.fecha_desembolso)::date AS cosecha,
               cm.dias_atraso,
               (EXTRACT(YEAR FROM AGE(cm.fecha_cierre, c.fecha_desembolso)) * 12
                + EXTRACT(MONTH FROM AGE(cm.fecha_cierre, c.fecha_desembolso)))::int AS mob
        FROM creditos c JOIN cierre_mensual cm USING (credito_id)
    ), x AS (
        SELECT credito_id, cosecha, BOOL_OR(dias_atraso > 30 AND mob <= 6) AS cayo
        FROM vida GROUP BY credito_id, cosecha
    )
    SELECT TO_CHAR(cosecha, 'YYYY-"T"Q') AS cosecha, AVG(cayo::int) AS pct
    FROM x WHERE cosecha <= DATE '2026-01-01' GROUP BY cosecha ORDER BY cosecha
""")
fig, ax = plt.subplots(figsize=(7.5, 3.2))
ax.bar(cos.cosecha, cos.pct, color=AGUA, width=0.6)
for x, v in enumerate(cos.pct):
    ax.text(x, v + 0.001, f"{v:.1%}", ha="center", va="bottom", color=TEXTO, fontsize=9)
ax.set_ylim(0, cos.pct.max() * 1.18)
ax.yaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=0))
ax.grid(axis="x", visible=False)
ax.set_title("Cosechas: % de créditos con mora > 30 días en sus primeros 6 meses")
fig.savefig(IMG / "05_cosechas.png")
plt.close(fig)

conexion.close()
print("Gráficos en img/ y datos para Power BI en powerbi/datos/")
