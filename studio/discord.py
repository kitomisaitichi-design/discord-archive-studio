"""Read-only Discord client. The only authenticated HTTP method is GET."""
import json
import hashlib
import time
import threading
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from .pacing import varied_delay


class AuthError(RuntimeError):
    def __init__(self, message, digest=None):
        super().__init__(message)
        self.digest = digest


class PermissionError(RuntimeError):
    pass


class Interrupted(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Discord:
    def __init__(self, token, control=None, status=None):
        self.token = token
        self.control = control or (lambda: True)
        self.status = status or (lambda text: None)
        self.lock = threading.RLock()
        self.throttle = {'next': 0}
        self.page_delay = 2.5
        self.timing_variation = 25

    @property
    def next_request(self):
        return self.throttle['next']

    @next_request.setter
    def next_request(self, value):
        self.throttle['next'] = value

    def wait(self, seconds):
        deadline = time.monotonic() + max(0, seconds)
        while time.monotonic() < deadline:
            if not self.control():
                raise Interrupted('Paused or cancelled.')
            time.sleep(min(.25, max(0, deadline-time.monotonic())))

    def get(self, route, **params):
        if not self.control():
            raise Interrupted('Paused or cancelled.')
        with self.lock:
            self.wait(self.next_request-time.monotonic())
            url = 'https://discord.com/api/v10/' + route.lstrip('/')
            if params:
                url += '?' + urlencode({k: v for k, v in params.items() if v is not None})
            for attempt in range(5):
                if not self.control():
                    raise Interrupted('Paused or cancelled.')
                request = Request(url, headers={'Authorization': self.token, 'User-Agent': 'DiscordArchiveStudio/1.0 (local read-only archive)', 'Accept': 'application/json'})
                try:
                    with build_opener(NoRedirect()).open(request, timeout=30) as response:
                        data = json.load(response)
                        remaining = response.headers.get('X-RateLimit-Remaining')
                        reset = float(response.headers.get('X-RateLimit-Reset-After', '0'))
                        pressure=self.throttle.get('pressure',1)
                        delay = max(varied_delay(self.page_delay*pressure,self.timing_variation), reset+1 if remaining == '0' else 0)
                        self.throttle['pressure']=1+(pressure-1)*.9
                        self.next_request = time.monotonic()+delay
                        return data
                except HTTPError as error:
                    if error.code == 401:
                        raise AuthError('Discord session expired. Reopen logged-in Discord to reconnect.', hashlib.sha256(self.token.encode()).hexdigest()) from None
                    if error.code in (403, 404):
                        raise PermissionError('Discord denied access to this channel or resource. Existing archive is preserved.') from None
                    if error.code == 429:
                        self.throttle['pressure']=min(4,self.throttle.get('pressure',1)*1.5)
                        try:
                            retry = float(json.load(error).get('retry_after', 60))
                        except (ValueError, TypeError):
                            retry = 60
                        retry = max(1, retry)
                        self.status('Discord rate limit; waiting %.0f seconds.' % retry)
                        self.wait(retry+1)
                        continue
                    if error.code < 500:
                        raise RuntimeError('Discord rejected the read request (HTTP %s).' % error.code) from None
                except (URLError, TimeoutError, OSError):
                    pass
                self.status('Network interrupted; retrying read request.')
                self.wait(min(60, 2**attempt * 2))
            raise RuntimeError('Discord read failed after bounded retries; resume this task later.')

    def guilds(self):
        result = [{'id': '0', 'name': 'Direct messages'}]
        after = None
        while True:
            page = self.get('users/@me/guilds', limit=100, after=after)
            result.extend(page)
            if len(page) < 100:
                break
            newest = max(page, key=lambda s: int(s['id']))['id']
            if newest == after:
                raise RuntimeError('Discord repeated a server page; stopped to avoid a loop.')
            after = newest
        return result

ALLOWED_MEDIA = {'cdn.discordapp.com', 'media.discordapp.net', 'cdn.discordapp.net'}


def media_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_MEDIA or parsed.username or parsed.password:
        raise ValueError('Attachment URL is not a Discord media URL.')
    return url


class MediaRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class MediaTooLarge(ValueError):
    pass


def download(url, destination, maximum, control, progress=lambda total: None):
    opener = build_opener(MediaRedirect())
    with opener.open(Request(media_url(url), headers={'User-Agent': 'DiscordArchiveStudio/1.0'}), timeout=45) as response:
        declared = response.headers.get('Content-Length')
        if declared and declared.isdigit() and int(declared) > maximum:
            raise MediaTooLarge('Skipped: attachment exceeds the selected size cap.')
        total = 0
        with destination.open('wb') as output:
            while True:
                if not control():
                    raise Interrupted('Media download paused.')
                chunk = response.read(min(256*1024, maximum-total+1))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise MediaTooLarge('Skipped: attachment exceeds the selected size cap.')
                output.write(chunk)
                progress(total)
    return total
