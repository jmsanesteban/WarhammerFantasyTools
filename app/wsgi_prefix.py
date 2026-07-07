class PrefixMiddleware:
    """Lets the app be served under a URL prefix (e.g. '/wft') without
    touching route definitions: strips the prefix from PATH_INFO and moves
    it into SCRIPT_NAME so url_for()/redirects generate prefixed URLs.

    Deliberately tolerant: a request whose path does NOT start with the
    prefix is passed through unchanged, so the same running instance keeps
    answering unprefixed requests too (e.g. direct LAN health checks) while
    Cloudflare forwards prefixed public traffic.
    """

    def __init__(self, wsgi_app, prefix):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if self.prefix and (path == self.prefix or path.startswith(self.prefix + '/')):
            environ['SCRIPT_NAME'] = self.prefix
            environ['PATH_INFO'] = path[len(self.prefix):] or '/'
        return self.wsgi_app(environ, start_response)
