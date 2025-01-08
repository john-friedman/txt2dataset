from setuptools import setup, find_packages

setup(
    name="datasetbuilder",
    version="0.01",
    packages=find_packages(),
    install_requires=[
        "pandas",
        "google-generativeai",
        "tqdm",
        "psutil"
    ],
    python_requires=">=3.8"
)