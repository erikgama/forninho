-- ============================================================
-- Forninho — consultas de warm-up da Airport DB (versão leve)
-- 9 consultas executáveis no total: 6 leves + 3 analíticas.
-- Objetivo: validar o modo two-phase rapidamente,
-- com uma carga controlada para evitar varreduras completas muito caras.
-- ============================================================
USE airportdb;

-- Leves (contagens e lookups simples) ------------------------------

-- 1. Contagem de companhias aéreas
SELECT COUNT(*) FROM airline;

-- 2. Contagem de aeroportos
SELECT COUNT(*) FROM airport;

-- 3. Total de países distintos (via airport_geo)
SELECT COUNT(DISTINCT country) FROM airport_geo WHERE country IS NOT NULL;

-- 4. Amostra de aeroportos com IATA
SELECT a.iata, a.name
FROM airport a
WHERE a.iata IS NOT NULL
LIMIT 20;

-- 5. Frota por companhia (pequena — só airline + airplane)
SELECT al.airlinename, COUNT(ap.airplane_id) AS frota
FROM airline al
JOIN airplane ap ON ap.airline_id = al.airline_id
GROUP BY al.airlinename
ORDER BY frota DESC
LIMIT 10;

-- 6. Quantidade de aeronaves por tipo
SELECT at.identifier AS tipo_aeronave, COUNT(ap.airplane_id) AS total
FROM airplane_type at
JOIN airplane ap ON ap.type_id = at.type_id
GROUP BY at.identifier
ORDER BY total DESC
LIMIT 10;

-- Analíticas (agregações sobre tabelas grandes) --------------------

-- 7. [ANALÍTICA] Aeroportos com maior movimentação de saída
SELECT
    a.name  AS airport,
    a.iata,
    ag.country,
    COUNT(f.flight_id) AS departures
FROM airport a
LEFT JOIN airport_geo ag ON ag.airport_id = a.airport_id
JOIN flight f ON f.`from` = a.airport_id
GROUP BY a.airport_id, a.name, a.iata, ag.country
ORDER BY departures DESC
LIMIT 15;

-- 8. [ANALÍTICA LEVE] Distribuição de reservas por faixa de preço
-- Amostra recente para evitar varredura completa em dezenas de milhões de reservas.
SELECT
    CASE
        WHEN b.price < 200  THEN 'Abaixo de $200'
        WHEN b.price < 500  THEN '$200 - $499'
        WHEN b.price < 1000 THEN '$500 - $999'
        ELSE 'Acima de $1000'
    END AS faixa_preco,
    COUNT(*)               AS total_reservas,
    ROUND(AVG(b.price), 2) AS preco_medio
FROM (
    SELECT price
    FROM booking
    ORDER BY booking_id DESC
    LIMIT 100000
) b
GROUP BY faixa_preco
ORDER BY preco_medio;

-- 9. [ANALÍTICA] Voos por dia da semana
SELECT
    DAYNAME(f.departure) AS dia_da_semana,
    COUNT(f.flight_id)   AS total_voos
FROM flight f
GROUP BY DAYNAME(f.departure), DAYOFWEEK(f.departure)
ORDER BY DAYOFWEEK(f.departure);
