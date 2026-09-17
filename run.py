"""
run.py — Unified Project Launcher
=================================
Convenient script to launch Backend (FastAPI) and/or Frontend (Streamlit)
with a single command.

Usage:
    python run.py             # Launches both Backend and Frontend
    python run.py --backend   # Launches Backend only
    python run.py --frontend  # Launches Frontend only
"""

import sys
import os
import subprocess
import time
import argparse
import signal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_backend():
    print("🚀 Starting FastAPI Backend at http://localhost:8000 ...")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.server:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload"
    ]
    return subprocess.Popen(cmd, cwd=BASE_DIR)

def run_frontend():
    print("🗺️ Starting Streamlit Frontend at http://localhost:8501 ...")
    cmd = [
        sys.executable, "-m", "streamlit",
        "run",
        os.path.join(BASE_DIR, "frontend", "app.py"),
        "--server.port", "8501"
    ]
    return subprocess.Popen(cmd, cwd=BASE_DIR)

def main():
    parser = argparse.ArgumentParser(description="Boston Smart Route Finder Launcher")
    parser.add_argument("--backend", action="store_true", help="Run only backend service")
    parser.add_argument("--frontend", action="store_true", help="Run only frontend service")
    args = parser.parse_args()

    procs = []

    try:
        if args.backend:
            p_back = run_backend()
            procs.append(p_back)
            p_back.wait()
        elif args.frontend:
            p_front = run_frontend()
            procs.append(p_front)
            p_front.wait()
        else:
            p_back = run_backend()
            procs.append(p_back)
            time.sleep(2)  # Give backend a moment to start
            p_front = run_frontend()
            procs.append(p_front)

            print("\n🌟 Both services are running:")
            print("   - Backend Docs: http://localhost:8000/docs")
            print("   - Frontend Web: http://localhost:8501")
            print("   Press Ctrl+C to terminate both.\n")

            while True:
                time.sleep(1)
                # Check if any process terminated unexpectedly
                for p in procs:
                    if p.poll() is not None:
                        return

    except KeyboardInterrupt:
        print("\n🛑 Shutting down services...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("✅ All services stopped.")

if __name__ == "__main__":
    main()
