import os
import tempfile

# Point the app at a throwaway database before anything imports app.db
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="puntclub-test-")
os.environ["ADMIN_PASSWORD"] = "test-pw"
