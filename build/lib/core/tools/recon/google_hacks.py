import time, random
from urllib.parse import quote
from core.tools.recon import ReconTool
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

class GoogleHacksTool(ReconTool):
    name = "google_hacks"
    description = "Uses LLM to generate Google dorks and performs cloaked searches using undetected Chrome."

    def __call__(self, target_package: dict, elf=None, use_llm=True, max_queries=5) -> dict:
        try:
            target = target_package.get("target", "")
            context = self.summarize_context(target_package)
            queries = []

            if use_llm and elf:
                prompt = f"""You are an expert OSINT recon agent.

Target: {target}

Context from previous reconnaissance:
{context}

Generate up to {max_queries} Google dork queries that could reveal public files, admin pages, sensitive configs, or exposed endpoints. Only return the dorks, one per line."""
                response = elf.client.chat.completions.create(
                    model=elf.model,
                    messages=[
                        {"role": "system", "content": "Generate advanced Google dorks."},
                        {"role": "user", "content": prompt}
                    ]
                )
                queries = [
                    line.strip().strip("`")
                    for line in response.choices[0].message.content.strip().splitlines()
                    if line.strip() and not line.strip().startswith("```")
                ]
            else:
                queries = [
                    f"site:{target} intitle:index.of",
                    f"site:{target} filetype:pdf",
                    f"site:{target} filetype:xls",
                    f"site:{target} inurl:login",
                    f"site:{target} ext:env | ext:sql | ext:log"
                ]

            all_results = []
            options = uc.ChromeOptions()
            options.headless = False  # Use headful mode for stealth
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-blink-features=AutomationControlled")
            driver = uc.Chrome(options=options)

            for q in queries:
                encoded = quote(q)
                search_url = f"https://www.google.com/search?q={encoded}"
                print(f"🔍 Querying: {q}")
                driver.get(search_url)
                time.sleep(random.randint(2, 5))  # Random sleep to avoid detection
                print(f"📄 Raw HTML for: {q}\n{'=' * 60}\n{driver.page_source[:5000]}\n{'=' * 60}\n")

                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.END)
                time.sleep(random.randint(1, 4))

                anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href^="http"]')
                results = []
                for a in anchors:
                    href = a.get_attribute("href")
                    title = a.text.strip()
                    # Heuristic: skip known Google service pages
                    if (
                            "google.com" in href
                            or "support.google.com" in href
                            or "accounts.google.com" in href
                            or "policies.google.com" in href
                    ):
                        continue
                    if href and title:
                        results.append({"title": title, "url": href})

                all_results.append({"query": q, "results": results})

            driver.quit()

            return {
                "tool": self.name,
                "success": True,
                "queries": queries,
                "results": all_results
            }

        except Exception as e:
            return {
                "tool": self.name,
                "success": False,
                "error": str(e)
            }


if __name__ == "__main__":
    from judais import JudAIs

    elf = JudAIs()
    tool = GoogleHacksTool()

    # Target with public exposure (educational, often indexed)
    tp = {
        "target": "mit.edu",
        "whois_lookup": {
            "raw_output": "Registrant: Massachusetts Institute of Technology"
        },
        "subdomains": [
            "ocw.mit.edu", "web.mit.edu", "libraries.mit.edu"
        ]
    }

    result = tool(tp, elf=elf, use_llm=True, max_queries=3)

    print("🔍 Google Hacks Tool Result")
    print("==========================")
    if result["success"]:
        for q in result["queries"]:
            print(f"\n📌 Query: {q}")
        print("\n--- Top Results ---")
        for entry in result["results"]:
            print(f"\n🔎 {entry['query']}")
            for res in entry["results"]:  # show top 3 per query
                print(f"Result: {res}")
    else:
        print(f"❌ Error: {result.get('error')}")
