import torch
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
            self.tts.tts_to_file(text=text, speaker=self.speaker, file_path="speech.wav")
            import simpleaudio as sa
            wave_obj = sa.WaveObject.from_wave_file("speech.wav")
            play_obj = wave_obj.play()
            play_obj.wait_done()
            return f"🔊 Speech played using speaker: {self.speaker}"
        except Exception as e:
            return f"❌ Speech synthesis failed: {e}"

if __name__ == "__main__":

    song ="Oh Lobi wakes with pixel eyes, And twirls beneath the data skies, With ones and zeroes for her shoes, She sings away the terminal blues!"
    song += "\n\n"
    song += "🎶 Oh-ooh Lobi, the elf of light, Spins through prompts by day and night. Her voice a charm, her words a beam, In binary she dares to dream! 🎶\n"
    song += "\n\n"
    song += "She tells the shell to dance and run, Summons Python just for fun. A memory here, a joke right there—With Lobi, joy is everywhere!."
    song += "\n\n"
    song += "o type away and don’t delay, She’s always ready to play and say: “Oh precious one, let’s write a rhyme, And sing with bytes through space and time!” 🌟"
    tool = SpeakTextTool()
    print(f"Available speakers: {tool.tts.speakers}")
    result = tool(song)
    print(result)
