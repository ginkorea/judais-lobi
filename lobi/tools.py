#tools.py

import requests
from bs4 import BeautifulSoup


def perform_web_search(query, max_results=5, deep_dive=False):
    """
    Perform a DuckDuckGo search and optionally dive deep into the first result to read its contents.

    :param query: The search query string.
    :param max_results: The maximum number of search results to return.
    :param deep_dive: If True, fetch and display content from the top search result.
    :return: Markdown formatted search results or contents of the top result.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://html.duckduckgo.com/html/?q={query}"
    res = requests.post(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    results = []

    # Gather the search results
    for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
        href = a.get("href")
        text = a.get_text()
        results.append({"title": text, "url": href})

    # Format results as markdown
    markdown_results = "\n".join([f"- [{result['title']}]({result['url']})" for result in results])

    # If deep dive is requested, fetch and display the first result in detail
    if deep_dive and results:
        first_result_url = results[0]["url"]
        detailed_content = fetch_page_content(first_result_url)
        return f"Deep dive into: {results[0]['title']}\nURL: {first_result_url}\n\nContents:\n{detailed_content}"

    return markdown_results


def fetch_page_content(url):
    """
    Fetches the main content from a given URL.

    :param url: URL of the page to fetch content from.
    :return: Text content of the page.
    """
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract main content; this example assumes that the main text lies within <p> tags.
        # This is a simplification and may need to be adjusted to fit specific site structures.
        content = ' '.join([p.get_text() for p in soup.find_all('p')])
        return content
    except Exception as e:
        return f"Failed to fetch or parse the page contents: {str(e)}"


