# tools.py

import os
import re
import subprocess
import tempfile
import venv
import shutil
import random
import requests
import pyttsx3
from pathlib import Path
from bs4 import BeautifulSoup

# Import Coqui TTS
try:
    from TTS.api import TTS as CoquiTTS
except ImportError:
    CoquiTTS = None

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
        self.tts_model = None

    def list_tools(self):
        return list(self.registry.keys())

    def get_tool(self, name):
        return self.registry.get(name)

    def describe_tool(self, name):
        tool = self.get_tool(name)
        return tool.__doc__ if tool else f"No such tool: {name}"

    @staticmethod
    def ensure_lobienv():
        lobienv = Path(".lobienv")
        python_bin = lobienv / "bin" / "python"
        if not python_bin.exists():
            venv.create(str(lobienv), with_pip=True)

    @staticmethod
    def is_root():
        return os.geteuid() == 0

    def ask_for_sudo_permission(self):
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

                if "ModuleNotFoundError" in error_msg and unsafe:
                    missing_pkg = self._extract_missing_package(error_msg)
                    if missing_pkg:
                        subprocess.run(
                            [str(pip_bin), "install", missing_pkg],
                            capture_output=True,
                            text=True
                        )
                        attempt += 1
                        continue

                if any(term in error_msg.lower() for term in
                       ["permission denied", "must be run as root", "operation not permitted"]):
                    if not self.is_root():
                        if self.ask_for_sudo_permission():
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

                if attempt < max_retries:
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
        self.ensure_lobienv()

        lobienv = Path(".lobienv")
        pip_bin = lobienv / "bin" / "pip"
        path = Path(path)

        if (path / "setup.py").exists():
            install_cmd = [str(pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            install_cmd = [str(pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            install_cmd = [str(pip_bin), "install", "-r", "requirements.txt"]
        else:
            return "❌ No installable project found in the given directory."

        result = subprocess.run(
            install_cmd,
            cwd=str(path),
            capture_output=True,
            text=True
        )
        return f"📦 Installed project from {path}:\n{result.stdout.strip() or result.stderr.strip()}"

    @staticmethod
    def extract_shell_command(text):
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
        match = re.search(r"No module named '(.*?)'", error_text)
        return match.group(1) if match else None

    @staticmethod
    def extract_python_code(text):
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

    def speak_text(self, text):
        """Speaks text aloud using Coqui TTS if available, falls back to pyttsx3."""
        try:
            if self.tts_model is None:
                print("🧝 Loading Lobi's magical voice...")
                from TTS.api import TTS as CoquiTTS
                self.tts_model = CoquiTTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=True,
                                          gpu=False)

            output_file = "/tmp/lobi_speech.wav"
            self.tts_model.tts_to_file(text=text, file_path=output_file)
            subprocess.run(["aplay", output_file], check=True)

        except Exception as e:
            print(f"⚠️ Coqui TTS failed, falling back to pyttsx3: {e}")
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', 140)
                engine.say(text)
                engine.runAndWait()
            except Exception as fallback_error:
                print(f"❌ Both TTS engines failed: {fallback_error}")

