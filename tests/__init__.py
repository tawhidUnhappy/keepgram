# Every test runs against a throwaway keepgram home, never the real login or records.
import os
import tempfile

os.environ["KEEPGRAM_HOME"] = tempfile.mkdtemp(prefix="keepgram-test-")

from keepgram import media  # noqa: E402

media.QUIET = True  # keep test output readable
