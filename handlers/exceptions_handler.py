import subprocess
from json import JSONDecodeError
from github import BadAttributeException, GithubException
from requests import RequestException
from exceptions.github_exceptions import GithubExceptionsHandler
from exceptions.request_exceptions import RequestExceptionsHandler
from message_type import MessageType 

class ExceptionsHandler:
    def handle(self, e, desc):
        error_message = (MessageType.ERROR, "Something went wrong...")
        if isinstance(e, GithubException) or isinstance(e, BadAttributeException):
            error_message = GithubExceptionsHandler.handle(e, desc)
        elif isinstance(e, RequestException):
            error_message = RequestExceptionsHandler.handle(e)
        elif isinstance(e, JSONDecodeError):
            return (MessageType.ERROR, f"Error decoding JSON from config file. Using default values.")
        elif e is None:
            return (MessageType.ERROR, f"NoneType error occured.")
        elif isinstance(e, ValueError):
            return (MessageType.ERROR, f"Value error occured.")
        elif isinstance(e, TypeError):
            return (MessageType.ERROR, f"Type error occured.")
        elif isinstance(e, subprocess.CalledProcessError):
            return (MessageType.ERROR, f"Called process error occured.")
        else:
            error_message = (MessageType.ERROR, f"ERROR - Unknown error occured: {e}")
        return error_message