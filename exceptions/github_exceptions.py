from github import BadAttributeException, GithubException, BadCredentialsException, RateLimitExceededException, UnknownObjectException
from message_type import MessageType 
 
class GithubExceptionsHandler:
    def handle(e):
        text = f"{e.data.get('message')} (Status Code: {e.status})"
        exception_map = {
            GithubException: lambda e: (MessageType.ERROR, f"Github Error: {text}"),
            BadCredentialsException: lambda e: (MessageType.ERROR, f"Token Error: {text}"),
            RateLimitExceededException: lambda e: (MessageType.ERROR, f"Rate Limit Exceeded Error: {text}"),
            UnknownObjectException: lambda e: (MessageType.ERROR, f"Unknown Object Error: {text}"),
            BadAttributeException: lambda e: (MessageType.ERROR, f"Bad Attribute Error: Attribute not found - {text}"),
        }
        error_message = exception_map.get(type(e), lambda e: (MessageType.ERROR, f"{str(e)}"))(e)
        return error_message
