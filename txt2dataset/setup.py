from setuptools import setup, find_packages

setup(
    name="txt2dataset",
    version="0.02",
    packages=find_packages(),
    install_requires=[
        "pandas",
        "google-generativeai",
        "tqdm",
        "psutil"
    ],
    python_requires=">=3.8"
)