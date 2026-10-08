"""
Genera una cartera de créditos SINTÉTICA (datos inventados, ninguna persona real).

Tablas que produce (en la carpeta data/):
    agencias.csv  -> dónde se otorgó el crédito
    clientes.csv  -> quién pidió el crédito
    creditos.csv  -> el préstamo: monto, plazo, tasa, producto
    cuotas.csv    -> el cronograma de pagos y cuándo se pagó cada cuota

Idea de la simulación:
    Cada mes vence una cuota. El cliente puede pagarla, no pagarla (se atrasa)
    o, si ya estaba atrasado, ponerse al día. La probabilidad de atrasarse
    depende del perfil de riesgo del cliente (ingreso, edad, carga financiera,
    producto y canal). Así los datos tienen patrones reales que el análisis
    puede descubrir. Con 6 cuotas impagas el crédito se CASTIGA (se da por
    perdido y sale de la cartera), como hacen las entidades financieras.

Uso:
    python scripts/generar_datos.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 42                                # misma semilla = mismos datos cada vez
FECHA_CORTE = pd.Timestamp("2026-09-30")    # "hoy" para el análisis
N_CLIENTES = 4000
CARPETA_DATOS = Path(__file__).resolve().parent.parent / "data"

rng = np.random.default_rng(SEMILLA)

# ---------------------------------------------------------------------------
# 1. Agencias
# ---------------------------------------------------------------------------
AGENCIAS = [
    (1, "Lima Centro", "Lima"), (2, "San Juan de Lurigancho", "Lima"),
    (3, "Los Olivos", "Lima"), (4, "Ate", "Lima"), (5, "Callao", "Lima"),
    (6, "Arequipa Centro", "Arequipa"), (7, "Trujillo Centro", "La Libertad"),
    (8, "Piura Centro", "Piura"), (9, "Cusco Centro", "Cusco"),
    (10, "Huancayo Centro", "Junín"),
]
agencias = pd.DataFrame(AGENCIAS, columns=["agencia_id", "nombre_agencia", "region"])
# Un poco de riesgo extra por agencia (algunas originan peor que otras)
riesgo_agencia = dict(zip(agencias.agencia_id, rng.normal(0, 0.35, len(agencias))))

# ---------------------------------------------------------------------------
# 2. Clientes
# ---------------------------------------------------------------------------
edades = rng.integers(20, 70, N_CLIENTES)
clientes = pd.DataFrame({
    "cliente_id": np.arange(1, N_CLIENTES + 1),
    "fecha_nacimiento": [
        FECHA_CORTE - pd.DateOffset(years=int(e), days=int(rng.integers(0, 365)))
        for e in edades
    ],
    "sexo": rng.choice(["F", "M"], N_CLIENTES),
    "tipo_empleo": rng.choice(["Dependiente", "Independiente"], N_CLIENTES, p=[0.55, 0.45]),
    # Ingreso con forma "lognormal": la mayoría gana poco y pocos ganan mucho
    "ingreso_mensual": np.round(rng.lognormal(np.log(2800), 0.55, N_CLIENTES), -1),
    "agencia_id": rng.choice(agencias.agencia_id, N_CLIENTES,
                             p=[.16, .14, .12, .10, .08, .10, .09, .08, .07, .06]),
})
# Rasgo oculto: "disciplina de pago" propia de cada persona (no se exporta)
riesgo_personal = rng.normal(0, 0.8, N_CLIENTES)

# ---------------------------------------------------------------------------
# 3. Créditos
# ---------------------------------------------------------------------------
PRODUCTOS = {
    #  nombre:        (prob, monto_mediano, plazos posibles,      TEA mín, TEA máx, ajuste riesgo)
    "Consumo":        (0.60, 8000,   [6, 12, 18, 24, 36],      0.25, 0.60, 0.30),
    "Microempresa":   (0.30, 15000,  [6, 12, 18, 24],          0.30, 0.55, 0.25),
    "Vehicular":      (0.10, 60000,  [24, 36, 48, 60],         0.12, 0.18, -0.90),
}

filas = []
credito_id = 1
inicio, fin = pd.Timestamp("2024-01-01"), pd.Timestamp("2026-06-30")
dias_ventana = (fin - inicio).days
for idx, cli in clientes.iterrows():
    for _ in range(rng.choice([1, 2, 3], p=[0.70, 0.22, 0.08])):
        producto = rng.choice(list(PRODUCTOS), p=[v[0] for v in PRODUCTOS.values()])
        _, mediana, plazos, tea_min, tea_max, _aj = PRODUCTOS[producto]
        if producto == "Microempresa" and cli.tipo_empleo == "Dependiente":
            producto = "Consumo"                     # microempresa solo a independientes
            _, mediana, plazos, tea_min, tea_max, _aj = PRODUCTOS[producto]
        filas.append({
            "credito_id": credito_id,
            "cliente_id": cli.cliente_id,
            "agencia_id": cli.agencia_id,
            "producto": producto,
            "canal": rng.choice(["Agencia", "Digital"], p=[0.65, 0.35]),
            "fecha_desembolso": inicio + pd.Timedelta(days=int(rng.integers(0, dias_ventana))),
            "monto_desembolsado": float(np.round(rng.lognormal(np.log(mediana), 0.45), -2)),
            "plazo_meses": int(rng.choice(plazos)),
            "tea": float(np.round(rng.uniform(tea_min, tea_max), 4)),
        })
        credito_id += 1
creditos = pd.DataFrame(filas)

# Cuota fija (método francés): cuota = P * i / (1 - (1 + i)^-n)
i_mensual = (1 + creditos.tea) ** (1 / 12) - 1
creditos["cuota_mensual"] = np.round(
    creditos.monto_desembolsado * i_mensual / (1 - (1 + i_mensual) ** -creditos.plazo_meses), 2
)


def sigmoide(x):
    return 1 / (1 + np.exp(-x))


# Probabilidad mensual de "saltarse" la cuota estando al día
cli_idx = creditos.cliente_id - 1
edad = edades[cli_idx]
carga = creditos.cuota_mensual / clientes.ingreso_mensual.values[cli_idx]  # cuota / ingreso
puntaje = (
    -5.7
    + creditos.producto.map({k: v[5] for k, v in PRODUCTOS.items()})
    + np.where(creditos.canal == "Digital", 0.35, 0.0)
    + np.where(edad < 25, 0.45, 0.0)
    - 0.45 * np.log(clientes.ingreso_mensual.values[cli_idx] / 2800)
    + 1.2 * (carga - 0.25).clip(lower=-0.2)
    + creditos.agencia_id.map(riesgo_agencia)
    + riesgo_personal[cli_idx]
)
prob_atraso = sigmoide(puntaje).to_numpy()

# ---------------------------------------------------------------------------
# 4. Cronograma de cuotas y simulación de pagos
# ---------------------------------------------------------------------------
# Si el cliente YA está atrasado con n cuotas pendientes, ¿qué tan probable es
# que se ponga al día (pague todo) o que se atrase más (no pague nada)?
PROB_REGULARIZA = {2: 0.50, 3: 0.35, 4: 0.18, 5: 0.10, 6: 0.05}
PROB_EMPEORA = {2: 0.30, 3: 0.40, 4: 0.55, 5: 0.65, 6: 0.75}

# Con 6 cuotas impagas (unos 180 días de atraso) el banco CASTIGA el crédito:
# lo da por perdido y lo saca de la cartera (aunque siga gestionando su cobro).
CUOTAS_PARA_CASTIGO = 6

filas_cuotas = []
fechas_castigo = {}
for k, cr in enumerate(creditos.itertuples(index=False)):
    i = (1 + cr.tea) ** (1 / 12) - 1
    saldo = cr.monto_desembolsado
    pendientes = []                     # cuotas vencidas aún no pagadas
    cuotas_credito = []
    for n in range(1, cr.plazo_meses + 1):
        venc = cr.fecha_desembolso + pd.DateOffset(months=n)
        interes = round(saldo * i, 2)
        amortizacion = round(cr.cuota_mensual - interes, 2) if n < cr.plazo_meses else round(saldo, 2)
        saldo = round(saldo - amortizacion, 2)
        cuota = {
            "credito_id": cr.credito_id, "numero_cuota": n, "fecha_vencimiento": venc,
            "monto_cuota": round(amortizacion + interes, 2), "amortizacion": amortizacion,
            "interes": interes, "fecha_pago": pd.NaT,
        }
        cuotas_credito.append(cuota)
        if venc > FECHA_CORTE or cr.credito_id in fechas_castigo:
            continue                     # cuota futura o crédito castigado: no hay pagos

        pendientes.append(cuota)
        npend = len(pendientes)
        p = prob_atraso[k]
        if npend == 1:                   # estaba al día
            paga_todo, paga_una = 1 - p, 0.0
        else:                            # ya estaba atrasado
            reg = PROB_REGULARIZA.get(npend, 0.02) * (1 - min(p * 3, 0.8))
            emp = PROB_EMPEORA.get(npend, 0.90)
            paga_todo, paga_una = reg, max(0.0, 1 - reg - emp)
        u = rng.random()
        if npend == 1 and u < paga_todo:
            # La mayoría paga antes o el mismo día; algunos con unos días de retraso
            desfase = int(rng.integers(-10, 1)) if rng.random() < 0.85 else int(rng.integers(1, 26))
        else:
            desfase = int(rng.integers(0, 28))
        fecha_pago = venc + pd.Timedelta(days=desfase)
        if fecha_pago > FECHA_CORTE:
            continue                     # el pago caería después del corte: aún no ocurre

        if u < paga_todo:
            a_pagar = pendientes
        elif u < paga_todo + paga_una:
            a_pagar = pendientes[:1]     # paga solo la más antigua
        else:
            a_pagar = []                 # no paga nada este mes
        for c in a_pagar:
            c["fecha_pago"] = fecha_pago
        pendientes = pendientes[len(a_pagar):]   # siempre se pagan las más antiguas
        if len(pendientes) >= CUOTAS_PARA_CASTIGO:
            fechas_castigo[cr.credito_id] = venc
    filas_cuotas.extend(cuotas_credito)

creditos["fecha_castigo"] = creditos.credito_id.map(fechas_castigo)
cuotas = pd.DataFrame(filas_cuotas)
cuotas.insert(0, "cuota_id", np.arange(1, len(cuotas) + 1))

# ---------------------------------------------------------------------------
# 5. Guardar CSV
# ---------------------------------------------------------------------------
CARPETA_DATOS.mkdir(exist_ok=True)
for df, col in [(clientes, "fecha_nacimiento"), (creditos, "fecha_desembolso"),
                (creditos, "fecha_castigo"), (cuotas, "fecha_vencimiento"),
                (cuotas, "fecha_pago")]:
    df[col] = pd.to_datetime(df[col]).dt.date
agencias.to_csv(CARPETA_DATOS / "agencias.csv", index=False)
clientes.to_csv(CARPETA_DATOS / "clientes.csv", index=False)
creditos.to_csv(CARPETA_DATOS / "creditos.csv", index=False)
cuotas.to_csv(CARPETA_DATOS / "cuotas.csv", index=False)

print(f"Agencias: {len(agencias):,} | Clientes: {len(clientes):,} | "
      f"Créditos: {len(creditos):,} | Cuotas: {len(cuotas):,}")
