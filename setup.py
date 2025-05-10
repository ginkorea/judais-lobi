from setuptools import setup, find_packages

setup(
    name="judais-lobi",
    version="0.5.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "openai>=1.0.0",
        "rich",
        "python-dotenv",
        "beautifulsoup4",
        "requests",
        "faiss-cpu",
        "numpy",
        "spacy[ja]==3.6.1",
        "simpleaudio~=1.0.4",  # For speech playback (C-backed)
    ],
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
