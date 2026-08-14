#!/usr/bin/env python3
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SC850SL 对焦助手</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; background: #101216; color: #eef2f6; }
    body { font-family: system-ui, sans-serif; padding: 12px; }
    h1 { margin: 0 0 6px; font-size: 22px; }
    #metrics { color: #9ff7c5; margin-bottom: 10px; }
    .hint { color: #ffd88a; margin: 8px 0; }
    .panel { margin: 12px 0; border: 1px solid #39414d; background: #090b0e; }
    .panel h2 { margin: 0; padding: 8px 10px; font-size: 17px; }
    #full { display: block; width: 100%; height: auto; }
    .native-scroll { overflow: auto; max-height: 68vh; }
    #crop { display: block; width: auto; max-width: none; height: auto; }
  </style>
</head>
<body>
  <h1>SC850SL /dev/video71 对焦助手</h1>
  <div id="metrics">正在连接...</div>
  <div class="hint">
    缓慢转动焦环，观察原始像素裁剪的车牌/栏杆边缘，并让 sharpness avg
    达到稳定峰值；不要只看缩小后的全景。
  </div>
  <section class="panel">
    <h2>低延迟全景（绿色框为测焦区域）</h2>
    <img id="full" alt="focus full preview">
  </section>
  <section class="panel">
    <h2>原始像素测焦区域（可横向滚动）</h2>
    <div class="native-scroll">
      <img id="crop" alt="native focus crop">
    </div>
  </section>
  <script>
    const full = document.getElementById("full");
    const crop = document.getElementById("crop");
    const metrics = document.getElementById("metrics");

    function pollImage(image, path) {
      const refresh = () => {
        image.onload = () => window.setTimeout(refresh, 80);
        image.onerror = () => window.setTimeout(refresh, 500);
        image.src = `${path}?t=${Date.now()}`;
      };
      refresh();
    }

    async function pollMetrics() {
      try {
        const response = await fetch(`/focus_metrics.json?t=${Date.now()}`, {
          cache: "no-store"
        });
        const data = await response.json();
        metrics.textContent =
          `采集 ${data.capture_width}×${data.capture_height} | ` +
          `原始裁剪 ${data.crop_width}×${data.crop_height} | ` +
          `sharpness ${data.sharpness.toFixed(1)} | ` +
          `avg ${data.sharpness_average.toFixed(1)} | ` +
          `frame ${data.frame_index}`;
      } catch (_) {
        metrics.textContent = "等待对焦预览数据...";
      }
      window.setTimeout(pollMetrics, 300);
    }

    window.addEventListener("load", () => {
      pollImage(full, "/frame.jpg");
      pollImage(crop, "/focus_crop.jpg");
      pollMetrics();
    });
  </script>
</body>
</html>
""".encode("utf-8")


FILES = {
    "/frame.jpg": Path("/tmp/frame.jpg"),
    "/focus_crop.jpg": Path("/tmp/focus_crop.jpg"),
    "/focus_metrics.json": Path("/tmp/focus_metrics.json"),
}


class FocusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self.send_payload(INDEX_HTML, "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        file_path = FILES.get(path)
        if file_path is None:
            self.send_error(404)
            return
        try:
            payload = file_path.read_bytes()
        except OSError:
            self.send_error(503, "Preview data is not ready")
            return
        content_type = mimetypes.guess_type(file_path.name)[0]
        self.send_payload(payload, content_type or "application/octet-stream")

    def send_payload(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), FocusHandler)
    server.daemon_threads = True
    print("Focus assistant listening on http://0.0.0.0:8080/", flush=True)
    server.serve_forever()
