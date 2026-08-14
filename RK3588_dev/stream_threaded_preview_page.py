import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


INDEX_HTML = b"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RK3588 ALPR Live Preview</title>
  <style>
    html, body { margin: 0; min-height: 100%; background: #111; color: #eee; }
    body { font-family: sans-serif; display: grid; place-items: center; }
    main { width: min(100vw, 1280px); text-align: center; }
    h1 { margin: 12px 0 8px; font-size: 20px; font-weight: 500; }
    img { display: block; width: 100%; height: auto; background: #222; }
  </style>
</head>
<body>
  <main>
    <h1>RK3588 ALPR Live Preview</h1>
    <img src="/stream.mjpg" alt="ALPR live stream">
  </main>
</body>
</html>
"""


class CamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(INDEX_HTML)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(INDEX_HTML)
            return

        if self.path == "/frame.jpg":
            self.send_frame()
            return

        if self.path == "/stream.mjpg":
            self.send_stream()
            return

        self.send_error(404)

    def read_frame(self):
        try:
            with open("/tmp/frame.jpg", "rb") as frame_file:
                image = frame_file.read()
            return image if len(image) > 1000 else None
        except OSError:
            return None

    def send_frame(self):
        image = self.read_frame()
        if image is None:
            self.send_error(503, "Frame is not ready")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(image)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(image)

    def send_stream(self):
        self.send_response(200)
        self.send_header(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame"
        )
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()

        while True:
            try:
                image = self.read_frame()
                if image is not None:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(
                        f"Content-Length: {len(image)}\r\n\r\n".encode()
                    )
                    self.wfile.write(image)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                break
            except Exception:
                break

    def log_message(self, format, *args):
        print(
            f"{self.client_address[0]} - [{self.log_date_time_string()}] "
            f"{format % args}",
            flush=True,
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), CamHandler)
    server.daemon_threads = True
    print("ALPR preview page listening on http://0.0.0.0:8080/", flush=True)
    server.serve_forever()
