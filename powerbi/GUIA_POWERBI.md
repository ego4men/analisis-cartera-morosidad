# Guía del dashboard en Power BI

Paso a paso para construir `powerbi/cartera_morosidad.pbix` a partir de los CSV de `powerbi/datos/`
(generados por `scripts/graficos_y_exportacion.py`). Tiempo estimado: 2–3 horas.

## 1. Cargar datos (Power Query)

1. **Inicio → Obtener datos → Texto/CSV** y carga `estado_corte.csv`, `cierre_mensual.csv` y `agencias.csv`.
2. Antes de cargar, pulsa **Transformar datos** (se abre Power Query) y en cada tabla:
   - Revisa los **tipos de datos**: fechas como *Fecha*, montos como *Número decimal* e IDs como *Número entero*.
     Si las fechas salen como texto: clic derecho en la columna → *Cambiar tipo → Usando configuración regional → Inglés (Estados Unidos)*.
   - En `estado_corte`: **Agregar columna → Columna condicional** `estado` = "Vigente" si `tramo_mora` no es "Cancelado" ni "Castigado"; si no, el mismo valor.
   - En `cierre_mensual`: **Agregar columna → Fecha → Mes → Inicio del mes** (`mes`), útil para unirla con el calendario.
3. Renombra las consultas como `fEstado`, `fCierre` y `dAgencia` (f = hecho, d = dimensión).

> 💡 Cada paso queda registrado en **Pasos aplicados**: eso es Power Query, una receta que se repite sola al actualizar.

## 2. Modelo estrella

Crea una tabla calendario con **Modelado → Nueva tabla**:

```DAX
dCalendario =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2024, 1, 1 ), DATE ( 2026, 9, 30 ) ),
    "Año", YEAR ( [Date] ),
    "Mes", FORMAT ( [Date], "mmm-yy" ),
    "InicioMes", DATE ( YEAR ( [Date] ), MONTH ( [Date] ), 1 )
)
```

Márcala como tabla de fechas (**Herramientas de tabla → Marcar como tabla de fechas**). En la vista **Modelo**, crea estas relaciones (uno a varios, filtro en una sola dirección):

| Desde (1) | Hacia (N) |
|---|---|
| `dAgencia[agencia_id]` | `fEstado[agencia_id]` |
| `dAgencia[agencia_id]` | `fCierre[agencia_id]` |
| `dCalendario[Date]` | `fCierre[fecha_cierre]` |

## 3. Medidas DAX

Crea una tabla vacía `_Medidas` (**Inicio → Especificar datos**, sin datos) para guardarlas ordenadas.

```DAX
-- Foto al corte (30/09/2026)
Saldo Vigente =
CALCULATE ( SUM ( fEstado[saldo_capital] ), fEstado[estado] = "Vigente" )

Créditos Vigentes =
CALCULATE ( COUNTROWS ( fEstado ), fEstado[estado] = "Vigente" )

Saldo Mora 30 =
CALCULATE ( [Saldo Vigente], fEstado[dias_atraso] > 30 )

% Mora 30 =
DIVIDE ( [Saldo Mora 30], [Saldo Vigente] )

% Mora 90 =
DIVIDE ( CALCULATE ( [Saldo Vigente], fEstado[dias_atraso] > 90 ), [Saldo Vigente] )

Monto Vencido 1-60 =
CALCULATE ( SUM ( fEstado[monto_vencido] ), fEstado[dias_atraso] >= 1, fEstado[dias_atraso] <= 60 )

Saldo Castigado =
CALCULATE ( SUM ( fEstado[saldo_capital] ), fEstado[estado] = "Castigado" )

-- Evolución mensual
Saldo Mes =
SUM ( fCierre[saldo_capital] )

% Mora 30 Mes =
DIVIDE ( CALCULATE ( [Saldo Mes], fCierre[dias_atraso] > 30 ), [Saldo Mes] )

Var. Mora vs Mes Anterior =
VAR actual   = [% Mora 30 Mes]
VAR anterior = CALCULATE ( [% Mora 30 Mes], DATEADD ( dCalendario[Date], -1, MONTH ) )
RETURN IF ( NOT ISBLANK ( anterior ), actual - anterior )
```

Formato: las medidas con `%` como **Porcentaje con 2 decimales** y los saldos como **Moneda (S/) sin decimales**.

> 💡 **CALCULATE** es la función clave de DAX: calcula una medida *cambiando el filtro*.
> `[Saldo Mora 30]` toma el saldo vigente pero solo de las filas con más de 30 días de atraso.
> **VAR** guarda resultados intermedios para no repetir cálculos y hacer la fórmula legible.

## 4. Páginas del reporte

**Página 1 · Resumen ejecutivo**
- Tarjetas: `Saldo Vigente`, `Créditos Vigentes`, `% Mora 30`, `% Mora 90`, `Saldo Castigado`.
- Gráfico de columnas: `Saldo Mes` por `dCalendario[InicioMes]`.
- Gráfico de líneas: `% Mora 30 Mes` por `dCalendario[InicioMes]` (aparte, **no** en doble eje).
- Barras: `% Mora 30` por `fEstado[producto]`.
- Segmentadores: `producto`, `canal` y `dAgencia[region]`.

**Página 2 · Agencias**
- Barras horizontales: `% Mora 30` por `dAgencia[nombre_agencia]`, ordenadas de mayor a menor, con una **línea constante** en el promedio (panel *Análisis*).
- Matriz: filas `nombre_agencia`, columnas `fEstado[tramo_mora]`, valores `Saldo Vigente`.

**Página 3 · Gestión de cobranza**
- Tabla con `credito_id`, `cliente_id`, `producto`, `dias_atraso`, `cuotas_vencidas`, `monto_vencido` y `saldo_capital`,
  filtrada a `dias_atraso` entre 1 y 60 y ordenada por `monto_vencido`.
- Formato condicional (barras de datos) en `monto_vencido`.

## 5. Cómo validar que todo está bien

Las cifras deben coincidir con el análisis SQL al 30/09/2026:

| Medida | Valor esperado |
|---|---|
| Saldo Vigente | S/ 32 521 168 |
| Créditos Vigentes | 2 981 |
| % Mora 30 | 4,91 % |
| % Mora 30 · Microempresa | 9,07 % |

Al terminar, guarda el archivo como `powerbi/cartera_morosidad.pbix`, exporta capturas de cada página a `img/` (`06_dashboard_resumen.png`, etc.) y agrégalas al README.
