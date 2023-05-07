PRAGMA foreign_keys = 1 ;

BEGIN ;

CREATE TABLE IF NOT EXISTS
  letstry_games (
    game_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    url TEXT NOT NULL UNIQUE,
    state TEXT CHECK(state IN ('orphaned', 'submitted', 'rejected', 'accepted', 'elected', 'done')) NOT NULL DEFAULT 'submitted',
    date_created DATETIME NOT NULL DEFAULT current_timestamp
  );

CREATE TABLE IF NOT EXISTS
  letstry_proposals (
    discord_user_id INTEGER NOT NULL PRIMARY KEY,
    game_id INTEGER NOT NULL,
    date_created DATETIME NOT NULL DEFAULT current_timestamp,
    FOREIGN KEY (game_id) REFERENCES letstry_games (game_id)
      ON DELETE CASCADE
  );

CREATE TABLE IF NOT EXISTS
  letstry_ballots (
    ballot_id INTEGER PRIMARY KEY,
    discord_thread_id INTEGER NOT NULL UNIQUE,
    date_created DATETIME NOT NULL DEFAULT current_timestamp,
    date_open DATETIME NOT NULL DEFAULT current_timestamp,
    date_close DATETIME NOT NULL DEFAULT (DATETIME('NOW', '+3 days')),
    staging INTEGER NOT NULL DEFAULT TRUE
  );

  CREATE VIEW IF NOT EXISTS
    letstry_ballots_view
  AS
    SELECT
      ballot_id AS ballot_id,
      discord_thread_id AS discord_thread_id,
      date_created AS date_created,
      date_open AS date_open,
      date_close AS date_close,
      staging AS staging,
      CASE
        WHEN staging = TRUE THEN 'staging'
        WHEN date_open > DATETIME('NOW') THEN 'submitted'
        WHEN date_close > DATETIME('NOW') THEN 'open'
      ELSE
        'closed'
      END AS state
    FROM
      letstry_ballots ;


CREATE TABLE IF NOT EXISTS
  letstry_ballot_games (
    game_id INTEGER NOT NULL,
    ballot_id INTEGER NOT NULL,
    votes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, ballot_id),
    FOREIGN KEY (game_id) REFERENCES letstry_games (game_id)
      ON DELETE CASCADE,
    FOREIGN KEY (ballot_id) REFERENCES letstry_ballots (ballot_id)
      ON DELETE CASCADE
  );

CREATE TABLE IF NOT EXISTS
  letstry_ballot_votes (
    ballot_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    discord_user_id INTEGER NOT NULL,
    PRIMARY KEY (discord_user_id, ballot_id),
    FOREIGN KEY (ballot_id) REFERENCES letstry_ballots (ballot_id)
      ON DELETE CASCADE,
    FOREIGN KEY (game_id) REFERENCES letstry_games (game_id)
       ON DELETE CASCADE
  );

CREATE TRIGGER IF NOT EXISTS
  letstry_ballot_games_count_votes_insert
AFTER INSERT ON letstry_ballot_votes
BEGIN
  UPDATE
    letstry_ballot_games
  SET
    votes = (
      SELECT
        COUNT(*)
      FROM
        letstry_ballot_votes
      WHERE
        letstry_ballot_votes.game_id = letstry_ballot_games.game_id AND
        letstry_ballot_votes.ballot_id = letstry_ballot_games.ballot_id
    )
  WHERE
    letstry_ballot_games.ballot_id = NEW.ballot_id ;
END;

CREATE TRIGGER IF NOT EXISTS
  letstry_ballot_games_count_votes_delete
AFTER DELETE ON letstry_ballot_votes
BEGIN
  UPDATE
    letstry_ballot_games
  SET
    votes = (
      SELECT
        COUNT(*)
      FROM
        letstry_ballot_votes
      WHERE
        letstry_ballot_votes.game_id = letstry_ballot_games.game_id AND
        letstry_ballot_votes.ballot_id = letstry_ballot_games.ballot_id
    )
  WHERE
    letstry_ballot_games.ballot_id = OLD.ballot_id ;
END;

CREATE TRIGGER IF NOT EXISTS
  letstry_games_update_state_when_proposal_added
AFTER INSERT ON letstry_proposals
BEGIN
  UPDATE
    letstry_games
  SET
    state = (
      SELECT
        IIF(COUNT(*) > 0, 'submitted', state)
      FROM
        letstry_proposals
      WHERE
        letstry_games.game_id = letstry_proposals.game_id
    )
  WHERE
    state = 'orphaned' AND
    game_id = NEW.game_id ;
END;

CREATE TRIGGER IF NOT EXISTS
  letstry_games_update_state_when_proposal_removed
AFTER DELETE ON letstry_proposals
BEGIN
  UPDATE
    letstry_games
  SET
    state = (
      SELECT
        IIF(COUNT(*) = 0, 'orphaned', state)
      FROM
        letstry_proposals
      WHERE
        letstry_games.game_id = letstry_proposals.game_id
    )
  WHERE
    state = 'submitted' AND
    game_id = OLD.game_id ;
END;

CREATE TRIGGER IF NOT EXISTS
  prevent_insert_into_ballot_votes_if_ballot_not_open
BEFORE INSERT ON letstry_ballot_votes
BEGIN
  SELECT
    RAISE(FAIL, 'ballot not open')
  FROM
    letstry_ballots_view
  WHERE
    letstry_ballots_view.state != 'open' AND
    letstry_ballots_view.ballot_id = NEW.ballot_id ;
END;

CREATE TRIGGER IF NOT EXISTS
  prevent_delete_from_ballot_votes_if_ballot_not_open
BEFORE DELETE ON letstry_ballot_votes
BEGIN
  SELECT
    RAISE(FAIL, 'ballot not open')
  FROM
    letstry_ballots_view
  WHERE
    letstry_ballots_view.state != 'open' AND
    letstry_ballots_view.ballot_id = OLD.ballot_id ;
END;

CREATE TRIGGER IF NOT EXISTS
  prevent_insert_proposal_for_completed_games
BEFORE INSERT ON letstry_proposals
BEGIN
  SELECT
    RAISE(FAIL, 'game not open for proposal')
  FROM
    letstry_games
  WHERE
    letstry_games.game_id = NEW.game_id AND
    letstry_games.state NOT IN ('submitted', 'orphaned') ;
END;

CREATE TRIGGER IF NOT EXISTS
  accept_games_when_added_to_ballot
BEFORE INSERT ON letstry_ballot_games
BEGIN
  UPDATE
    letstry_games
  SET
    state = 'accepted'
  WHERE
    game_id = NEW.game_id AND
    state IN ('orphaned', 'submitted') ;
END;

CREATE TRIGGER IF NOT EXISTS
  prevent_ballot_games_if_game_has_invalid_state
BEFORE INSERT ON letstry_ballot_games
BEGIN
  SELECT
    RAISE(FAIL, 'game not open for ballots')
  FROM
    letstry_games
  WHERE
    game_id = NEW.game_id AND
    state IN ('rejected', 'elected', 'done') ;
END;

CREATE TRIGGER IF NOT EXISTS
  prevent_ballot_unstaging_if_it_has_no_games
BEFORE UPDATE OF staging ON letstry_ballots
WHEN
  NEW.staging = FALSE
BEGIN
  SELECT
    RAISE(FAIL, 'no games in ballot')
  FROM
    letstry_ballots
  WHERE NOT EXISTS(
    SELECT
      1
    FROM
      letstry_ballot_games
    WHERE
      ballot_id = NEW.ballot_id
  );
END ;

CREATE TABLE IF NOT EXISTS
  letstry_versions (
    version INTEGER PRIMARY KEY
  );

INSERT INTO
  letstry_versions
VALUES
  (0)
ON CONFLICT DO NOTHING ;

COMMIT ;