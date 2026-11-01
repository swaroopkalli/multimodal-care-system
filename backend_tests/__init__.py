"""Development-time verification suite for the MindBridge backend.

    python -m backend_tests                 # run everything
    python -m backend_tests --only 7        # one area (number or name fragment)
    python -m backend_tests --strict        # unavailable services count as FAIL instead of SKIP
    python -m backend_tests --list
"""
