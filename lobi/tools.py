# tools.py

import requests
from bs4 import BeautifulSoup
import subprocess
import shlex


def perform_web_search(query, max_results=5, deep_dive=False, k_articles=3):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://html.duckduckgo.com/html/?q={query}"
    res = requests.post(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    results = []

    for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
        href = a.get("href")
        text = a.get_text()
        results.append({"title": text, "url": href})

    markdown_results = "\n".join([f"- [{result['title']}]({result['url']})" for result in results])

    if deep_dive and results:
        # fetch the top k articles results
        detailed_results = []
        for result in results[:k_articles]:
            try:
                content = fetch_page_content(result["url"])
                detailed_results.append({"title": result["title"], "content": content})
            except Exception as e:
                detailed_results.append({"title": result["title"], "content": f"Failed to fetch or parse: {str(e)}"})

        first_result_url = results[0]["url"]
        detailed_content = fetch_page_content(first_result_url)
        return f"Deep dive into: {results[0]['title']}\nURL: {first_result_url}\n\nContents:\n{detailed_content}"

    return markdown_results


def fetch_page_content(url):
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, 'html.parser')
        content = ' '.join([p.get_text() for p in soup.find_all('p')])
        return content
    except Exception as e:
        return f"Failed to fetch or parse the page contents: {str(e)}"


def run_shell_command(command, timeout=10, unsafe=True):
    """
    Executes a shell command with full power (Lobi's hammer!).
    Set `unsafe=False` later if you want to add filtering.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            executable="/bin/bash"
        )
        return f"✅ Output:\n{result.stdout.strip()}"
    except subprocess.CalledProcessError as e:
        return f"❌ Error:\n{e.stderr.strip() if e.stderr else str(e)}"
    except subprocess.TimeoutExpired:
        return f"⏱️ Timed out after {timeout} seconds"
    except Exception as ex:
        return f"⚠️ Unexpected error: {str(ex)}"


TOOL_REGISTRY = {
    "perform_web_search": perform_web_search,
    "fetch_page_content": fetch_page_content,
    "run_shell_command": run_shell_command
}
