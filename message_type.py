from enum import Enum


class MessageType(Enum):
    ERROR = '[ERROR]'
    WARNING = '[WARNING]'
    INFO = '[INFO]'
    SUCCESS = '[SUCCESS]'
    DEFAULT = ''