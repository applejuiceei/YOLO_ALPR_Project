import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RK3588 ALPR 4K Live Preview</title>
  <style>
    html, body { margin: 0; min-height: 100%; background: #111; color: #eee; }
    body { font-family: sans-serif; display: grid; place-items: center; }
    main { width: min(100vw, 3840px); text-align: center; }
    h1 { margin: 10px 0 6px; font-size: 20px; font-weight: 500; }
    #status { margin-bottom: 8px; color: #9fd; font-size: 14px; }
    img { display: block; width: 100%; height: auto; background: #222; }
  </style>
</head>
<body>
  <main>
    <h1>RK3588 ALPR 4K Live Preview</h1>
    <div id="status">正在连接 4K 识别画面...</div>
    <img id="preview" alt="ALPR 4K live preview">
  </main>
  <script>
    const image = document.getElementById("preview");
    const status = document.getElementById("status");

    function refreshFrame() {
      image.onload = () => {
        status.textContent =
          `${image.naturalWidth} x ${image.naturalHeight} · 实时识别画面`;
        window.setTimeout(refreshFrame, 1200);
      };
      image.onerror = () => {
        status.textContent = "画面暂时不可用，正在重试...";
        window.setTimeout(refreshFrame, 1500);
      };
      image.src = `/frame.jpg?t=${Date.now()}`;
    }

    window.addEventListener("load", () => {
      window.setTimeout(refreshFrame, 250);
    });
  </script>
</body>
</html>
""".encode("utf-8")


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(INDEX_HTML)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(INDEX_HTML)
            return

        if path == "/frame.jpg":
            self.send_frame()
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404)

    def send_frame(self):
        try:
            with open("/tmp/frame.jpg", "rb") as frame_file:
                image = frame_file.read()
        except OSError:
            image = b""

        if len(image) <= 1000:
            self.send_error(503, "Frame is not ready")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(image)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(image)

    def log_message(self, format, *args):
        print(
            f"{self.client_address[0]} - [{self.log_date_time_string()}] "
            f"{format % args}",
            flush=True,
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), PreviewHandler)
    server.daemon_threads = True
    print("4K polling preview listening on http://0.0.0.0:8080/", flush=True)
    server.serve_forever()
