from setuptools import setup, find_packages

setup(
    name="django-tombstone",
    version="1.0.2",
    packages=find_packages(exclude=["tests*"]),
    install_requires=["Django>=4.2"],
    python_requires=">=3.10",
)
