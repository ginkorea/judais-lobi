# setup.py

from setuptools import setup, find_packages

# Import bootstrap function
try:
    from lobi.bootstrap import bootstrap_lobienv
    bootstrap_lobienv()
except Exception as e:
    print(f"⚠️ Warning: Bootstrap failed during install: {e}")

setup(
    name="lobi-cli",
    version="0.3.1",  # incremented for new voice feature!
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "rich",
        "python-dotenv",
        "beautifulsoup4",
        "requests",
        "faiss-cpu",
        "numpy",
        "pyttsx3"  # NEW for Voice (TTS)!
    ],
    entry_points={
        "console_scripts": [
            "lobi = lobi.cli:main",
            "lobi-bootstrap = lobi.bootstrap:bootstrap_lobienv",
        ],
    },
    author="Josh Gompert",
    description="Lobi: a terminal-based AI assistant with personality, memory, and now a speaking voice!",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ginkorea/lobi",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
