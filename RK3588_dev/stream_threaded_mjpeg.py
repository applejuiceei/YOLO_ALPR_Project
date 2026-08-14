import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class CamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame"
        )
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()

        while True:
            try:
                file_path = "/tmp/frame.jpg"
                if os.path.exists(file_path):
                    try:
                        with open(file_path, "rb") as frame_file:
                            image = frame_file.read()

                        if len(image) > 1000:
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(
                                f"Content-Length: {len(image)}\r\n\r\n".encode()
                            )
                            self.wfile.write(image)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                    except OSError:
                        pass

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
    print("Threaded MJPEG preview listening on http://0.0.0.0:8080/", flush=True)
    server.serve_forever()
