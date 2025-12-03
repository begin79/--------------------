import asyncio
import sys
import os
import datetime
from urllib.parse import quote

# Add root dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.http import make_request_with_retry
from app.config import BASE_URL_SCHEDULE

from app.schedule import search_entities, API_TYPE_GROUP

async def test_search():
    query = "ИС1-227"
    print(f"Searching for: {query}")
    
    results, error = await search_entities(query, API_TYPE_GROUP)
    
    if error:
        print(f"❌ Error: {error}")
    elif results:
        print(f"✅ Found: {results}")
    else:
        print("❌ Nothing found")

if __name__ == "__main__":
    asyncio.run(test_search())
