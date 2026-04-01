import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path, override=True)

url = os.getenv("DATABASE_URL")
print(f"DEBUG_URL: {url}")
if "5432" in url:
    print("MATCH: 5432 FOUND")
else:
    print("MATCH: 5432 NOT FOUND")
