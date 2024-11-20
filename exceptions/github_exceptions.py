from github import BadAttributeException, GithubException, BadCredentialsException, RateLimitExceededException, UnknownObjectException
from message_type import MessageType 

class GithubExceptionsHandler:
    def handle(e, desc):
        message = f"{desc} ({e.data.get('message')})" if desc else ({e.data.get('message')})
        text = f"{message} (Status Code: {e.status})"
        exception_map = {
            GithubException: lambda e: (
                MessageType.ERROR,
                {            
                400: f"[Status code: {e.status}] Bad Request: Check your input. {message}",
                401: f"[Status code: {e.status}] Unauthorized: Please check your credentials. {message}",
                404: f"[Status code: {e.status}] Not Found: The requested resource does not exist. {message}",
                500: f"[Status code: {e.status}] Internal Server Error: Try again later. {message}"
                }.get(getattr(e, "status", None), f"Github Error: {text}")
            ),
            BadCredentialsException: lambda e: (                
                MessageType.ERROR,
                {
                400: f"[Status code: {e.status}] Bad Request: Invalid object. {message}",
                401: f"[Status code: {e.status}] Unauthorized: Please check your credentials. {message}",
                404: f"[Status code: {e.status}] Not Found: The requested resource does not exist. {message}",
                409: f"[Status code: {e.status}] Conflict: Object cannot be accessed or deleted. {message}"
                }.get(getattr(e, "status", None), f"Github Error: {text}")
            ),
            RateLimitExceededException: lambda e: (
                MessageType.ERROR,
                {
                403: f"[Status code: {e.status}] Forbidden: Rate limit exceeded. {message}",
                429: f"[Status code: {e.status}] Too Many Requests. {message}"
                }.get(getattr(e, "status", None), f"Github Error: {text}")
            ),
            UnknownObjectException: lambda e: (MessageType.ERROR,{
                400: f"[Status code: {e.status}] Bad Request: Invalid object. {message}",
                404: f"[Status code: {e.status}] Not Found: The requested resource does not exist. {message}",
                409: f"[Status code: {e.status}] Conflict: Object cannot be accessed or deleted. {message}"
                }.get(getattr(e, "status", None), f"Github Error: {text}")),
            BadAttributeException: lambda e: (MessageType.ERROR, f"Bad Attribute Error: Attribute not found - {text}"),
        }
        error_message = exception_map.get(type(e), lambda e: (MessageType.ERROR, f"{str(e)}"))(e)
        return error_message
