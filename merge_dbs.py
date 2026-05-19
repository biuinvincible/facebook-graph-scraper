"""Merge worker DBs vào DB chính sau khi parallel scrape xong."""
import sqlite3
from pathlib import Path
from loguru import logger


def merge_dbs(main_db: str = "data/facebook_graph.db", n_workers: int = 5):
    main = sqlite3.connect(main_db)
    main.execute("PRAGMA journal_mode=WAL")
    merged = 0

    for i in range(n_workers):
        worker_db = f"data/worker_{i}.db"
        if not Path(worker_db).exists():
            continue
        src = sqlite3.connect(worker_db)
        try:
            for table in ["posts", "users", "comments", "edges_user_post",
                          "edges_user_user", "edges_user_comment",
                          "edges_post_post", "graph_samples"]:
                try:
                    rows = src.execute(f"SELECT * FROM {table}").fetchall()
                    if not rows:
                        continue
                    cols = len(rows[0])
                    placeholders = ",".join(["?"] * cols)
                    main.executemany(
                        f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})", rows
                    )
                    merged += len(rows)
                except Exception as e:
                    pass
            src.close()
            main.commit()
            logger.info(f"Merged worker_{i}.db")
        except Exception as e:
            logger.error(f"Failed to merge worker_{i}.db: {e}")

    main.close()
    logger.info(f"Merge complete: {merged} total rows")


if __name__ == "__main__":
    merge_dbs()
