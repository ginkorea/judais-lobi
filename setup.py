from setuptools import setup, find_packages

setup(
    name="lobi-cli",
    version="0.1.1",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "rich",
        "python-dotenv",
    ],
    entry_points={
        "console_scripts": [
            "lobi = lobi.cli:main",
        ],
    },
    author="Your Name",
    description="Lobi: a terminal-based GPT assistant",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/lobi-cli",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
