from setuptools import setup, find_packages

VERSION = "0.6.2"


setup(
    name="judais-lobi",
    version=VERSION,
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "openai>=1.0.0",
        "rich>=14.0.0",
        "python-dotenv>=1.1.0",
        "beautifulsoup4>=4.13.4",
        "requests>=2.32.3",
        "faiss-cpu>=1.11.0",
        "numpy>=1.26.4",
        "httpx>=0.28.1",
        "httpcore>=1.0.9",
        "h11>=0.16.0",
        "sniffio>=1.3.1",
        "pydantic>=2.11.0",
        "annotated-types>=0.7.0",
        "certifi>=2025.8.3",
    ],
    extras_require={
        "voice": [
            "simpleaudio>=1.0.4",
            "TTS>=0.22.0",
            "torch>=2.7.0",
            "torchaudio>=2.7.0",
            "soundfile>=0.13.1",
            "audioread>=3.0.1",
            "soxr>=0.5.0.post1",
            "transformers>=4.51.3",
            "huggingface-hub>=0.31.1",
            "tokenizers>=0.21.1",
            "safetensors>=0.5.3",
            "trainer>=0.0.36",
        ]
    },
    entry_points={
        "console_scripts": [
            "lobi = core.cli:main_lobi",
            "judais = core.cli:main_judais",
        ],
    },
    author="Josh Gompert",
    description="JudAIs & Lobi: Dual-agent terminal AI with memory, automation, and attitude",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ginkorea/judais-lobi",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
)
