# tools.py

import os
import re
import subprocess
import tempfile
import venv
import shutil
import random
import requests
from bs4 import BeautifulSoup
from pathlib import Path


class Tools:
    def __init__(self):
        self.registry = {
            "perform_web_search": self.perform_web_search,
            "fetch_page_content": self.fetch_page_content,
            "run_shell_command": self.run_shell_command,
            "run_python_code": self.run_python_code,
            "install_project": self.install_project,
            "extract_shell_command": self.extract_shell_command,
        }

    def list_tools(self):
        """Returns a list of all available tool names."""
        return list(self.registry.keys())

    def get_tool(self, name):
        """Returns the function handle for the given tool name, or None if not found."""
        return self.registry.get(name)

    def describe_tool(self, name):
        """Returns the docstring description for the given tool, if available."""
        tool = self.get_tool(name)
        return tool.__doc__ if tool else f"No such tool: {name}"

    @staticmethod
    def ensure_lobienv():
        """Ensure that .lobienv exists with pip."""
        lobienv = Path(".lobienv")
        python_bin = lobienv / "bin" / "python"
        if not python_bin.exists():
            venv.create(str(lobienv), with_pip=True)

    @staticmethod
    def is_root():
        """Returns True if running as root."""
        return os.geteuid() == 0

    def ask_for_sudo_permission(self):
        """Ask the user if Lobi may proceed with sudo-level actions."""
        flavors = [
            "Precious, Lobi needs your blessing to weave powerful magics...",
            "Lobi must open forbidden sockets, yesss. Shall we proceed?",
            "Without sudo, precious, Lobi cannot poke the network bits!",
            "Dangerous tricksies need root access... Will you trust Lobi?"
        ]
        try:
            prompt = random.choice(flavors)
            answer = input(f"⚠️ {prompt} (yes/no) ").strip().lower()
            return answer in ["yes", "y"]
        except EOFError:
            return False

    def perform_web_search(self, query, max_results=5, deep_dive=False, k_articles=3):
        """Searches DuckDuckGo and returns markdown results."""
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://html.duckduckgo.com/html/?q={query}"
        res = requests.post(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        results = []

        for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
            href = a.get("href")
            text = a.get_text()
            results.append({"title": text, "url": href})

        markdown_results = "\n".join([f"- [{r['title']}]({r['url']})" for r in results])

        if deep_dive and results:
            detailed = [self.fetch_page_content(r["url"]) for r in results[:k_articles]]
            return f"Deep dive into: {results[0]['title']}\nURL: {results[0]['url']}\n\nContents:\n{detailed[0]}"
        return markdown_results

    @staticmethod
    def fetch_page_content(url):
        """Fetches and returns visible text content from a URL, based on <p> tags."""
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, 'html.parser')
            return ' '.join(p.get_text() for p in soup.find_all('p'))
        except Exception as e:
            return f"Failed to fetch or parse: {str(e)}"

    @staticmethod
    def run_shell_command(command, timeout=10, unsafe=True, return_success=False):
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
            output = result.stdout.strip()
            if return_success:
                return output, 1
            return output
        except subprocess.CalledProcessError as e:
            output = e.stderr.strip() if e.stderr else str(e)
            if return_success:
                return output, 0
            return output
        except Exception as ex:
            if return_success:
                return f"⚠️ Unexpected error: {str(ex)}", 0
            return f"⚠️ Unexpected error: {str(ex)}"

    def run_python_code(self, code, unsafe=True, max_retries=2, return_success=False):
        """
        Executes Python code inside the dedicated .lobienv virtual environment.
        Automatically installs missing packages if needed.
        If a runtime error occurs, Lobi will attempt to repair and retry the code.
        If sudo privileges are needed, Lobi will ask and re-run just the Python code with sudo.
        """
        from lobi import Lobi

        self.ensure_lobienv()

        lobienv = Path(".lobienv")
        python_bin = lobienv / "bin" / "python"
        pip_bin = lobienv / "bin" / "pip"

        attempt = 0
        current_code = code
        elf = Lobi()

        while attempt <= max_retries:
            code_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".py")
            code_file.write(current_code)
            code_file.close()

            try:
                result = subprocess.run(
                    [str(python_bin), code_file.name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    output = result.stdout.strip()
                    if return_success:
                        return f"✅ Output:\n{output}", 1
                    return f"✅ Output:\n{output}"

                error_msg = result.stderr.strip()

                # Handle missing modules separately
                if "ModuleNotFoundError" in error_msg and unsafe:
                    missing_pkg = self._extract_missing_package(error_msg)
                    if missing_pkg:
                        print(f"📦 Missing package '{missing_pkg}' detected, installing...")
                        subprocess.run(
                            [str(pip_bin), "install", missing_pkg],
                            capture_output=True,
                            text=True
                        )
                        attempt += 1
                        continue  # Retry immediately after install

                # Handle permission-related errors
                if any(term in error_msg.lower() for term in
                       ["permission denied", "must be run as root", "operation not permitted"]):
                    if not self.is_root():
                        if self.ask_for_sudo_permission():
                            print("🧝‍♂️ Lobi thanks you, precious! Attempting to rerun Python code with sudo...")

                            sudo_result = subprocess.run(
                                ["sudo", str(python_bin), code_file.name],
                                capture_output=True,
                                text=True,
                                timeout=30
                            )

                            if sudo_result.returncode == 0:
                                output = sudo_result.stdout.strip()
                                if return_success:
                                    return f"✅ Output (with sudo):\n{output}", 1
                                return f"✅ Output (with sudo):\n{output}"
                            else:
                                output = sudo_result.stderr.strip()
                                if return_success:
                                    return f"❌ Sudo run failed:\n{output}", 0
                                return f"❌ Sudo run failed:\n{output}"

                        else:
                            if return_success:
                                return "❌ Lobi was not given permission to use root powers.", 0
                            return "❌ Lobi was not given permission to use root powers."

                # If a runtime error, attempt repair
                if attempt < max_retries:
                    print(f"⚠️ Error detected on attempt {attempt + 1}, trying to repair...")
                    current_code = self.repair_code_with_lobi(elf, current_code, error_msg)
                    attempt += 1
                    continue

                if return_success:
                    return f"❌ Python error after {max_retries} retries:\n{error_msg}", 0
                return f"❌ Python error after {max_retries} retries:\n{error_msg}"

            except subprocess.TimeoutExpired:
                if return_success:
                    return "⏱️ Python code timed out.", 0
                return "⏱️ Python code timed out."

            finally:
                os.remove(code_file.name)

        if return_success:
            return "❌ Could not fix or execute the code after multiple retries.", 0
        return "❌ Could not fix or execute the code after multiple retries."

    def install_project(self, path="."):
        """Installs a Python project into .lobienv."""
        self.ensure_lobienv()

        lobienv = Path(".lobienv")
        pip_bin = lobienv / "bin" / "pip"

        path = Path(path)
        install_cmd = None

        if (path / "setup.py").exists():
            install_cmd = [str(pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            install_cmd = [str(pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            install_cmd = [str(pip_bin), "install", "-r", "requirements.txt"]

        if install_cmd:
            result = subprocess.run(
                install_cmd,
                cwd=str(path),
                capture_output=True,
                text=True
            )
            return f"📦 Installed project from {path}:\n{result.stdout.strip() or result.stderr.strip()}"
        else:
            return "❌ No installable project found in the given directory."

    @staticmethod
    def extract_shell_command(text):
        """Extracts a bash command from Markdown/code-formatted output."""
        match = re.search(r"```bash\n(.+?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"```(.+?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"`([^`]+)`", text)
        if match:
            return match.group(1).strip()
        return text.strip()

    @staticmethod
    def _extract_missing_package(error_text):
        """Helper to extract missing package names from ModuleNotFoundError."""
        match = re.search(r"No module named '(.*?)'", error_text)
        return match.group(1) if match else None

    @staticmethod
    def extract_python_code(text):
        """Extracts Python code from Markdown/code-formatted output. Strips any leading 'python' if present."""
        match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            if code.startswith("python"):
                code = code[len("python"):].strip()
            return code

        match = re.search(r"```(.+?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        match = re.search(r"`([^`]+)`", text)
        if match:
            return match.group(1).strip()

        return text.strip()

    def repair_code_with_lobi(self, elf, original_code, error_message):
        """Ask Lobi to repair Python code based on the error message."""
        repair_prompt = [
            {"role": "system", "content": "You are a Python expert. Given broken Python code and an error message, fix the code. Return ONLY the corrected code inside a Markdown Python code block."},
            {"role": "user", "content": f"Broken code:\n```python\n{original_code}\n```\nError:\n{error_message}\nPlease fix and return."}
        ]

        completion = elf.client.chat.completions.create(
            model=elf.model,
            messages=repair_prompt
        )

        corrected_code = completion.choices[0].message.content
        return self.extract_python_code(corrected_code)
