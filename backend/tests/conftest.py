import os


# Tests exercise authentication explicitly where needed; the local demo password
# in the ignored .env must not change unrelated API test expectations.
os.environ["APP_PASSWORD"] = ""
