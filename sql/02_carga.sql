-- =============================================================================
-- 02_carga.sql · Carga los CSV de data/ en las tablas
-- Ejecutar DESDE LA CARPETA DEL PROYECTO (las rutas son relativas):
--   psql -U postgres -d cartera -f sql/02_carga.sql
--
-- \copy es un comando de psql (no de SQL): lee el archivo desde TU PC y lo
-- envía al servidor. El orden importa: primero las tablas "padre".
-- =============================================================================

-- Los CSV están en UTF-8: se lo decimos a psql para que respete las tildes
SET client_encoding = 'UTF8';

\copy agencias FROM 'data/agencias.csv' WITH (FORMAT csv, HEADER true)
\copy clientes FROM 'data/clientes.csv' WITH (FORMAT csv, HEADER true)
\copy creditos FROM 'data/creditos.csv' WITH (FORMAT csv, HEADER true)
\copy cuotas   FROM 'data/cuotas.csv'   WITH (FORMAT csv, HEADER true)

-- Verificación: cuántas filas quedaron en cada tabla
SELECT 'agencias' AS tabla, COUNT(*) AS filas FROM agencias
UNION ALL SELECT 'clientes', COUNT(*) FROM clientes
UNION ALL SELECT 'creditos', COUNT(*) FROM creditos
UNION ALL SELECT 'cuotas',   COUNT(*) FROM cuotas;
