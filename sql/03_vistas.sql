-- =============================================================================
-- 03_vistas.sql · Capa analítica: estado de cada crédito y cierres mensuales
--   psql -U postgres -d cartera -f sql/03_vistas.sql
--
-- Conceptos que se practican:
--   * CTE (WITH ...): dividir una consulta difícil en pasos con nombre.
--   * LEFT JOIN + COALESCE: conservar créditos aunque no tengan cuotas impagas.
--   * CASE: convertir días de atraso en tramos.
--   * generate_series: crear una fila por cada fin de mes.
--   * VIEW y MATERIALIZED VIEW: guardar una consulta para reutilizarla.
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS cierre_mensual;
DROP VIEW IF EXISTS v_estado_corte;

-- -----------------------------------------------------------------------------
-- 1) v_estado_corte: foto de cada crédito al 30/09/2026 (fecha de corte)
-- -----------------------------------------------------------------------------
CREATE VIEW v_estado_corte AS
WITH parametros AS (
    SELECT DATE '2026-09-30' AS fecha_corte
),
-- Cuotas que a la fecha de corte siguen sin pagarse
cuotas_impagas AS (
    SELECT cu.credito_id,
           cu.fecha_vencimiento,
           cu.amortizacion,
           cu.monto_cuota,
           p.fecha_corte
    FROM cuotas cu
    CROSS JOIN parametros p
    WHERE cu.fecha_pago IS NULL OR cu.fecha_pago > p.fecha_corte
),
-- Por crédito: saldo de capital, cuota vencida más antigua y monto vencido
resumen AS (
    SELECT credito_id,
           SUM(amortizacion)                                              AS saldo_capital,
           MIN(fecha_vencimiento) FILTER (WHERE fecha_vencimiento < fecha_corte) AS primera_vencida,
           COUNT(*)               FILTER (WHERE fecha_vencimiento < fecha_corte) AS cuotas_vencidas,
           COALESCE(SUM(monto_cuota) FILTER (WHERE fecha_vencimiento < fecha_corte), 0) AS monto_vencido
    FROM cuotas_impagas
    GROUP BY credito_id
)
SELECT c.credito_id,
       c.cliente_id,
       c.agencia_id,
       c.producto,
       c.canal,
       c.fecha_desembolso,
       c.monto_desembolsado,
       COALESCE(r.saldo_capital, 0)                         AS saldo_capital,
       COALESCE(r.cuotas_vencidas, 0)                       AS cuotas_vencidas,
       COALESCE(r.monto_vencido, 0)                         AS monto_vencido,
       COALESCE(p.fecha_corte - r.primera_vencida, 0)       AS dias_atraso,
       CASE
           WHEN c.fecha_castigo <= p.fecha_corte          THEN 'Castigado'
           WHEN COALESCE(r.saldo_capital, 0) = 0          THEN 'Cancelado'
           WHEN r.primera_vencida IS NULL                 THEN '0. Al día'
           WHEN p.fecha_corte - r.primera_vencida <= 30   THEN '1. 1-30'
           WHEN p.fecha_corte - r.primera_vencida <= 60   THEN '2. 31-60'
           WHEN p.fecha_corte - r.primera_vencida <= 90   THEN '3. 61-90'
           ELSE                                                '4. 90+'
       END                                                  AS tramo_mora
FROM creditos c
CROSS JOIN parametros p
LEFT JOIN resumen r ON r.credito_id = c.credito_id;


-- -----------------------------------------------------------------------------
-- 2) cierre_mensual: la misma foto, pero para CADA fin de mes desde ene-2024.
--    Es la base para ver la evolución de la mora y calcular roll rates.
--    Se materializa (se guarda el resultado) porque es costosa de calcular.
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW cierre_mensual AS
WITH meses AS (
    -- Último día de cada mes: inicio del mes siguiente menos 1 día
    SELECT (m + INTERVAL '1 month' - INTERVAL '1 day')::date AS fecha_cierre
    FROM generate_series(DATE '2024-01-01', DATE '2026-09-01', INTERVAL '1 month') AS m
),
-- Créditos vivos en cada cierre: ya desembolsados y aún no castigados
creditos_mes AS (
    SELECT m.fecha_cierre, c.credito_id, c.producto, c.canal, c.agencia_id
    FROM meses m
    JOIN creditos c
      ON c.fecha_desembolso <= m.fecha_cierre
     AND (c.fecha_castigo IS NULL OR c.fecha_castigo > m.fecha_cierre)
),
impagas_mes AS (
    SELECT cm.fecha_cierre,
           cm.credito_id,
           SUM(cu.amortizacion)                                                AS saldo_capital,
           MIN(cu.fecha_vencimiento) FILTER (WHERE cu.fecha_vencimiento < cm.fecha_cierre) AS primera_vencida
    FROM creditos_mes cm
    JOIN cuotas cu
      ON cu.credito_id = cm.credito_id
     AND (cu.fecha_pago IS NULL OR cu.fecha_pago > cm.fecha_cierre)
    GROUP BY cm.fecha_cierre, cm.credito_id
)
SELECT cm.fecha_cierre,
       cm.credito_id,
       cm.producto,
       cm.canal,
       cm.agencia_id,
       i.saldo_capital,
       COALESCE(cm.fecha_cierre - i.primera_vencida, 0) AS dias_atraso,
       CASE
           WHEN i.primera_vencida IS NULL                  THEN '0. Al día'
           WHEN cm.fecha_cierre - i.primera_vencida <= 30  THEN '1. 1-30'
           WHEN cm.fecha_cierre - i.primera_vencida <= 60  THEN '2. 31-60'
           WHEN cm.fecha_cierre - i.primera_vencida <= 90  THEN '3. 61-90'
           ELSE                                                 '4. 90+'
       END AS tramo_mora
FROM creditos_mes cm
JOIN impagas_mes i                       -- solo créditos con saldo (> 0) en ese mes
  ON i.fecha_cierre = cm.fecha_cierre
 AND i.credito_id   = cm.credito_id;

CREATE INDEX idx_cierre_credito_fecha ON cierre_mensual (credito_id, fecha_cierre);
