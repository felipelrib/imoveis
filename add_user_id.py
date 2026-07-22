import sys
import os

# Add src to pythonpath
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from infra.db import SessionLocal
from sqlalchemy import text

def run():
    with SessionLocal() as session:
        session.execute(text("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS user_id VARCHAR;"))
        session.commit()
        print("Column user_id added.")

if __name__ == "__main__":
    run()
