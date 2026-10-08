-- =============================================================================
-- 04_analisis.sql · Preguntas de negocio sobre la cartera
--   psql -U postgres -d cartera -f sql/04_analisis.sql
-- Requiere haber ejecutado 03_vistas.sql.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- P1. ¿Cómo está la cartera hoy por producto? Saldo, mora >30 días y mora >90.
-- Concepto: agregación condicional con FILTER (alternativa a SUM(CASE ...)).
-- -----------------------------------------------------------------------------
SELECT producto,
       COUNT(*)                                                         AS creditos_vigentes,
       ROUND(SUM(saldo_capital))                                        AS saldo_capital,
       ROUND(100.0 * SUM(saldo_capital) FILTER (WHERE dias_atraso > 30)
                   / SUM(saldo_capital), 2)                             AS mora_30_pct,
       ROUND(100.0 * SUM(saldo_capital) FILTER (WHERE dias_atraso > 90)
                   / SUM(saldo_capital), 2)                             AS mora_90_pct
FROM v_estado_corte
WHERE tramo_mora NOT IN ('Cancelado', 'Castigado')
GROUP BY producto
ORDER BY mora_30_pct DESC;


-- -----------------------------------------------------------------------------
-- P2. ¿Cómo se reparte el saldo entre tramos de mora?
-- Concepto: función de ventana SUM() OVER () = total general sin agrupar filas.
-- -----------------------------------------------------------------------------
SELECT tramo_mora,
       COUNT(*)                                                AS creditos,
       ROUND(SUM(saldo_capital))                               AS saldo_capital,
       ROUND(100.0 * SUM(saldo_capital)
                   / SUM(SUM(saldo_capital)) OVER (), 2)       AS pct_saldo
FROM v_estado_corte
WHERE tramo_mora NOT IN ('Cancelado', 'Castigado')
GROUP BY tramo_mora
ORDER BY tramo_mora;


-- -----------------------------------------------------------------------------
-- P3. Roll rates: de un mes al siguiente, ¿a qué tramo pasa cada crédito?
-- Concepto: LAG() trae el valor de la fila anterior dentro de cada crédito.
-- Lectura: de los créditos que estaban "1. 1-30", ¿qué % pasó a "2. 31-60"?
-- -----------------------------------------------------------------------------
WITH transiciones AS (
    SELECT credito_id,
           fecha_cierre,
           LAG(tramo_mora)   OVER (PARTITION BY credito_id ORDER BY fecha_cierre) AS tramo_anterior,
           LAG(fecha_cierre) OVER (PARTITION BY credito_id ORDER BY fecha_cierre) AS cierre_anterior,
           tramo_mora AS tramo_actual
    FROM cierre_mensual
    WHERE fecha_cierre >= DATE '2025-01-31'          -- último año y medio
)
SELECT tramo_anterior,
       ROUND(100.0 * COUNT(*) FILTER (WHERE tramo_actual = '0. Al día') / COUNT(*), 1) AS a_al_dia,
       ROUND(100.0 * COUNT(*) FILTER (WHERE tramo_actual = '1. 1-30')   / COUNT(*), 1) AS a_1_30,
       ROUND(100.0 * COUNT(*) FILTER (WHERE tramo_actual = '2. 31-60')  / COUNT(*), 1) AS a_31_60,
       ROUND(100.0 * COUNT(*) FILTER (WHERE tramo_actual = '3. 61-90')  / COUNT(*), 1) AS a_61_90,
       ROUND(100.0 * COUNT(*) FILTER (WHERE tramo_actual = '4. 90+')    / COUNT(*), 1) AS a_90_mas,
       COUNT(*) AS casos
FROM transiciones
WHERE tramo_anterior IS NOT NULL
  AND fecha_cierre = (cierre_anterior + INTERVAL '1 day' + INTERVAL '1 month' - INTERVAL '1 day')::date
GROUP BY tramo_anterior
ORDER BY tramo_anterior;


-- -----------------------------------------------------------------------------
-- P4. Cosechas (vintage): ¿qué trimestres de desembolso salieron peores?
-- % de créditos que llegaron a más de 30 días de atraso dentro de sus
-- primeros 6 meses de vida (MOB = month on book, meses desde el desembolso).
-- Concepto: comparar "manzanas con manzanas" (todos con la misma antigüedad).
-- -----------------------------------------------------------------------------
WITH vida AS (
    SELECT c.credito_id,
           DATE_TRUNC('quarter', c.fecha_desembolso)::date AS cosecha,
           cm.dias_atraso,
           (EXTRACT(YEAR FROM AGE(cm.fecha_cierre, c.fecha_desembolso)) * 12
            + EXTRACT(MONTH FROM AGE(cm.fecha_cierre, c.fecha_desembolso)))::int AS mob
    FROM creditos c
    JOIN cierre_mensual cm ON cm.credito_id = c.credito_id
),
por_credito AS (
    SELECT credito_id, cosecha,
           BOOL_OR(dias_atraso > 30 AND mob <= 6) AS cayo_30_en_6m
    FROM vida
    GROUP BY credito_id, cosecha
)
SELECT TO_CHAR(cosecha, 'YYYY-"T"Q')                              AS cosecha,
       COUNT(*)                                                   AS creditos,
       ROUND(100.0 * COUNT(*) FILTER (WHERE cayo_30_en_6m) / COUNT(*), 2) AS pct_mora30_mob6
FROM por_credito
WHERE cosecha <= DATE '2026-01-01'          -- solo cosechas con al menos 6 meses de vida
GROUP BY cosecha
ORDER BY cosecha;


-- -----------------------------------------------------------------------------
-- P5. Ranking de agencias por mora y comparación con el promedio.
-- Conceptos: RANK(), NTILE() y AVG() OVER () como ventanas.
-- -----------------------------------------------------------------------------
WITH mora_agencia AS (
    SELECT a.nombre_agencia,
           a.region,
           SUM(e.saldo_capital)                                          AS saldo,
           100.0 * SUM(e.saldo_capital) FILTER (WHERE e.dias_atraso > 30)
                 / SUM(e.saldo_capital)                                  AS mora_30
    FROM v_estado_corte e
    JOIN agencias a ON a.agencia_id = e.agencia_id
    WHERE e.tramo_mora NOT IN ('Cancelado', 'Castigado')
    GROUP BY a.nombre_agencia, a.region
)
SELECT RANK()   OVER (ORDER BY mora_30 DESC)            AS ranking_mora,
       nombre_agencia,
       region,
       ROUND(saldo)                                     AS saldo,
       ROUND(mora_30, 2)                                AS mora_30_pct,
       ROUND(mora_30 - AVG(mora_30) OVER (), 2)         AS dif_vs_promedio,
       NTILE(3) OVER (ORDER BY mora_30 DESC)            AS tercil   -- 1 = peor tercio
FROM mora_agencia
ORDER BY ranking_mora;


-- -----------------------------------------------------------------------------
-- P6. Lista de gestión de cobranza: los 5 casos prioritarios por agencia.
-- Concepto: ROW_NUMBER() OVER (PARTITION BY ...) para el "top N por grupo".
-- Prioridad: créditos en 1-60 días (aún recuperables) con mayor monto vencido.
-- -----------------------------------------------------------------------------
WITH candidatos AS (
    SELECT e.*,
           a.nombre_agencia,
           ROW_NUMBER() OVER (PARTITION BY e.agencia_id
                              ORDER BY e.monto_vencido DESC) AS prioridad
    FROM v_estado_corte e
    JOIN agencias a ON a.agencia_id = e.agencia_id
    WHERE e.dias_atraso BETWEEN 1 AND 60
)
SELECT nombre_agencia, prioridad, credito_id, cliente_id, producto,
       dias_atraso, cuotas_vencidas, monto_vencido, saldo_capital
FROM candidatos
WHERE prioridad <= 5
ORDER BY nombre_agencia, prioridad;
