-- =============================================================================
-- 01_esquema.sql · Crea las tablas de la cartera de créditos
-- Ejecutar conectado a la base "cartera":
--   psql -U postgres -d cartera -f sql/01_esquema.sql
-- =============================================================================

-- Si las tablas ya existen, se borran para empezar limpio (orden inverso a las FK)
DROP TABLE IF EXISTS cuotas, creditos, clientes, agencias CASCADE;

-- Dimensión: dónde se otorgó el crédito
CREATE TABLE agencias (
    agencia_id      SMALLINT     PRIMARY KEY,
    nombre_agencia  VARCHAR(60)  NOT NULL,
    region          VARCHAR(30)  NOT NULL
);

-- Dimensión: quién es el cliente
CREATE TABLE clientes (
    cliente_id       INTEGER       PRIMARY KEY,
    fecha_nacimiento DATE          NOT NULL,
    sexo             CHAR(1)       NOT NULL CHECK (sexo IN ('F', 'M')),
    tipo_empleo      VARCHAR(15)   NOT NULL,
    ingreso_mensual  NUMERIC(10,2) NOT NULL CHECK (ingreso_mensual > 0),
    agencia_id       SMALLINT      NOT NULL REFERENCES agencias (agencia_id)
);

-- Hecho principal: el préstamo
CREATE TABLE creditos (
    credito_id         INTEGER       PRIMARY KEY,
    cliente_id         INTEGER       NOT NULL REFERENCES clientes (cliente_id),
    agencia_id         SMALLINT      NOT NULL REFERENCES agencias (agencia_id),
    producto           VARCHAR(20)   NOT NULL,
    canal              VARCHAR(10)   NOT NULL,
    fecha_desembolso   DATE          NOT NULL,
    monto_desembolsado NUMERIC(12,2) NOT NULL CHECK (monto_desembolsado > 0),
    plazo_meses        SMALLINT      NOT NULL,
    tea                NUMERIC(6,4)  NOT NULL,   -- tasa efectiva anual (0.35 = 35 %)
    cuota_mensual      NUMERIC(12,2) NOT NULL,
    fecha_castigo      DATE                      -- NULL si no fue castigado
);

-- Detalle: el cronograma, una fila por cuota
CREATE TABLE cuotas (
    cuota_id          INTEGER       PRIMARY KEY,
    credito_id        INTEGER       NOT NULL REFERENCES creditos (credito_id),
    numero_cuota      SMALLINT      NOT NULL,
    fecha_vencimiento DATE          NOT NULL,
    monto_cuota       NUMERIC(12,2) NOT NULL,
    amortizacion      NUMERIC(12,2) NOT NULL,   -- parte que reduce la deuda (capital)
    interes           NUMERIC(12,2) NOT NULL,
    fecha_pago        DATE,                     -- NULL = todavía no pagada
    UNIQUE (credito_id, numero_cuota)
);

-- Índices: aceleran las búsquedas por las columnas que más filtramos/unimos
CREATE INDEX idx_creditos_cliente  ON creditos (cliente_id);
CREATE INDEX idx_cuotas_credito    ON cuotas (credito_id);
CREATE INDEX idx_cuotas_venc_pago  ON cuotas (fecha_vencimiento, fecha_pago);
