#tools/recon/whois.py

import subprocess
from core.tools.recon import ReconTool

class WhoisTool(ReconTool):
    name = "whois_lookup"
    description = "Performs a WHOIS lookup on the given domain or IP."

    def __call__(self, target: str) -> dict:
        try:
            _result = subprocess.run(["whois", target], capture_output=True, text=True, timeout=30)
            return {
                "tool": self.name,
                "success": True,
                "raw_output": _result.stdout
            }
        except subprocess.TimeoutExpired:
            return {
                "tool": self.name,
                "success": False,
                "error": "WHOIS lookup timed out."
            }
        except Exception as e:
            return {
                "tool": self.name,
                "success": False,
                "error": str(e)
            }


if __name__ == "__main__":
    tool = WhoisTool()
    t = "ginkorea.one"
    result = tool(t)

    print("WHOIS Lookup Result:")
    print("====================")
    if result["success"]:
        print(result["raw_output"])  # Print first 1000 chars
    else:
        print(f"Error: {result.get('error')}")
