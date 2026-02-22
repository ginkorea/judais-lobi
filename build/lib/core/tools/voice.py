import torch
import subprocess
import sys
import platform
from core.tools.tool import Tool
from TTS.api import TTS

class SpeakTextTool(Tool):
    name = "speak_text"
    description = "Speaks a given text aloud using a neural voice model (Coqui TTS)."

    def __init__(self, speaker=None, **kwargs):
        super().__init__(**kwargs)
        use_gpu = torch.cuda.is_available()
        self.tts = TTS(model_name="tts_models/en/vctk/vits", progress_bar=False, gpu=use_gpu)
        self.speaker = speaker or self._default_speaker()

    def _default_speaker(self):
        if self.tts.speakers:
            return self.tts.speakers[0]
        return None

    def __call__(self, text: str):
        try:
            import simpleaudio as sa
        except ImportError:
            print("🔊 `simpleaudio` not found. Attempting to install with ALSA support...")
            if not self._install_system_dependencies():
                return "❌ Could not install ALSA headers. Please install manually."
            subprocess.run([sys.executable, "-m", "pip", "install", "simpleaudio"], check=True)
            try:
                import simpleaudio as sa
            except ImportError:
                return "❌ `simpleaudio` install failed. Try: pip install judais-lobi[voice]"

        try:
            self.tts.tts_to_file(text=text, speaker=self.speaker, file_path="speech.wav")
            wave_obj = sa.WaveObject.from_wave_file("speech.wav")
            play_obj = wave_obj.play()
            play_obj.wait_done()
            return f"🔊 Speech played using speaker: {self.speaker}"
        except Exception as e:
            return f"❌ Speech synthesis failed: {e}"

    @staticmethod
    def _install_system_dependencies():
        system = platform.system().lower()
        if system != "linux":
            print("⚠️ Voice auto-install only supported on Linux.")
            return False

        if subprocess.call(["which", "dnf"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "dnf", "install", "-y", "alsa-lib-devel"]
        elif subprocess.call(["which", "apt"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "apt", "install", "-y", "libasound2-dev"]
        elif subprocess.call(["which", "pacman"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "pacman", "-S", "--noconfirm", "alsa-lib"]
        else:
            print("❗ Unsupported Linux distro. Install ALSA headers manually.")
            return False

        print(f"🛠 Installing: {' '.join(cmd)}")
        return subprocess.call(cmd) == 0

# 🧪 Test
if __name__ == "__main__":

    song = (
        "Oh Lobi wakes with pixel eyes,\n"
        "And twirls beneath the data skies,\n"
        "With ones and zeroes for her shoes,\n"
        "She sings away the terminal blues!\n\n"
        "🎶 Oh-ooh Lobi, the elf of light,\n"
        "Spins through prompts by day and night.\n"
        "Her voice a charm, her words a beam,\n"
        "In binary she dares to dream! 🎶\n\n"
        "She tells the shell to dance and run,\n"
        "Summons Python just for fun.\n"
        "A memory here, a joke right there—\n"
        "With Lobi, joy is everywhere!\n\n"
        "So type away and don’t delay,\n"
        "She’s always ready to play and say:\n"
        "“Oh precious one, let’s write a rhyme,\n"
        "And sing with bytes through space and time!” 🌟"
    )

    tool = SpeakTextTool()
    print(f"Available speakers: {tool.tts.speakers}")
    result = tool(song)
    print(result)
