import os


# This seems to be needed in tests since each reverse of a URL triggers another import or `urls.py`
# which violates the django-ninja registry.
def pytest_generate_tests(metafunc):
    os.environ["NINJA_SKIP_REGISTRY"] = "yes"
