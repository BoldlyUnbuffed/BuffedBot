ALTER TABLE
    letstry_ballots
ADD COLUMN
    finalized INTEGER NOT NULL DEFAULT FALSE ;

DROP VIEW letstry_ballots_view ;

CREATE VIEW
  letstry_ballots_view
AS
  SELECT
      ballot_id AS ballot_id,
      discord_thread_id AS discord_thread_id,
      date_created AS date_created,
      date_open AS date_open,
      date_close AS date_close,
      staging AS staging,
      finalized AS finalized,
      CASE
        WHEN finalized = TRUE THEN 'finalized'
        WHEN staging = TRUE THEN 'staging'
        WHEN date_open > DATETIME('NOW') THEN 'submitted'
        WHEN date_close > DATETIME('NOW') THEN 'open'
        ELSE 'closed'
      END AS state
  FROM
      letstry_ballots ;

CREATE TRIGGER
  elect_game_when_ballot_finalized
AFTER UPDATE OF finalized ON letstry_ballots
WHEN
  NEW.finalized = TRUE
BEGIN
  UPDATE
      letstry_games
  SET
      state = 'elected'
  WHERE
      game_id = (
          SELECT
              game_id
          FROM
              letstry_ballot_games
          WHERE
              letstry_ballot_games.ballot_id = NEW.ballot_id
          ORDER BY
              votes DESC
          LIMIT 1
      ) ;
END ;

UPDATE
  letstry_ballots
SET
  finalized = TRUE
WHERE
  date_close > DATETIME('NOW') ;