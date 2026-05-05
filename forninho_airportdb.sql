-- ============================================================
-- Forninho — consultas de warm-up da Airport DB
-- Banco: https://dev.mysql.com/doc/airportdb/en/
-- Schema oficial (flughafendb / airportdb) — 14 tabelas:
--   airline, airplane, airplane_type, airport, airport_geo,
--   airport_reachable, booking, employee, flight, flight_log,
--   flightschedule, passenger, passengerdetails, weatherdata
-- Notas importantes do schema:
--   * Não existe tabela `country`. País está em:
--       - airport_geo.country   (país do aeroporto)
--       - passengerdetails.country (país do passageiro)
--   * Não existe `aircraft` — é `airplane` (capacity) + `airplane_type`
--     (identifier/description). flight usa `airplane_id`.
--   * flight.`from` e flight.`to` são palavras reservadas — usar backticks.
--   * passenger não tem dados demográficos — estão em passengerdetails.
-- ============================================================
USE airportdb;

-- 1. Total de passageiros por país de origem
SELECT
    pd.country,
    COUNT(DISTINCT p.passenger_id) AS total_passageiros
FROM passenger p
JOIN passengerdetails pd ON pd.passenger_id = p.passenger_id
GROUP BY pd.country
ORDER BY total_passageiros DESC
LIMIT 20;

-- 2. Voos com maior número de passageiros embarcados
SELECT
    f.flight_id,
    f.flightno,
    a1.name AS origem,
    a2.name AS destino,
    COUNT(b.booking_id) AS total_reservas
FROM flight f
JOIN airport a1 ON a1.airport_id = f.`from`
JOIN airport a2 ON a2.airport_id = f.`to`
JOIN booking b  ON b.flight_id = f.flight_id
GROUP BY f.flight_id, f.flightno, a1.name, a2.name
ORDER BY total_reservas DESC
LIMIT 10;

-- 3. Receita total por companhia aérea
SELECT
    al.airlinename,
    COUNT(b.booking_id)           AS total_reservas,
    SUM(b.price)                  AS receita_total,
    ROUND(AVG(b.price), 2)        AS preco_medio_passagem
FROM airline al
JOIN flight  f ON f.airline_id = al.airline_id
JOIN booking b ON b.flight_id  = f.flight_id
GROUP BY al.airline_id, al.airlinename
ORDER BY receita_total DESC;

-- 4. Aeroportos com maior movimentação de saída
SELECT
    a.name  AS airport,
    a.iata,
    ag.country,
    COUNT(f.flight_id) AS saidas
FROM airport a
LEFT JOIN airport_geo ag ON ag.airport_id = a.airport_id
JOIN flight f ON f.`from` = a.airport_id
GROUP BY a.airport_id, a.name, a.iata, ag.country
ORDER BY saidas DESC
LIMIT 15;

-- 5. Passageiros com mais viagens realizadas
SELECT
    p.firstname,
    p.lastname,
    pd.country,
    COUNT(b.booking_id) AS total_voos
FROM passenger p
LEFT JOIN passengerdetails pd ON pd.passenger_id = p.passenger_id
JOIN booking b ON b.passenger_id = p.passenger_id
GROUP BY p.passenger_id, p.firstname, p.lastname, pd.country
ORDER BY total_voos DESC
LIMIT 10;

-- 6. Média de preço por rota (origem → destino)
SELECT
    a1.iata AS origem_iata,
    a2.iata AS destino_iata,
    COUNT(b.booking_id)      AS total_reservas,
    ROUND(AVG(b.price), 2)   AS preco_medio,
    ROUND(MIN(b.price), 2)   AS preco_minimo,
    ROUND(MAX(b.price), 2)   AS preco_maximo
FROM flight f
JOIN airport a1 ON a1.airport_id = f.`from`
JOIN airport a2 ON a2.airport_id = f.`to`
JOIN booking b  ON b.flight_id   = f.flight_id
GROUP BY a1.iata, a2.iata
ORDER BY total_reservas DESC
LIMIT 20;

-- 7. Voos por dia da semana
SELECT
    DAYNAME(f.departure) AS dia_da_semana,
    COUNT(f.flight_id)   AS total_voos
FROM flight f
GROUP BY DAYNAME(f.departure), DAYOFWEEK(f.departure)
ORDER BY DAYOFWEEK(f.departure);

-- 8. Tipos de aeronave mais utilizados
SELECT
    at.identifier        AS tipo_aeronave,
    COUNT(f.flight_id)   AS total_voos,
    COUNT(b.booking_id)  AS total_passageiros
FROM airplane_type at
JOIN airplane ap ON ap.type_id   = at.type_id
JOIN flight   f  ON f.airplane_id = ap.airplane_id
JOIN booking  b  ON b.flight_id   = f.flight_id
GROUP BY at.type_id, at.identifier
ORDER BY total_voos DESC
LIMIT 20;

-- 9. Passageiros que voaram para mais de 3 países diferentes
SELECT
    p.firstname,
    p.lastname,
    COUNT(DISTINCT ag.country) AS paises_visitados
FROM passenger p
JOIN booking     b  ON b.passenger_id = p.passenger_id
JOIN flight      f  ON f.flight_id    = b.flight_id
JOIN airport_geo ag ON ag.airport_id  = f.`to`
GROUP BY p.passenger_id, p.firstname, p.lastname
HAVING paises_visitados > 3
ORDER BY paises_visitados DESC
LIMIT 20;

-- 10. Rotas mais lucrativas
SELECT
    a1.iata AS from_iata,
    a2.iata AS to_iata,
    a1.name AS from_airport,
    a2.name AS to_airport,
    SUM(b.price) AS receita_total
FROM flight f
JOIN airport a1 ON a1.airport_id = f.`from`
JOIN airport a2 ON a2.airport_id = f.`to`
JOIN booking b  ON b.flight_id   = f.flight_id
GROUP BY a1.iata, a2.iata, a1.name, a2.name
ORDER BY receita_total DESC
LIMIT 10;

-- 11. Distribuição de reservas por faixa de preço
SELECT
    CASE
        WHEN b.price < 200  THEN 'Abaixo de $200'
        WHEN b.price < 500  THEN '$200 - $499'
        WHEN b.price < 1000 THEN '$500 - $999'
        ELSE 'Acima de $1000'
    END AS faixa_preco,
    COUNT(*)               AS total_reservas,
    ROUND(AVG(b.price), 2) AS preco_medio
FROM booking b
GROUP BY faixa_preco
ORDER BY preco_medio;

-- 12. Voos com ocupação acima de 80%
SELECT
    f.flightno,
    at.identifier          AS tipo_aeronave,
    ap.capacity            AS assentos,
    COUNT(b.booking_id)    AS assentos_reservados,
    ROUND((COUNT(b.booking_id) / ap.capacity) * 100, 1) AS ocupacao_pct
FROM flight f
JOIN airplane      ap ON ap.airplane_id = f.airplane_id
JOIN airplane_type at ON at.type_id     = ap.type_id
JOIN booking       b  ON b.flight_id    = f.flight_id
GROUP BY f.flight_id, f.flightno, at.identifier, ap.capacity
HAVING ocupacao_pct > 80
ORDER BY ocupacao_pct DESC
LIMIT 20;

-- 13. Total de reservas por mês
SELECT
    YEAR(f.departure)       AS ano,
    MONTH(f.departure)      AS mes,
    MONTHNAME(f.departure)  AS nome_mes,
    COUNT(b.booking_id)     AS total_reservas,
    SUM(b.price)            AS receita_total
FROM booking b
JOIN flight f ON f.flight_id = b.flight_id
GROUP BY YEAR(f.departure), MONTH(f.departure), MONTHNAME(f.departure)
ORDER BY ano, mes;

-- 14. Companhias aéreas com maior número de aeronaves distintas
SELECT
    al.airlinename,
    COUNT(DISTINCT f.airplane_id) AS aeronaves_distintas,
    COUNT(f.flight_id)            AS total_voos
FROM airline al
JOIN flight f ON f.airline_id = al.airline_id
GROUP BY al.airline_id, al.airlinename
ORDER BY aeronaves_distintas DESC;

-- 15. Passageiros que gastaram mais de $5000 no total
SELECT
    p.firstname,
    p.lastname,
    pd.country,
    COUNT(b.booking_id)        AS total_voos,
    ROUND(SUM(b.price), 2)     AS total_gasto
FROM passenger p
LEFT JOIN passengerdetails pd ON pd.passenger_id = p.passenger_id
JOIN booking b ON b.passenger_id = p.passenger_id
GROUP BY p.passenger_id, p.firstname, p.lastname, pd.country
HAVING total_gasto > 5000
ORDER BY total_gasto DESC
LIMIT 20;

-- 16. Aeroportos que nunca foram destino
SELECT
    a.airport_id,
    a.name,
    a.iata,
    ag.country
FROM airport a
LEFT JOIN airport_geo ag ON ag.airport_id = a.airport_id
WHERE a.airport_id NOT IN (
    SELECT DISTINCT f.`to` FROM flight f
)
LIMIT 50;

-- 17. Voo com maior duração (tempo entre departure e arrival)
SELECT
    f.flightno,
    a1.name  AS origem,
    a1.iata  AS origem_iata,
    a2.name  AS destino,
    a2.iata  AS destino_iata,
    f.departure,
    f.arrival,
    TIMESTAMPDIFF(MINUTE, f.departure, f.arrival) AS duracao_minutos
FROM flight f
JOIN airport a1 ON a1.airport_id = f.`from`
JOIN airport a2 ON a2.airport_id = f.`to`
WHERE f.arrival > f.departure
ORDER BY duracao_minutos DESC
LIMIT 10;

-- 18. Países com mais aeroportos
SELECT
    ag.country,
    COUNT(DISTINCT ag.airport_id) AS total_aeroportos
FROM airport_geo ag
WHERE ag.country IS NOT NULL AND ag.country <> ''
GROUP BY ag.country
ORDER BY total_aeroportos DESC
LIMIT 15;

-- 19. Ranking de passageiros por receita gerada para a companhia
SELECT
    al.airlinename,
    p.firstname,
    p.lastname,
    COUNT(b.booking_id)     AS voos_com_companhia,
    ROUND(SUM(b.price), 2)  AS total_gasto
FROM airline al
JOIN flight    f ON f.airline_id  = al.airline_id
JOIN booking   b ON b.flight_id   = f.flight_id
JOIN passenger p ON p.passenger_id = b.passenger_id
GROUP BY al.airline_id, al.airlinename, p.passenger_id, p.firstname, p.lastname
ORDER BY total_gasto DESC
LIMIT 15;

-- 20. Voos sem nenhum booking
SELECT
    f.flight_id,
    f.flightno,
    f.departure,
    a1.iata AS from_iata,
    a2.iata AS to_iata
FROM flight f
JOIN airport a1 ON a1.airport_id = f.`from`
JOIN airport a2 ON a2.airport_id = f.`to`
LEFT JOIN booking b ON b.flight_id = f.flight_id
WHERE b.booking_id IS NULL
LIMIT 20;

-- 21. Ticket médio por país de origem do passageiro
SELECT
    pd.country,
    COUNT(b.booking_id)    AS total_reservas,
    ROUND(AVG(b.price), 2) AS passagem_media
FROM passengerdetails pd
JOIN booking b ON b.passenger_id = pd.passenger_id
GROUP BY pd.country
ORDER BY passagem_media DESC
LIMIT 20;

-- 22. Aeronaves com maior receita acumulada
SELECT
    ap.airplane_id,
    at.identifier          AS tipo_aeronave,
    ap.capacity            AS assentos,
    COUNT(b.booking_id)    AS total_passageiros,
    ROUND(SUM(b.price), 2) AS receita_total
FROM airplane ap
JOIN airplane_type at ON at.type_id    = ap.type_id
JOIN flight        f  ON f.airplane_id = ap.airplane_id
JOIN booking       b  ON b.flight_id   = f.flight_id
GROUP BY ap.airplane_id, at.identifier, ap.capacity
ORDER BY receita_total DESC
LIMIT 10;

-- 23. Passageiros frequentes que voaram em mais de 5 companhias
SELECT
    p.firstname,
    p.lastname,
    COUNT(DISTINCT f.airline_id) AS companhias_voadas
FROM passenger p
JOIN booking b ON b.passenger_id = p.passenger_id
JOIN flight  f ON f.flight_id    = b.flight_id
GROUP BY p.passenger_id, p.firstname, p.lastname
HAVING companhias_voadas > 5
ORDER BY companhias_voadas DESC
LIMIT 20;

-- 24. Horário de pico de partidas por hora do dia
SELECT
    HOUR(f.departure)  AS hora_do_dia,
    COUNT(f.flight_id) AS total_partidas
FROM flight f
GROUP BY HOUR(f.departure)
ORDER BY total_partidas DESC;

-- 25. Top 10 rotas por número de passageiros distintos
SELECT
    a1.iata AS from_iata,
    a2.iata AS to_iata,
    COUNT(DISTINCT b.passenger_id) AS passageiros_unicos,
    COUNT(b.booking_id)            AS total_reservas
FROM flight f
JOIN airport a1 ON a1.airport_id = f.`from`
JOIN airport a2 ON a2.airport_id = f.`to`
JOIN booking b  ON b.flight_id   = f.flight_id
GROUP BY a1.iata, a2.iata
ORDER BY passageiros_unicos DESC
LIMIT 10;

-- 26. Receita média por assento ofertado
SELECT
    al.airlinename,
    SUM(ap.capacity)                              AS total_assentos_ofertados,
    ROUND(SUM(b.price) / SUM(ap.capacity), 2)     AS receita_por_assento
FROM airline al
JOIN flight   f  ON f.airline_id  = al.airline_id
JOIN airplane ap ON ap.airplane_id = f.airplane_id
JOIN booking  b  ON b.flight_id   = f.flight_id
GROUP BY al.airline_id, al.airlinename
ORDER BY receita_por_assento DESC;

-- 27. Último voo realizado por passageiro (top 20 mais recentes)
SELECT
    p.passenger_id,
    p.firstname,
    p.lastname,
    MAX(f.departure) AS ultimo_voo
FROM passenger p
JOIN booking b ON b.passenger_id = p.passenger_id
JOIN flight  f ON f.flight_id    = b.flight_id
GROUP BY p.passenger_id, p.firstname, p.lastname
ORDER BY ultimo_voo DESC
LIMIT 20;

-- 28. Companhias com melhor taxa de ocupação média
SELECT
    al.airlinename,
    ROUND(AVG(
        (SELECT COUNT(*) FROM booking b2 WHERE b2.flight_id = f.flight_id)
        / ap.capacity * 100
    ), 1) AS ocupacao_media_pct
FROM airline al
JOIN flight   f  ON f.airline_id   = al.airline_id
JOIN airplane ap ON ap.airplane_id = f.airplane_id
GROUP BY al.airline_id, al.airlinename
ORDER BY ocupacao_media_pct DESC
LIMIT 10;

-- 29. Reservas por trimestre
SELECT
    YEAR(f.departure)       AS ano,
    QUARTER(f.departure)    AS trimestre,
    COUNT(b.booking_id)     AS total_reservas,
    ROUND(SUM(b.price), 2)  AS receita_total
FROM booking b
JOIN flight f ON f.flight_id = b.flight_id
GROUP BY YEAR(f.departure), QUARTER(f.departure)
ORDER BY ano, trimestre;

-- 30. Sumário geral do banco
SELECT
    (SELECT COUNT(*) FROM passenger)                                       AS total_passageiros,
    (SELECT COUNT(*) FROM flight)                                          AS total_voos,
    (SELECT COUNT(*) FROM booking)                                         AS total_reservas,
    (SELECT COUNT(*) FROM airport)                                         AS total_aeroportos,
    (SELECT COUNT(*) FROM airline)                                         AS total_companhias,
    (SELECT COUNT(*) FROM airplane)                                        AS total_aeronaves,
    (SELECT COUNT(*) FROM airplane_type)                                   AS total_tipos_aeronave,
    (SELECT COUNT(DISTINCT country)
       FROM airport_geo
      WHERE country IS NOT NULL AND country <> '')                         AS total_paises,
    (SELECT ROUND(SUM(price), 2) FROM booking)                             AS receita_total;
