import os
import sys
import threading
import time
import webbrowser


ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")


def open_preview():
    time.sleep(3)
    webbrowser.open("http://localhost:8000")


def main():
    os.chdir(BACKEND)
    sys.path.insert(0, BACKEND)

    try:
      import uvicorn
    except Exception as exc:
      print("[ERROR] uvicorn import failed:", exc)
      print("Please install backend dependencies or check backend\\venv.")
      input("Press Enter to exit...")
      return 1

    print("========================================")
    print("Quant Hunter H5 Preview")
    print("========================================")
    print("Preview URL: http://localhost:8000")
    print("Keep this window open while previewing.")
    print("Press Ctrl+C to stop the server.")
    print("========================================")

    threading.Thread(target=open_preview, daemon=True).start()
    uvicorn.run(
        "app.main_simple:app",
        host="0.0.0.0",
        port=8000,
        lifespan="off",
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
