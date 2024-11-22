from requests import HTTPError, Timeout, TooManyRedirects
from message_type import MessageType

class RequestExceptionsHandler:
    def handle(e):
        exception_map = {
            HTTPError: lambda e: (MessageType.ERROR, f"HTTP Error: {e}"),
            ConnectionError: lambda e: (MessageType.ERROR, f"Connection Error: {e}"),
            Timeout: lambda e: (MessageType.ERROR, f"Timed out: {e}"),
            TooManyRedirects: lambda e: (MessageType.ERROR, f"Too many redirects: {e}")}
        error_message = exception_map.get(type(e), lambda e: (MessageType.ERROR, f"{str(e)}"))(e)
        return error_message