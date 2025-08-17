from setuptools import setup, find_packages
import os

# Read the contents of your README file
with open(os.path.join(os.path.dirname(__file__), '../readme.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="txt2dataset",
    version="0.4.0",
    packages=find_packages(),
    install_requires=[
        "google-generativeai",
        "tqdm",
    ],
    description="Convert text to datasets",
    long_description=long_description,
    long_description_content_type='text/markdown',
)