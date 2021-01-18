"""File for defining errors"""

class TimeoutException(Exception):
    """Raised after a timeout occurs."""
    pass

class InvalidParameter(Exception):
    """Raised if an invalid parameter is specified."""
    pass


class RetriesExceeded(Exception):
    """Raised after the maximum number of retries has been reached."""
    pass


class JSONParseError(Exception):
    """Raised when unable to parse JSON."""
    pass

class UnexpectedHTML(Exception):
    """
    Raised when JSON is expected, but HTML is returned instead
    This usually occurs when an internal service error occurs.
    """
    def __init__(self, message=None, html=None):
        super().__init__(message)
        self.html = html

class CallbackFunction(Exception):
    """Raised when the callback function does not have (only) one required positional argument"""
    pass


class VideoNotFound(Exception):
    """Raised when video cannot be found."""
    pass


class ParsingError(Exception):
    """Raised when video data cannot be parsed."""
    pass


class VideoUnavailable(Exception):
    """Raised when video is unavailable."""
    pass


class LoginRequired(Exception):
    """Raised when video is login is required (e.g. if video is private)."""
    pass


class VideoUnplayable(Exception):
    """Raised when video is unplayable (e.g. if video is members-only)."""
    pass


class NoChatReplay(Exception):
    """Raised when the video does not contain a chat replay."""
    pass


class InvalidURL(Exception):
    """Raised when the url given is invalid."""
    pass


class TwitchError(Exception):
    """Raised when an error occurs with a Twitch video."""
    pass


class NoContinuation(Exception):
    """Raised when there are no more messages to retrieve (in a live stream)."""
    pass


class CookieError(Exception):
    """Raised when an error occurs while loading a cookie file."""
    pass
