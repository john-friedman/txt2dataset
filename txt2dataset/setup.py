from setuptools import setup, find_packages
import os

# Read the contents of your README file
with open(os.path.join(os.path.dirname(__file__), '../readme.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="txt2dataset",
    version="0.3.0",
    packages=find_packages(),
    install_requires=[
        "pandas",
        "google-generativeai",
        "tqdm",
        "psutil"
    ],
    python_requires=">=3.8",
    description="Convert text to datasets",
    long_description=long_description,
    long_description_content_type='text/markdown',
)