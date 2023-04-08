CREATE TABLE IF NOT EXISTS 
  steam_games_cache (
    app_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL UNIQUE,
    description TEXT,
    image TEXT NOT NULL,
    price FLOAT NOT NULL,
    review_count INT NOT NULL,
    review_summary TEXT NOT NULL,
    date_created DATETIME NOT NULL
  )