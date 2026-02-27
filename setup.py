from setuptools import setup, find_packages

VERSION = "0.7.2"

setup(
    name="judais-lobi",
    version=VERSION,
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "openai>=1.0.0",
        "mistralai>=1.0.0",       # ✅ Added for Mistral integration
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
        "dev": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
        "critic": [
            "anthropic>=0.30.0",
            "google-generativeai>=0.7.0",
            "keyring>=25.0.0",
            "pyyaml>=6.0",
        ],
        "treesitter": [
            "tree-sitter>=0.23.0",
            "tree-sitter-c>=0.21.0",
            "tree-sitter-cpp>=0.22.0",
            "tree-sitter-rust>=0.23.0",
            "tree-sitter-go>=0.23.0",
            "tree-sitter-javascript>=0.23.0",
            "tree-sitter-typescript>=0.23.0",
            "tree-sitter-java>=0.23.0",
        ],
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
    description="JudAIs & Lobi v0.7.2 — Dual-agent terminal AI with unified OpenAI/Mistral backend, memory, and tools",
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
