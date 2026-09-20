import enum


class FileProcessingStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"
