import http.server
import socketserver

PORT = 3000

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class NoCacheHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

if __name__ == '__main__':
    socketserver.TCPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(("", PORT), NoCacheHTTPRequestHandler)
    print(f"Serving frontend multithreaded with no-cache at port {PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
