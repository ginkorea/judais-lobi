# tools/fetch_page.py

from core.tools.tool import Tool
import requests
from bs4 import BeautifulSoup

class FetchPageTool(Tool):
    name = "fetch_page_content"
    description = "Fetches and extracts visible text from the given URL."

    def __call__(self, url):
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, 'html.parser')
            return ' '.join(p.get_text() for p in soup.find_all('p'))
        except Exception as e:
            return f"Failed to fetch or parse: {str(e)}"
